# -*- coding: utf-8 -*-
"""
ReAct Agent 主循环
==================
实现"推理 → 行动 → 观察"的循环，直到产出最终回答。

核心流程（单轮对话）：
  1. 将用户输入写入工作记忆
  2. Skill 路由（LLM 语义判断 → 激活工作流；失败时回退关键词匹配）
  3. 若有工具可用 → 进入 ReAct 循环：
     Thought → Action → (执行工具) → Observation → Thought → ... → Final Answer
  4. 若无工具可用 → 直接调用 DeepSeek 对话
  5. 将最终回答写入工作记忆

与工作记忆的协作：
  - 工作记忆提供"对话上下文"（摘要 + 近期对话），注入每轮 ReAct 提示词
  - ReAct 的 Thought/Action/Observation 是瞬态的，不写入工作记忆
  - 一轮结束后，仅将"用户输入 + 最终回答"写入工作记忆

Skill 路由机制（升级版）：
  - 优先用 LLM 语义判断该激活哪些 skill（能理解同义词、迂回表达）
  - LLM 调用失败时，自动回退到关键词字符串匹配（保证可用性）
  - 路由结果记录在 self._route_method，供日志输出区分
"""
import re
import json
import queue
import threading
from difflib import get_close_matches

from llm.deepseek_client import DeepSeekClient
from core.memory import WorkingMemory
from core.declarative_memory import DeclarativeMemory
from core.prompts import (
    REACT_SYSTEM_TEMPLATE,
    DIRECT_CHAT_SYSTEM,
    SUMMARIZE_PROMPT,
    SKILL_ROUTING_TEMPLATE,
    DECLARATIVE_MEMORY_INJECTION,
)
from config import MAX_ITERATIONS, MEMORY_WINDOW, TEMPERATURE, DECLARATIVE_MEMORY_PATH


class ParsedResponse:
    """解析 LLM 输出后的结构化结果"""

    def __init__(self, thought="", action="", action_input="", final_answer=""):
        self.thought = thought            # 思考过程
        self.action = action              # 工具名称
        self.action_input = action_input  # 工具输入（JSON 字符串）
        self.final_answer = final_answer  # 最终回答

    @property
    def has_action(self):
        return bool(self.action)

    @property
    def has_final_answer(self):
        return bool(self.final_answer)


class ReactAgent:
    """
    ReAct Agent：多轮对话 + 工具调用 + 工作记忆。

    参数
    ----
    tool_registry : ToolRegistry
        工具注册表（包含所有已注册的工具实例）
    skill_loader  : SkillLoader
        渐进式技能加载器
    verbose       : bool
        是否打印推理过程（Thought/Action/Observation）
    """

    def __init__(self, tool_registry, skill_loader=None, verbose=True):
        self.llm = DeepSeekClient()
        self.tools = tool_registry
        self.skills = skill_loader
        self.verbose = verbose

        # 记录本次 skill 路由使用的方法（"llm" 或 "keyword"），供日志输出
        self._route_method = ""

        # 创建工作记忆，传入摘要函数（用 DeepSeek 生成摘要）
        self.memory = WorkingMemory(
            window_size=MEMORY_WINDOW,
            summarizer=self._summarize,
        )

        # 创建声明性记忆（持久化用户偏好，从 memory.md 加载）
        # 与工作记忆的区别：
        #   - 工作记忆 = 短期对话上下文（滑动窗口 + 摘要，重启丢失）
        #   - 声明性记忆 = 长期用户档案（持久化到文件，重启不丢失）
        # 声明性记忆采用手动触发更新，不会自动从对话中提取
        self.declarative_memory = DeclarativeMemory(DECLARATIVE_MEMORY_PATH)

    def chat(self, user_input):
        """
        处理一轮用户对话（非流式，等待完整结果后返回）。

        参数
        ----
        user_input : str  用户输入

        返回
        ----
        str : 助手的最终回答
        """
        # ---- 第 1 步：渐进式匹配并加载 Skill ----
        active_tools, skill_addon = self._load_skills(user_input)

        if self.verbose and self.skills:
            matched = self.skills.last_matched
            if matched:
                names = [s["name"] for s in matched]
                method = self._route_method or "keyword"
                print(f"  [Skill] 已加载技能({method}): {', '.join(names)}")
            else:
                method = self._route_method or "keyword"
                print(f"  [Skill] 无匹配技能({method})，进入纯对话模式")

        # ---- 第 2 步：根据是否有工具选择路径 ----
        if active_tools:
            answer = self._react_loop(user_input, active_tools, skill_addon)
        else:
            answer = self._direct_chat(user_input)

        # ---- 第 3 步：写入工作记忆 ----
        self.memory.add_user(user_input)
        self.memory.add_assistant(answer)

        return answer

    def chat_streaming(self, user_input):
        """
        处理一轮用户对话（流式版，逐步 yield 事件）。

        与 chat() 的区别：
          - chat()    返回完整字符串
          - chat_streaming() 是生成器，yield 事件字典

        事件类型：
          {"type": "trace", "step": {"type": "skill|thought|...", "text": "..."}}
            → 推理过程步骤（前端逐步展示）
          {"type": "answer_chunk", "text": "..."}
            → 最终回答的文本片段（前端打字机效果）
          {"type": "done", "memory_size": int}
            → 全部完成，附带工作记忆条数

        参数
        ----
        user_input : str  用户输入

        返回
        ----
        generator : 每次 yield 一个事件字典
        """
        # ---- 第 1 步：渐进式匹配并加载 Skill ----
        active_tools, skill_addon = self._load_skills(user_input)

        # 发送 Skill 路由结果作为 trace 事件
        if self.skills:
            matched = self.skills.last_matched
            if matched:
                names = [s["name"] for s in matched]
                method = self._route_method or "keyword"
                yield {"type": "trace", "step": {
                    "type": "skill",
                    "text": f"已加载技能({method}): {', '.join(names)}",
                }}
            else:
                method = self._route_method or "keyword"
                yield {"type": "trace", "step": {
                    "type": "skill",
                    "text": f"无匹配技能命中，进入纯对话模式",
                }}

        # ---- 第 2 步：根据是否有工具选择路径 ----
        if active_tools:
            # ReAct 模式：推理过程非流式（需要完整响应来解析），
            # 最终回答使用真实流式
            answer = yield from self._react_loop_streaming(
                user_input, active_tools, skill_addon
            )
        else:
            # 纯对话模式：直接流式返回 LLM 响应（真正的逐字流式）
            answer = yield from self._direct_chat_streaming(user_input)

        # ---- 第 3 步：写入工作记忆 ----
        self.memory.add_user(user_input)
        self.memory.add_assistant(answer)

        # 发送完成事件
        yield {"type": "done", "memory_size": len(self.memory.items)}

    # ==================== Skill 加载 ====================

    def _load_skills(self, user_input):
        """
        加载技能（升级版：LLM 语义路由 + 关键词回退）。

        路由优先级：
          1. LLM 语义路由 —— 把所有 skill 的描述交给 LLM，让它判断该激活哪些
          2. 关键词匹配   —— LLM 调用失败或解析异常时，回退到字符串匹配

        匹配到 skill 后，激活其工作流正文（注入 ReAct 提示词）并收集所需工具。

        返回
        ----
        (active_tools, skill_addon) : (list[BaseTool], str)
        """
        active_tools = []
        skill_addon = ""

        if not self.skills:
            # 无技能加载器 → 使用所有工具作为后备
            return self.tools.all_tools(), ""

        # ---- 优先用 LLM 语义路由 ----
        matched = self._route_skills_with_llm(user_input)

        # ---- LLM 路由失败 → 回退到关键词匹配 ----
        if matched is None:
            matched = self.skills.match(user_input)
            self._route_method = "keyword"
        else:
            self._route_method = "llm"

        # ---- 激活匹配到的技能：收集工具 + 工作流正文 ----
        for skill in matched:
            addon = self.skills.activate(skill)
            # 收集该技能需要的工具
            for tool_name in skill.get("required_tools", []):
                tool = self.tools.get(tool_name)
                if tool and tool not in active_tools:
                    active_tools.append(tool)
            # 收集工作流正文作为系统提示词补充
            if addon:
                skill_addon += addon + "\n\n"

        return active_tools, skill_addon

    def _route_skills_with_llm(self, user_input):
        """
        用 LLM 语义判断该激活哪些技能。

        把所有 skill 的 name + description 拼成提示词，让 LLM 输出 JSON 数组。
        相比关键词匹配，能理解同义词、迂回表达和间接描述。

        参数
        ----
        user_input : str  用户输入

        返回
        ----
        list[dict] : 匹配到的技能元数据列表
        None       : LLM 调用失败或解析异常（调用方应回退到关键词匹配）
        """
        all_skills = self.skills.list_all()
        if not all_skills:
            return []

        # ---- 构建 skill 列表描述 ----
        skill_list = "\n".join(
            f"- {s['name']}: {s['description']}" for s in all_skills
        )
        prompt = SKILL_ROUTING_TEMPLATE.format(skill_list=skill_list)

        # ---- 调用 LLM 做路由判断 ----
        try:
            response = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_input},
                ],
                temperature=0.1,   # 低温度保证路由判断稳定
                max_tokens=200,    # 只需要短 JSON，限制长度省成本
            )
        except Exception as e:
            if self.verbose:
                print(f"  [Skill] LLM 路由调用失败: {e}，回退关键词匹配")
            return None

        # ---- 解析 LLM 返回的 JSON 数组 ----
        skill_names = self._parse_skill_names(response)
        if skill_names is None:
            if self.verbose:
                print(f"  [Skill] LLM 路由返回无法解析: {response[:80]}，回退关键词匹配")
            return None

        # ---- 根据名称匹配 skill 元数据 ----
        matched = []
        for name in skill_names:
            for skill in all_skills:
                if skill["name"] == name:
                    matched.append(skill)
                    break

        self.skills.last_matched = matched
        return matched

    @staticmethod
    def _parse_skill_names(response):
        """
        从 LLM 返回中提取技能名称列表。

        LLM 可能返回：
          - 纯 JSON 数组：["poetry_search"]
          - 带解释文字的混合内容：...分析... ["poetry_search"] ...
          - 空数组：[]

        返回
        ----
        list[str] : 技能名称列表（可能为空）
        None      : 完全无法解析出 JSON
        """
        response = response.strip()
        # 尝试直接解析整段为 JSON
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return [str(s) for s in result]
        except json.JSONDecodeError:
            pass
        # 回退：用正则提取第一个 JSON 数组片段
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return [str(s) for s in result]
            except json.JSONDecodeError:
                pass
        return None

    # ==================== ReAct 循环 ====================

    def _react_loop(self, user_input, active_tools, skill_addon):
        """
        ReAct 推理循环：Thought → Action → Observation → ... → Final Answer
        """
        # 构建工具描述
        tool_desc = "\n".join(t.get_usage() for t in active_tools)

        # 构建系统提示词
        system_prompt = REACT_SYSTEM_TEMPLATE.format(
            tool_descriptions=tool_desc,
            skill_addon=skill_addon or "（无特定技能上下文）",
        )

        # 注入声明性记忆（用户偏好档案，让 Agent 回答时参考用户习惯）
        # 仅在有记忆内容时注入，避免空内容浪费 token
        dm_context = self.declarative_memory.get_context()
        if dm_context:
            system_prompt += "\n\n" + DECLARATIVE_MEMORY_INJECTION.format(
                memory_content=dm_context
            )

        # 获取工作记忆上下文（之前对话的摘要 + 近期对话）
        memory_context = self.memory.get_context()

        # ReAct 草稿本：累积 Thought/Action/Observation
        scratchpad = ""

        for iteration in range(MAX_ITERATIONS):
            # 构建用户消息（记忆上下文 + 当前问题 + 草稿本）
            user_msg = self._build_user_message(memory_context, user_input, scratchpad)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            # 调用 DeepSeek（用 "Observation:" 作为停止符，防止 LLM 编造观察结果）
            try:
                response = self.llm.chat(
                    messages,
                    stop=["Observation:"],
                    temperature=TEMPERATURE,
                )
            except Exception as e:
                return f"LLM 调用失败: {e}"

            # 解析 LLM 输出
            parsed = self._parse_response(response)

            # 情况 1：已得到最终回答
            if parsed.has_final_answer:
                if self.verbose:
                    print(f"  [Thought] {parsed.thought}")
                    print(f"  [Final Answer] {parsed.final_answer[:100]}...")
                return parsed.final_answer

            # 情况 2：需要调用工具
            if parsed.has_action:
                if self.verbose:
                    print(f"  [Thought] {parsed.thought}")
                    print(f"  [Action] {parsed.action} | Input: {parsed.action_input}")

                # 执行工具
                observation = self._execute_tool(parsed.action, parsed.action_input)

                if self.verbose:
                    preview = observation[:200].replace("\n", " ")
                    print(f"  [Observation] {preview}...")

                # 追加到草稿本
                scratchpad += (
                    f"Thought: {parsed.thought}\n"
                    f"Action: {parsed.action}\n"
                    f"Action Input: {parsed.action_input}\n"
                    f"Observation: {observation}\n\n"
                )
            else:
                # 情况 3：无法解析 → 当作最终回答
                return response.strip()

        # 超过最大循环次数
        return "抱歉，我已经尝试了多次但仍未能完全回答您的问题，请尝试换一种方式提问。"

    def _react_loop_streaming(self, user_input, active_tools, skill_addon):
        """
        ReAct 推理循环的流式版本。

        设计说明：
          - ReAct 循环中的中间步骤（Thought/Action/Observation）需要完整的 LLM
            响应才能解析，所以中间步骤仍用非流式 chat()
          - 当解析到 Final Answer 时，改用 chat_stream() 真实流式输出最终回答
          - 每个推理步骤通过 yield trace 事件发送给前端

        返回
        ----
        str : 最终回答的完整文本（同时通过 yield 发送了流式片段）
        """
        # 构建工具描述
        tool_desc = "\n".join(t.get_usage() for t in active_tools)

        # 构建系统提示词
        system_prompt = REACT_SYSTEM_TEMPLATE.format(
            tool_descriptions=tool_desc,
            skill_addon=skill_addon or "（无特定技能上下文）",
        )

        # 注入声明性记忆
        dm_context = self.declarative_memory.get_context()
        if dm_context:
            system_prompt += "\n\n" + DECLARATIVE_MEMORY_INJECTION.format(
                memory_content=dm_context
            )

        # 获取工作记忆上下文
        memory_context = self.memory.get_context()

        # ReAct 草稿本
        scratchpad = ""

        for iteration in range(MAX_ITERATIONS):
            user_msg = self._build_user_message(memory_context, user_input, scratchpad)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            # 中间步骤用非流式（需要完整响应来解析 Thought/Action/Final Answer）
            try:
                response = self.llm.chat(
                    messages,
                    stop=["Observation:"],
                    temperature=TEMPERATURE,
                )
            except Exception as e:
                error_msg = f"LLM 调用失败: {e}"
                yield {"type": "answer_chunk", "text": error_msg}
                return error_msg

            parsed = self._parse_response(response)

            # 情况 1：已得到最终回答 → 流式输出
            if parsed.has_final_answer:
                # 发送 Thought 作为 trace
                if parsed.thought:
                    yield {"type": "trace", "step": {
                        "type": "thought", "text": parsed.thought,
                    }}

                # 用流式重新调用 LLM 获取最终回答
                # 构建一个只要求最终回答的消息（不带 stop 序列）
                final_messages = list(messages)
                final_messages.append({"role": "assistant", "content": response})
                final_messages.append({
                    "role": "user",
                    "content": "请直接输出 Final Answer 的内容，不要重复之前的思考过程。",
                })

                full_answer = ""
                try:
                    for chunk in self.llm.chat_stream(
                        final_messages, temperature=TEMPERATURE,
                    ):
                        full_answer += chunk
                        yield {"type": "answer_chunk", "text": chunk}
                except Exception as e:
                    # 流式失败时回退到已解析的 final_answer
                    full_answer = parsed.final_answer
                    yield {"type": "answer_chunk", "text": full_answer}

                return full_answer

            # 情况 2：需要调用工具 → 发送 trace 事件
            if parsed.has_action:
                yield {"type": "trace", "step": {
                    "type": "thought", "text": parsed.thought,
                }}
                yield {"type": "trace", "step": {
                    "type": "action",
                    "text": f"{parsed.action} | Input: {parsed.action_input}",
                }}

                # 执行工具（支持分发事件实时推送）
                # _execute_tool_streaming 是生成器，yield 分发事件，return 观察结果
                observation = yield from self._execute_tool_streaming(
                    parsed.action, parsed.action_input
                )

                yield {"type": "trace", "step": {
                    "type": "observation",
                    "text": observation[:200] + ("..." if len(observation) > 200 else ""),
                }}

                # 追加到草稿本
                scratchpad += (
                    f"Thought: {parsed.thought}\n"
                    f"Action: {parsed.action}\n"
                    f"Action Input: {parsed.action_input}\n"
                    f"Observation: {observation}\n\n"
                )
            else:
                # 情况 3：无法解析 → 当作最终回答，直接流式发送
                answer = response.strip()
                yield {"type": "answer_chunk", "text": answer}
                return answer

        # 超过最大循环次数
        timeout_msg = "抱歉，我已经尝试了多次但仍未能完全回答您的问题，请尝试换一种方式提问。"
        yield {"type": "answer_chunk", "text": timeout_msg}
        return timeout_msg

    def _direct_chat_streaming(self, user_input):
        """
        纯对话模式的流式版本（无工具，直接流式调用 LLM）。

        这是真正的逐字流式 —— LLM 每生成一个 token 就立即 yield。
        """
        messages = [
            {"role": "system", "content": DIRECT_CHAT_SYSTEM},
        ]
        # 注入声明性记忆
        dm_context = self.declarative_memory.get_context()
        if dm_context:
            messages.append({
                "role": "system",
                "content": DECLARATIVE_MEMORY_INJECTION.format(
                    memory_content=dm_context
                ),
            })
        # 加入工作记忆中的历史对话
        messages.extend(self.memory.get_chat_messages())
        # 加入当前用户输入
        messages.append({"role": "user", "content": user_input})

        full_answer = ""
        try:
            for chunk in self.llm.chat_stream(messages, temperature=TEMPERATURE):
                full_answer += chunk
                yield {"type": "answer_chunk", "text": chunk}
        except Exception as e:
            error_msg = f"LLM 调用失败: {e}"
            yield {"type": "answer_chunk", "text": error_msg}
            return error_msg

        return full_answer

    def _build_user_message(self, memory_context, user_input, scratchpad):
        """构建 ReAct 用户消息：记忆上下文 + 当前问题 + 草稿本"""
        parts = []
        if memory_context:
            parts.append(memory_context)
        parts.append(f"当前问题: {user_input}")
        if scratchpad:
            parts.append(scratchpad)
        return "\n\n".join(parts)

    # ==================== 纯对话模式（无工具）====================

    def _direct_chat(self, user_input):
        """无工具可用时，直接调用 DeepSeek 对话"""
        messages = [
            {"role": "system", "content": DIRECT_CHAT_SYSTEM},
        ]
        # 注入声明性记忆（用户偏好档案，让 Agent 回答时参考用户习惯）
        dm_context = self.declarative_memory.get_context()
        if dm_context:
            messages.append({
                "role": "system",
                "content": DECLARATIVE_MEMORY_INJECTION.format(
                    memory_content=dm_context
                ),
            })
        # 加入工作记忆中的历史对话
        messages.extend(self.memory.get_chat_messages())
        # 加入当前用户输入
        messages.append({"role": "user", "content": user_input})

        try:
            response = self.llm.chat(messages, temperature=TEMPERATURE)
        except Exception as e:
            return f"LLM 调用失败: {e}"
        return response

    # ==================== 工具执行 ====================

    @staticmethod
    def _clean_tool_name(action):
        """
        清理 LLM 输出的工具名称中的 markdown 格式字符和多余空白。

        LLM 有时会在工具名周围添加 markdown 格式，例如：
          - **stock_analysis**  (加粗)
          - `stock_analysis`    (行内代码)
          - _stock_analysis_    (斜体)
          - [stock_analysis]    (链接文本)
          - stock_analysis |    (管道符后跟参数说明)

        这些格式字符会导致工具名与注册表中的键不匹配，
        因此在查找工具前需要清理。

        参数
        ----
        action : str  原始工具名称（可能含 markdown 格式字符）

        返回
        ----
        str : 清理后的工具名称
        """
        action = action.strip()
        # 去除首尾的 markdown 格式字符（可能嵌套，循环去除）
        # 包括：* ` _ ~ [ ] ( ) | 及空白
        changed = True
        while changed:
            changed = False
            stripped = action.strip(' \t\r\n`*_~[]()|')
            if stripped != action:
                action = stripped
                changed = True
        return action

    def _execute_tool(self, action, action_input):
        """
        执行工具调用。

        参数
        ----
        action       : str  工具名称
        action_input : str  JSON 格式的工具输入
        """
        # 清理工具名（去除 LLM 可能添加的 markdown 格式字符）
        action = self._clean_tool_name(action)

        tool = self.tools.get(action)
        if not tool:
            # 精确匹配失败 → 尝试模糊匹配（编辑距离相近的工具名）
            available = list(self.tools._tools.keys())
            close = get_close_matches(action, available, n=1, cutoff=0.6)
            if close:
                tool = self.tools.get(close[0])
                action = close[0]  # 使用匹配到的正确工具名
            else:
                return f"错误：未找到工具 '{action}'。可用工具：{available}"

        # 解析 JSON 参数
        try:
            params = json.loads(action_input)
        except json.JSONDecodeError:
            return f"错误：Action Input 不是合法 JSON：{action_input}"

        # 执行工具
        try:
            return tool.run(**params)
        except Exception as e:
            return f"工具执行出错：{e}"

    def _execute_tool_streaming(self, action, action_input):
        """
        流式工具执行（生成器）。

        对于支持事件回调的工具（如 StockBatchQueryTool），
        在工具执行期间实时 yield 分发事件，实现 SubAgent 分发过程的可视化。

        对于普通工具，直接同步执行，不 yield 任何事件。

        这是一个生成器方法，通过 yield from 调用：
          observation = yield from self._execute_tool_streaming(action, action_input)

        参数
        ----
        action       : str  工具名称
        action_input : str  JSON 格式的工具输入

        生成
        ----
        dict : 分发事件 {"type": "dispatch", "data": {...}}

        返回（通过 StopIteration.value）
        ----
        str : 工具执行结果（observation 文本）
        """
        # 清理工具名
        action = self._clean_tool_name(action)

        tool = self.tools.get(action)
        if not tool:
            # 模糊匹配
            available = list(self.tools._tools.keys())
            close = get_close_matches(action, available, n=1, cutoff=0.6)
            if close:
                tool = self.tools.get(close[0])
                action = close[0]
            else:
                return f"错误：未找到工具 '{action}'。可用工具：{available}"

        # 解析 JSON 参数
        try:
            params = json.loads(action_input)
        except json.JSONDecodeError:
            return f"错误：Action Input 不是合法 JSON：{action_input}"

        # 检查工具是否支持事件回调（批量查询工具）
        if hasattr(tool, 'set_event_callback'):
            # ---- 支持事件回调的工具：后台执行 + 实时推送事件 ----

            # 创建线程安全队列，用于接收分发事件
            event_queue = queue.Queue()

            # 设置回调：DispatchManager 的每个事件都放入队列
            tool.set_event_callback(lambda event: event_queue.put(event))

            # 在后台线程中执行工具（工具内部使用 ThreadPoolExecutor 并行查询）
            result_holder = {}

            def _run_tool_bg():
                """后台线程函数：执行工具并将结果存入 result_holder"""
                try:
                    result_holder['result'] = tool.run(**params)
                except Exception as e:
                    result_holder['error'] = str(e)
                finally:
                    # 放入 None 作为结束信号
                    event_queue.put(None)

            bg_thread = threading.Thread(target=_run_tool_bg, daemon=True)
            bg_thread.start()

            # 主线程：从队列读取事件并 yield（实时推送到前端）
            while True:
                # queue.get() 会阻塞，直到有事件可用
                # 这里的阻塞是期望的：等待后台线程产生事件
                event = event_queue.get()
                if event is None:
                    # None 是结束信号，工具执行完成
                    break
                # yield 分发事件给流式生成器
                yield {"type": "dispatch", "data": event}

            # 等待后台线程完全结束（通常已经结束）
            bg_thread.join(timeout=1.0)

            # 返回工具执行结果
            if 'error' in result_holder:
                return f"工具执行出错：{result_holder['error']}"
            else:
                return result_holder.get('result', '工具未返回结果')

        else:
            # ---- 普通工具：直接同步执行 ----
            try:
                return tool.run(**params)
            except Exception as e:
                return f"工具执行出错：{e}"

    # ==================== 输出解析 ====================

    def _parse_response(self, text):
        """
        解析 LLM 的 ReAct 输出。

        可能的输出：
          1. "Thought: ...\nAction: tool\nAction Input: {...}"
          2. "Thought: ...\nFinal Answer: ..."
          3. 其他（当作最终回答）
        """
        text = text.strip()

        # 1. 检查是否包含 Final Answer
        if "Final Answer:" in text:
            idx = text.index("Final Answer:")
            thought = text[:idx].replace("Thought:", "").strip()
            final = text[idx + len("Final Answer:"):].strip()
            return ParsedResponse(thought=thought, final_answer=final)

        # 2. 检查是否包含 Action + Action Input
        # 支持 markdown 格式的标签（如 **Action:** 或 `Action:`）
        action_re = re.search(r"[\*`]{0,2}Action:?\s*[\*`]{0,2}\s*(.+)", text)
        # Action Input 可能跨行（JSON），匹配到下一个关键字或文本末尾
        input_re = re.search(
            r"[\*`]{0,2}Action\s*Input:?\s*[\*`]{0,2}\s*(.*?)(?=\n(?:\*{0,2}Thought|\*{0,2}Action|\*{0,2}Final Answer|\*{0,2}Observation):|\Z)",
            text,
            re.DOTALL,
        )

        if action_re:
            action = action_re.group(1).strip()
            # 清理 LLM 可能添加的 markdown 格式字符（** ` _ | 等）
            action = self._clean_tool_name(action)
            action_input = input_re.group(1).strip() if input_re else "{}"

            # 提取 Thought：使用 [ \t]* 代替 \s*，避免吞掉换行符
            # 原问题：\s* 会匹配 \n，导致 (?=\nAction:) 前瞻失败
            # 同时支持 markdown 格式标签（如 **Thought:**）
            thought_re = re.search(
                r"[\*`]{0,2}Thought:?\s*[\*`]{0,2}[ \t]*(.*?)(?=\n[\*`]{0,2}Action:)",
                text,
                re.DOTALL,
            )
            thought = thought_re.group(1).strip() if thought_re else ""

            # 如果 Thought 为空，补充占位提示（LLM 有时会跳过推理直接输出 Action）
            if not thought:
                thought = "（模型直接选择工具执行，未输出显式推理）"

            return ParsedResponse(thought=thought, action=action, action_input=action_input)

        # 3. 无法解析 → 整段当作最终回答
        return ParsedResponse(final_answer=text)

    # ==================== 工作记忆摘要 ====================

    def _summarize(self, old_summary, new_text):
        """使用 DeepSeek 生成对话摘要（供工作记忆压缩时调用）"""
        prompt = SUMMARIZE_PROMPT.format(
            old_summary=old_summary or "（无）",
            new_text=new_text,
        )
        # 用低温度生成摘要，保证稳定性
        return self.llm.chat(
            [
                {"role": "system", "content": "你是一个对话摘要助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
