# -*- coding: utf-8 -*-
"""
批量股票查询工具（StockBatchQueryTool）
======================================
继承 BaseTool，作为主 Agent 调用的入口工具。

当用户同时询问多只股票时，主 Agent 通过 ReAct 循环调用此工具。
工具内部自动将多只股票拆分为子任务，通过 DispatchManager 并行分发给
多个 SubAgent 执行，最后聚合结果返回。

架构关系：
  主 Agent (ReactAgent)
    -> ReAct 决策：检测到多只股票 -> 调用 stock_batch_analysis
    -> StockBatchQueryTool.run()
      -> DispatchManager.dispatch()
        -> SubAgent 1 (贵州茅台) || SubAgent 2 (五粮液) || SubAgent 3 (中国平安)
        -> 并行执行（ThreadPoolExecutor）
      -> 聚合结果
    -> 返回 Observation 给主 Agent

输入格式（LLM 调用时）：
  {"stocks": ["贵州茅台", "五粮液", "中国平安"], "analysis_type": "financial"}
  {"stocks": ["茅台", "五粮液"], "analysis_type": "quote", "period": "daily"}
"""

from tools.base import BaseTool
from tools.stock_analysis import StockAnalysisTool
from tools.stock_quote_tool import StockQuoteTool
from core.dispatcher import DispatchManager


class StockBatchQueryTool(BaseTool):
    """
    批量股票查询工具。

    当用户需要同时查询 2 只及以上股票时使用此工具。
    工具内部通过 DispatchManager 并行分发，多只股票同时查询，
    耗时从 N*xT（串行）降至约 1*xT（并行）。

    属性
    ----
    name        : "stock_batch_analysis"  工具名称（Agent 调用时使用）
    description : str                     工具描述（注入 ReAct 提示词，告诉 LLM 何时使用）
    """

    # 工具名称：Agent 在 Action 中用此名称调用
    name = "stock_batch_analysis"

    # 工具描述：告诉 LLM 这个工具的用途和输入格式
    description = (
        "批量查询多只股票信息并并行分析。当用户同时询问2只及以上股票时使用此工具。"
        "输入 stocks（股票名称或代码的列表）和 analysis_type（financial=财务分析/quote=行情查询）。"
        "行情查询可附带 period（时间粒度，如 daily/weekly/monthly）。"
    )

    def __init__(self, max_workers=3, mode="direct", verbose=False):
        """
        初始化批量查询工具。

        参数
        ----
        max_workers : int   最大并发线程数（默认 3）
                            控制 SubAgent 的并行度，建议不超过 5
        mode        : str   SubAgent 工作模式："direct"（默认）或 "react"（预留）
        verbose     : bool  是否输出分发日志
        """
        # 工具类引用（不是实例！）
        # 传给 DispatchManager -> SubAgent，每个 SubAgent 创建自己的实例
        # 这样多线程下不会共享 requests.Session 等状态
        self._tool_classes = {
            "stock_analysis": StockAnalysisTool,
            "stock_quote": StockQuoteTool,
        }
        self._max_workers = max_workers
        self._mode = mode
        self._verbose = verbose
        # 事件回调（由 Agent 流式推理设置，用于实时推送分发事件到前端）
        self._event_callback = None

    def set_event_callback(self, callback):
        """
        设置分发事件回调函数。

        由 ReactAgent._react_loop_streaming() 在执行工具前调用，
        将一个线程安全的队列写入函数传入。DispatchManager 在 SubAgent
        开始/完成时会调用此回调，事件通过队列传递给流式生成器，
        最终以 SSE 事件推送到前端，实现分发过程的实时可视化。

        参数
        ----
        callback : callable  事件回调函数，签名：callback(event_dict)
        """
        self._event_callback = callback

    def run(self, stocks, analysis_type="financial", **kwargs):
        """
        执行批量股票查询。

        参数
        ----
        stocks        : list 或 str  股票名称或代码的列表
                                     如 ["贵州茅台", "五粮液", "中国平安"]
                                     也接受逗号分隔的字符串 "贵州茅台,五粮液"
        analysis_type : str          分析类型：
                                     "financial" = 财务分析（营收/利润/ROE 等）
                                     "quote" = 行情查询（K线/涨跌/成交量等）
        **kwargs      :              传递给每个子任务的额外参数：
                                     - period: 时间粒度（quote 模式用）
                                     - start_year / end_year: 年份区间（financial 模式用）
                                     - beg / end: 日期范围（quote 模式用）
                                     - limit: 返回条数上限（quote 模式用）

        返回
        ----
        str : 聚合后的分析报告文本
        """
        # ---- 参数校验与规范化 ----

        # 如果 stocks 是字符串，尝试拆分为列表
        # LLM 有时会传 "贵州茅台,五粮液" 而非 ["贵州茅台", "五粮液"]
        if isinstance(stocks, str):
            stocks = [s.strip() for s in stocks.split(",") if s.strip()]

        # 空列表检查
        if not stocks:
            return "错误：股票列表为空，请至少提供一只股票名称"

        # 单只股票提示（不报错，但建议用单只工具更高效）
        if len(stocks) == 1:
            return ("提示：仅查询 1 只股票时，建议直接使用 stock_analysis 或 "
                    "stock_quote 工具，效率更高。\n"
                    f"当前查询：{stocks[0]}")

        # ---- 构建子任务列表 ----
        # 每只股票对应一个子任务字典
        tasks = []
        for stock in stocks:
            task = {
                "stock": stock,
                "analysis_type": analysis_type,
            }
            # 将额外的参数（period, start_year 等）传递到每个子任务
            for k, v in kwargs.items():
                if v is not None:
                    task[k] = v
            tasks.append(task)

        # ---- 创建分发管理器并执行 ----
        dispatcher = DispatchManager(
            tool_classes=self._tool_classes,
            max_workers=self._max_workers,
            mode=self._mode,
            verbose=self._verbose,
            event_callback=self._event_callback,
        )

        return dispatcher.dispatch(tasks)
