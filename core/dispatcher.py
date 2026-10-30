# -*- coding: utf-8 -*-
"""
任务分发管理器（DispatchManager）
================================
负责将多只股票的查询任务分发给多个 SubAgent 并行执行。

核心能力：
  - 并行分发：使用 ThreadPoolExecutor 实现真正的并行 I/O
  - 容错隔离：单个 SubAgent 失败不影响其他 SubAgent
  - 结果聚合：按原始任务顺序汇总所有结果

使用方式：
  dispatcher = DispatchManager(tool_classes={"stock_analysis": StockAnalysisTool, ...})
  result = dispatcher.dispatch([
      {"stock": "贵州茅台", "analysis_type": "financial"},
      {"stock": "五粮液", "analysis_type": "financial"},
  ])
  # result 是聚合后的文本报告

并行原理：
  假设查 1 只股票耗时 T 秒（主要是 HTTP 请求等待）：
  - 串行查 5 只：5 x T 秒
  - 并行查 5 只（max_workers=5）：约 1 x T 秒
  - 并行查 5 只（max_workers=3）：约 2 x T 秒（前 3 只同时，完成后再查剩余 2 只）

  因为股票查询是 I/O 密集型任务（大部分时间在等 HTTP 响应），
  线程池可以充分利用等待时间，实现真正的并行加速。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.sub_agent import SubAgent


class DispatchManager:
    """
    任务分发管理器。

    参数
    ----
    tool_classes  : dict       工具类字典（类引用，非实例）
                              如 {"stock_analysis": StockAnalysisTool, "stock_quote": StockQuoteTool}
    max_workers   : int        最大并发线程数（默认 3）
                              建议不超过 5，避免 API 限流
    mode          : str        SubAgent 工作模式："direct" 或 "react"
    llm_client    : object     LLM 客户端（仅 mode="react" 时需要）
    verbose       : bool       是否输出详细日志到控制台
    event_callback: callable   事件回调函数（可选）
                              每当 SubAgent 开始/完成时调用，用于实时推送事件到前端
                              回调签名：callback(event_dict)
                              event_dict 格式：
                                {"phase": "start", "agent_id": "subagent_0", "stock": "贵州茅台", "total": 3}
                                {"phase": "complete", "agent_id": "subagent_0", "stock": "贵州茅台", "status": "ok", "duration": 1.2}
                                {"phase": "all_done", "total": 3, "duration": 1.5}
    """

    def __init__(self, tool_classes, max_workers=3, mode="direct",
                 llm_client=None, verbose=False, event_callback=None):
        self.tool_classes = tool_classes    # 工具类引用
        self.max_workers = max_workers      # 最大并发数
        self.mode = mode                    # SubAgent 工作模式
        self.llm_client = llm_client        # LLM 客户端（预留）
        self.verbose = verbose              # 日志开关
        self._event_callback = event_callback  # 事件回调函数

    def _emit_event(self, event):
        """
        发射分发事件到回调函数。

        如果设置了 event_callback，调用它并将事件字典传入。
        回调函数通常会将事件放入线程安全队列，供流式生成器读取并推送到前端。

        参数
        ----
        event : dict  事件字典，包含 phase 字段和相应的上下文信息
        """
        if self._event_callback:
            try:
                self._event_callback(event)
            except Exception:
                # 回调失败不应影响分发流程
                pass

    def dispatch(self, tasks):
        """
        并行分发任务给多个 SubAgent。

        流程：
          1. 为每个任务创建一个 SubAgent
          2. 用 ThreadPoolExecutor 并行提交所有 SubAgent
          3. 等待所有 SubAgent 完成，收集结果
          4. 按原始任务顺序聚合结果

        参数
        ----
        tasks : list[dict]  任务列表
                           如 [{"stock": "贵州茅台", "analysis_type": "financial"}, ...]

        返回
        ----
        str : 聚合后的结果文本报告
        """
        # 空任务检查
        if not tasks:
            return "无任务需要执行。"

        total = len(tasks)
        start_time = datetime.now()

        # 发射 "dispatch_start" 事件
        self._emit_event({
            "phase": "dispatch_start",
            "total": total,
            "stocks": [t.get("stock", "?") for t in tasks],
            "max_workers": min(self.max_workers, total),
        })

        if self.verbose:
            print(f"\n[DispatchManager] 开始分发 {total} 个任务，"
                  f"max_workers={self.max_workers}")

        # 结果字典：agent_id -> 结果文本
        # 用字典而非列表，因为 as_completed 返回顺序不确定
        results = {}

        # 实际并发数：取 max_workers 和任务数的较小值
        # 如果只有 2 个任务，不需要开 3 个线程
        worker_count = min(self.max_workers, total)

        # 使用线程池并行执行
        # with 语句确保所有线程在退出时被正确清理
        with ThreadPoolExecutor(max_workers=worker_count) as executor:

            # 提交所有任务到线程池
            # future_to_task 映射：Future 对象 -> (agent_id, task)
            future_to_task = {}
            for i, task in enumerate(tasks):
                agent_id = f"subagent_{i}"  # 编号：subagent_0, subagent_1, ...
                stock_name = task.get("stock", "?")

                # 创建子 Agent
                sub_agent = SubAgent(
                    agent_id=agent_id,
                    task=task,
                    tool_classes=self.tool_classes,
                    mode=self.mode,
                    llm_client=self.llm_client,
                )

                # 提交到线程池，获取 Future 对象
                future = executor.submit(sub_agent.run)
                future_to_task[future] = (agent_id, task)

                # 发射 "start" 事件（每个 SubAgent 开始）
                self._emit_event({
                    "phase": "start",
                    "agent_id": agent_id,
                    "stock": stock_name,
                    "total": total,
                })

            # 等待所有任务完成，按完成顺序收集结果
            # as_completed 返回一个迭代器，哪个 Future 先完成就先返回
            for future in as_completed(future_to_task):
                agent_id, task = future_to_task[future]
                stock_name = task.get("stock", "?")
                agent_start = datetime.now()
                try:
                    # future.result() 获取 SubAgent.run() 的返回值
                    result = future.result()
                    results[agent_id] = result

                    # 判断结果是成功还是失败（SubAgent 失败时返回包含"错误"/"失败"的字符串）
                    status = "error" if ("错误" in result or "失败" in result or "异常" in result) else "ok"

                    if self.verbose:
                        print(f"  [{agent_id}] {stock_name} 完成")

                except Exception as e:
                    # 如果 SubAgent.run() 抛出了未捕获的异常（理论上不应该，
                    # 因为 _run_direct 内部有 try/except），在这里兜底
                    results[agent_id] = f"[{agent_id}] 执行异常: {str(e)}"
                    status = "error"
                    if self.verbose:
                        print(f"  [{agent_id}] 异常: {e}")

                # 发射 "complete" 事件（每个 SubAgent 完成）
                agent_elapsed = (datetime.now() - agent_start).total_seconds()
                self._emit_event({
                    "phase": "complete",
                    "agent_id": agent_id,
                    "stock": stock_name,
                    "status": status,
                    "duration": round(agent_elapsed, 2),
                    "total": total,
                })

        # 日志：总耗时
        elapsed = (datetime.now() - start_time).total_seconds()
        if self.verbose:
            print(f"[DispatchManager] 全部完成，耗时 {elapsed:.2f}s")

        # 发射 "all_done" 事件
        self._emit_event({
            "phase": "all_done",
            "total": total,
            "duration": round(elapsed, 2),
        })

        # 按原始任务顺序整理结果
        # （as_completed 返回顺序不确定，需要用 agent_id 重新排序）
        ordered_results = []
        for i, task in enumerate(tasks):
            agent_id = f"subagent_{i}"
            ordered_results.append(
                results.get(agent_id, f"[{agent_id}] 结果缺失")
            )

        # 聚合所有结果为一个文本报告
        return self._aggregate(ordered_results, tasks)

    def _aggregate(self, results, tasks):
        """
        将多个 SubAgent 的结果聚合成一个文本报告。

        参数
        ----
        results : list[str]   结果列表（按原始任务顺序）
        tasks   : list[dict]  原始任务列表

        返回
        ----
        str : 聚合后的报告文本
        """
        # 提取所有股票名称
        stocks = [t.get("stock", "?") for t in tasks]

        # 构建报告头部
        header = (f"批量查询结果（共 {len(stocks)} 只股票："
                  f"{', '.join(stocks)}）\n")

        separator = "=" * 60 + "\n"

        # 构建报告正文：每个结果之间用分隔线隔开
        body = separator + header + separator
        for i, result in enumerate(results):
            body += f"\n{result}\n"
            if i < len(results) - 1:
                body += "-" * 60 + "\n"

        return body
