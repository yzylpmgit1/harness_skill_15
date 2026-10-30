# -*- coding: utf-8 -*-
"""
工具基类与注册表
================
所有工具继承 BaseTool，通过 ToolRegistry 统一管理。
Agent 在 ReAct 循环中通过注册表按名称获取工具并执行。
"""
import abc


class BaseTool(abc.ABC):
    """
    工具抽象基类。

    子类必须设置：
      - name        : 工具名称（Agent 调用时使用，需唯一）
      - description : 工具描述（告诉 LLM 该工具的用途和输入格式）

    子类必须实现：
      - run(**kwargs) : 执行工具逻辑，返回字符串结果
    """

    name: str = ""
    description: str = ""

    @abc.abstractmethod
    def run(self, **kwargs):
        """执行工具，返回字符串结果供 Agent 观察。"""
        ...

    def get_usage(self):
        """返回工具使用说明（拼入 ReAct 提示词，让 LLM 知道如何调用）。"""
        return f"- {self.name}: {self.description}"


class ToolRegistry:
    """
    工具注册表：管理所有可用工具实例。

    用法：
      registry = ToolRegistry()
      registry.register(RagSearchTool())
      registry.register(WeatherTool())
      tool = registry.get("rag_search")
    """

    def __init__(self):
        self._tools = {}  # name -> tool 实例

    def register(self, tool: BaseTool):
        """注册一个工具实例"""
        if not tool.name:
            raise ValueError("工具必须设置 name 属性")
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> BaseTool:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_by_names(self, names):
        """按名称列表批量获取工具"""
        return [self._tools[n] for n in names if n in self._tools]

    def all_tools(self):
        """返回所有已注册工具"""
        return list(self._tools.values())

    def all_usages(self):
        """返回所有工具的使用说明文本"""
        return "\n".join(t.get_usage() for t in self._tools.values())
