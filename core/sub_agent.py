# -*- coding: utf-8 -*-
"""
子 Agent（SubAgent）
====================
轻量级 Agent，负责执行单个股票的查询任务。

设计理念：
  方案 A（默认，mode="direct"）：直接调用工具，不经过 LLM 推理
    - 零 LLM 成本，纯 I/O 并行，速度快
    - 适用于"主 Agent 已决策好查什么，SubAgent 只需执行"的场景

  方案 B（预留，mode="react"）：迷你 ReAct 循环，LLM 自主决策
    - 可自主判断使用哪个工具、如何组合参数
    - 适用于"每只股票需要独立推理"的复杂场景
    - 当前仅预留接口，未实现具体逻辑

为什么方案 A 默认不调用 LLM？
  主 Agent 的 ReAct 循环已经完成了"查什么、怎么查"的推理决策。
  SubAgent 收到的是确定性任务（如"查贵州茅台的财务数据"），
  只需直接调用对应工具即可，无需再次推理。
  这样既省成本，又避免了多并发 LLM 调用的限流风险。
"""

import traceback


class SubAgent:
    """
    轻量级子 Agent。

    每个 SubAgent 负责一只股票的查询，多个 SubAgent 可通过
    DispatchManager 并行执行。

    参数
    ----
    agent_id    : str    子 Agent 标识（如 "subagent_0"），用于日志
    task        : dict   任务描述，如 {"stock": "贵州茅台", "analysis_type": "financial"}
    tool_classes: dict   工具类字典（注意是类，不是实例），
                         如 {"stock_analysis": StockAnalysisTool, "stock_quote": StockQuoteTool}
                         每个 SubAgent 会创建自己的工具实例，避免线程安全问题
    mode        : str    工作模式："direct"（直接调用）或 "react"（迷你 ReAct，预留）
    llm_client  : object LLM 客户端（仅 mode="react" 时需要，当前未使用）
    """

    def __init__(self, agent_id, task, tool_classes, mode="direct", llm_client=None):
        self.agent_id = agent_id              # 子 Agent 编号，用于日志和结果标识
        self.task = task                      # 任务字典，包含股票名称、分析类型等
        self.tool_classes = tool_classes      # 工具类引用（不是实例）
        self.mode = mode                      # 工作模式
        self.llm_client = llm_client          # LLM 客户端（预留，方案 B 使用）

    def run(self):
        """
        执行子任务，返回结果字符串。

        返回值
        ------
        str : 分析结果文本。格式为"【股票名 · 分析类型】\\n{详细结果}"。
              如果执行出错，返回错误信息字符串（不抛异常，避免影响其他 SubAgent）。
        """
        if self.mode == "direct":
            # 方案 A：直接调用工具（默认）
            return self._run_direct()
        elif self.mode == "react":
            # 方案 B：迷你 ReAct 循环（预留接口）
            return self._run_react()
        else:
            return f"[{self.agent_id}] 错误：未知模式 '{self.mode}'"

    def _run_direct(self):
        """
        方案 A：直接调用工具执行查询。

        流程：
          1. 从任务中提取股票名称和分析类型
          2. 根据分析类型选择对应工具
          3. 创建工具实例（每个 SubAgent 独立实例，线程安全）
          4. 调用工具的 run() 方法
          5. 返回带标识的结果文本

        为什么每次都创建新的工具实例？
          StockAnalysisTool 和 StockQuoteTool 内部会创建 requests.Session 对象。
          虽然 requests.Session 通常线程安全，但为避免任何潜在问题，
          每个 SubAgent 创建独立的工具实例，从根源上消除线程安全隐患。
        """
        # 从任务中提取股票名称
        stock = self.task.get("stock", "")
        if not stock:
            return f"[{self.agent_id}] 错误：任务中缺少 stock 参数"

        # 从任务中提取分析类型（默认财务分析）
        analysis_type = self.task.get("analysis_type", "financial")

        try:
            if analysis_type == "financial":
                # ---- 财务分析路径 ----
                # 获取工具类
                tool_class = self.tool_classes.get("stock_analysis")
                if tool_class is None:
                    return f"[{self.agent_id}] 错误：未找到 stock_analysis 工具类"

                # 创建独立的工具实例（线程安全）
                tool = tool_class()

                # 构建调用参数
                kwargs = {"stock": stock}
                # 可选参数：只有任务中包含时才传入
                if "start_year" in self.task:
                    kwargs["start_year"] = self.task["start_year"]
                if "end_year" in self.task:
                    kwargs["end_year"] = self.task["end_year"]
                if "realtime_data" in self.task:
                    kwargs["realtime_data"] = self.task["realtime_data"]

                # 执行工具调用
                result = tool.run(**kwargs)
                return f"【{stock} · 财务分析】\n{result}"

            elif analysis_type == "quote":
                # ---- 行情查询路径 ----
                tool_class = self.tool_classes.get("stock_quote")
                if tool_class is None:
                    return f"[{self.agent_id}] 错误：未找到 stock_quote 工具类"

                tool = tool_class()

                # 构建调用参数
                kwargs = {"stock": stock}
                if "period" in self.task:
                    kwargs["period"] = self.task["period"]
                if "beg" in self.task:
                    kwargs["beg"] = self.task["beg"]
                if "end" in self.task:
                    kwargs["end"] = self.task["end"]
                if "limit" in self.task:
                    kwargs["limit"] = self.task["limit"]

                result = tool.run(**kwargs)
                return f"【{stock} · 行情分析】\n{result}"

            else:
                return f"[{self.agent_id}] 错误：未知分析类型 '{analysis_type}'"

        except Exception as e:
            # 捕获所有异常，返回错误信息字符串（不抛异常）
            # 这样单个 SubAgent 失败不会影响其他 SubAgent 的执行
            error_detail = traceback.format_exc()
            return f"[{self.agent_id}] {stock} 查询失败: {str(e)}\n{error_detail}"

    def _run_react(self):
        """
        方案 B（预留）：迷你 ReAct 循环。

        未来可实现的功能：
          1. 构建简化的系统提示词（只包含股票工具）
          2. 最多 2 轮 ReAct 循环（Thought -> Action -> Observation）
          3. LLM 自主决策使用哪个工具（stock_analysis 还是 stock_quote）
          4. LLM 自主构造工具参数
          5. 执行工具并返回结果

        当前未实现，调用时会抛出 NotImplementedError。
        如需启用，需要传入 llm_client 参数。

        扩展指南：
          实现时可参考 core/agent.py 中的 _react_loop() 方法，
          但需要简化为最多 2 轮迭代，且只绑定 stock_analysis 和 stock_quote 工具。
          系统提示词可使用 core/prompts.py 中的 REACT_SYSTEM_TEMPLATE，
          但需要精简 tool_descriptions 和 skill_addon 部分。
        """
        if not self.llm_client:
            return f"[{self.agent_id}] 错误：react 模式需要 llm_client 参数"

        # TODO: 实现迷你 ReAct 循环
        # 1. 构建简化系统提示词（仅包含 stock_analysis 和 stock_quote 工具）
        # 2. 将 task 转换为自然语言指令（如"分析贵州茅台的财务状况"）
        # 3. 执行最多 2 轮 ReAct 循环
        # 4. 返回最终结果
        raise NotImplementedError(
            "方案 B（react 模式）尚未实现，当前请使用 mode='direct'"
        )
