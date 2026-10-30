# -*- coding: utf-8 -*-
"""
工作记忆（Working Memory）
==========================
管理多轮对话的上下文，核心机制：滑动窗口 + 自动摘要压缩。

设计思路（借鉴认知科学的工作记忆模型）：
  - 容量有限：只保留最近 N 条消息的完整内容（滑动窗口）
  - 不会遗忘：超出窗口的旧消息被压缩为摘要，保留关键信息
  - 上下文注入：每次构建 ReAct 提示词时，将"摘要 + 近期对话"注入

与 ReAct 的关系：
  - 工作记忆存储的是"稳定的对话历史"（用户问了什么、助手答了什么）
  - ReAct 循环中的 Thought/Action/Observation 是"瞬态推理链"，
    由 Agent 在单轮内维护，不写入工作记忆
  - 一轮对话结束后，只有最终回答写入工作记忆
"""
import time
from collections import deque


class MemoryItem:
    """单条记忆项：一条用户消息或助手回答"""

    def __init__(self, role, content):
        """
        参数
        ----
        role    : "user" 或 "assistant"
        content : 消息文本
        """
        self.role = role
        self.content = content
        self.timestamp = time.time()


class WorkingMemory:
    """
    工作记忆：滑动窗口 + 自动摘要。

    参数
    ----
    window_size : int
        滑动窗口大小，保留最近 N 条消息的完整内容
    summarizer  : callable(old_summary, old_text) -> new_summary
        摘要函数（通常用 DeepSeek 生成摘要）。
        若为 None，则旧消息以截断文本形式保留（不调用 LLM）。
    """

    def __init__(self, window_size=8, summarizer=None):
        self.window_size = window_size
        self.summarizer = summarizer
        self.items = deque()     # 近期消息队列（完整保留）
        self.summary = ""        # 旧消息的压缩摘要

    # ==================== 写入 ====================

    def add_user(self, content):
        """记录一条用户消息"""
        self.items.append(MemoryItem("user", content))
        self._try_compress()

    def add_assistant(self, content):
        """记录一条助手回答"""
        self.items.append(MemoryItem("assistant", content))
        self._try_compress()

    # ==================== 压缩 ====================

    def _try_compress(self):
        """当消息数超过窗口时，将最旧的消息压缩为摘要"""
        while len(self.items) > self.window_size:
            # 取出最旧的一条
            old = self.items.popleft()
            old_line = f"[{old.role}] {old.content}"

            if self.summarizer:
                # 使用 LLM 生成/更新摘要
                try:
                    self.summary = self.summarizer(self.summary, old_line)
                except Exception:
                    # 摘要失败时降级：直接拼接文本
                    self.summary = (self.summary + "\n" + old_line).strip()
            else:
                # 无摘要器：直接拼接（简单截断防过长）
                self.summary = (self.summary + "\n" + old_line).strip()
                if len(self.summary) > 2000:
                    self.summary = self.summary[-2000:]

    # ==================== 读取 ====================

    def get_context(self):
        """
        获取格式化的上下文文本，供 ReAct 提示词使用。

        返回格式：
          【对话历史摘要】
          ...
          【近期对话】
          User: ...
          Assistant: ...
        """
        parts = []

        if self.summary:
            parts.append(f"【对话历史摘要】\n{self.summary}")

        if self.items:
            lines = []
            for item in self.items:
                if item.role == "user":
                    lines.append(f"User: {item.content}")
                else:
                    lines.append(f"Assistant: {item.content}")
            parts.append("【近期对话】\n" + "\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def get_chat_messages(self):
        """获取 OpenAI 格式的消息列表（用于纯对话调用）"""
        messages = []
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"之前的对话摘要:\n{self.summary}",
            })
        for item in self.items:
            messages.append({"role": item.role, "content": item.content})
        return messages

    def clear(self):
        """清空工作记忆"""
        self.items.clear()
        self.summary = ""
