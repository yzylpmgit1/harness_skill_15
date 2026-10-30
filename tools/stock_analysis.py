# -*- coding: utf-8 -*-
"""
股票走势分析工具
================
根据用户输入的股票名称或代码，检索该股近 3 年的财务数据，
通过量化分析提取该股独有的趋势规律，生成数据驱动的个性化建议。

数据来源：iFinD 同花顺金融数据（已缓存到 data/stock_metrics.json）
分析维度：
  1. 成长性分析 —— 营收/利润的增速趋势（加速 or 减速）
  2. 盈利能力分析 —— 毛利率/净利率/ROE 的变化方向
  3. 财务安全分析 —— 资产负债率水平和变化
  4. 股价表现分析 —— 年度涨跌幅、波动率（如有）
  5. 综合诊断 —— 基于以上分析给出该股独有的特征标签和操作建议

设计理念 —— "不要千篇一律"：
  - 每只股票的指标阈值不同（如白酒毛利率 90%+ vs 电池 20%+）
  - 趋势方向比绝对数值更重要（ROE 从 30%→36% vs 从 12%→10%）
  - 建议必须引用具体数据，禁止套话
"""
import os
import json

from tools.base import BaseTool
from tools.ifind_adapter import IFindAdapter
from tools.em_data_fetcher import EMDataFetcher
from config import STOCK_METRICS_PATH, STOCK_CACHE_DIR


class StockAnalysisTool(BaseTool):
    """股票走势分析工具：检索财务数据 → 量化分析 → 个性化建议"""

    name = "stock_analysis"
    description = (
        '分析指定股票的财务走势并给出个性化建议。'
        '输入 JSON: {"stock": "股票名称或代码（如 贵州茅台、600519、铜陵有色）"}'
        '可选参数: {"start_year": 起始年份, "end_year": 结束年份}（如 2020-2022）'
        '不指定时间时默认取最近3年；指定时间区间时实时获取对应数据'
        '支持任意 A 股股票：本地缓存未命中时自动从东方财富获取真实数据'
    )

    def __init__(self):
        """构造时不做 IO，首次调用时才加载数据（懒加载）"""
        self._stocks = None    # 股票数据列表（静态缓存）
        self._ready = False    # 静态缓存是否已加载
        self._adapter = IFindAdapter()    # iFinD 数据适配器实例
        self._fetcher = EMDataFetcher()   # 东方财富数据获取器实例

    def _ensure_ready(self):
        """确保数据已加载（懒加载模式）"""
        if self._ready:
            return
        with open(STOCK_METRICS_PATH, "r", encoding="utf-8") as f:
            self._stocks = json.load(f)
        self._ready = True

    def run(self, stock: str, realtime_data: str = None, start_year: int = None, end_year: int = None):
        """
        分析指定股票的财务走势并给出建议。

        支持两种数据来源 + 两种时间范围：

        数据来源：
          1. 本地缓存模式（默认）：从 stock_metrics.json 查找已缓存的股票
          2. 实时数据模式：agent 通过 iFinD 获取数据后传入 realtime_data 参数
          3. 东方财富自动获取：本地未命中时自动调用东方财富 API

        时间范围：
          - 默认（不传 start_year/end_year）：自动取最近 3 个已披露年报
          - 自定义区间（传入 start_year + end_year）：实时从东方财富获取指定年份的数据
            ⚠ 自定义区间时跳过本地缓存，强制实时获取

        参数
        ----
        stock : str  股票名称（如"贵州茅台"）或代码（如"600519"）

        realtime_data : str, 可选
            iFinD 实时数据的 JSON 字符串。当传入此参数时，优先使用实时数据。

        start_year : int, 可选
            自定义起始年份（如 2020）。需与 end_year 同时使用。

        end_year : int, 可选
            自定义结束年份（如 2022）。需与 start_year 同时使用。

        返回
        ----
        str : 结构化的分析报告，包含数据、趋势诊断和个性化建议
        """
        self._ensure_ready()

        # 判断是否为自定义时间区间模式
        custom_range = start_year is not None and end_year is not None

        # ---- 数据获取（多级降级策略）----
        if realtime_data:
            # 模式 1：agent 传入 iFinD 实时数据
            stock_data = self._build_from_realtime(realtime_data)
            if stock_data:
                self._adapter.save_to_cache(stock_data, STOCK_CACHE_DIR)
            else:
                return "实时数据解析失败，请检查 iFinD 返回的数据格式是否正确。"
        elif custom_range:
            # 模式 2：用户指定了时间区间 → 跳过缓存，直接从东方财富获取
            stock_data = self._fetch_from_em(stock, start_year=start_year, end_year=end_year)
            if not stock_data:
                return (
                    f"未找到股票或获取数据失败: {stock}\n"
                    f"请求时间区间: {start_year}-{end_year}年\n"
                    f"请检查股票名称/代码是否正确，以及该区间年报是否已披露。"
                )
            # 自定义区间结果不缓存（避免与默认3年缓存混淆）
        else:
            # 模式 3：默认模式 —— 先查本地缓存
            stock_data = self._find_stock(stock)

            if not stock_data:
                # 本地未命中，自动从东方财富获取最近3年
                stock_data = self._fetch_from_em(stock)
                if stock_data:
                    self._adapter.save_to_cache(stock_data, STOCK_CACHE_DIR)
                else:
                    available = [f"{s['name']}({s['code']})" for s in self._stocks]
                    return (
                        f"未找到股票: {stock}\n"
                        f"本地缓存和东方财富接口均未获取到数据。\n"
                        f"当前本地支持的股票: {', '.join(available)}\n"
                        f"请检查股票名称或代码是否正确。"
                    )

        # ---- 第 2 步：逐年提取关键指标 ----
        years = stock_data["years"]
        report_parts = []
        report_parts.append(self._format_header(stock_data, custom_range))

        # ---- 第 3 步：分维度量化分析 ----
        growth_analysis = self._analyze_growth(years)
        profitability = self._analyze_profitability(years)
        safety = self._analyze_safety(years)
        price_analysis = self._analyze_price(stock_data)

        report_parts.append(growth_analysis["text"])
        report_parts.append(profitability["text"])
        report_parts.append(safety["text"])
        if price_analysis:
            report_parts.append(price_analysis)

        # ---- 第 4 步：综合诊断与个性化建议 ----
        diagnosis = self._generate_diagnosis(
            stock_data, growth_analysis, profitability, safety
        )
        report_parts.append(diagnosis)

        return "\n\n".join(report_parts)

    # ==================== 股票查找 ====================

    def _find_stock(self, query):
        """
        根据名称或代码查找股票数据。
        支持模糊匹配：输入"茅台"也能匹配到"贵州茅台"。

        查找顺序：
          1. 实时缓存目录（data/stock_cache/）—— 东方财富/iFinD 获取过的股票
          2. 静态缓存（stock_metrics.json）—— 手工整理的 5 只股票

        ⚠ 缓存时效性：实时缓存会检查最新年报年份是否过期，
           过期则不返回缓存，触发自动重新获取最新数据。
        """
        self._ensure_ready()  # 确保静态缓存已加载
        query = query.strip()

        # 计算当前应该能查到的最新年报年份（用于缓存时效性检查）
        # 复用 EMDataFetcher 的日期计算逻辑，保持一致性
        dates_str = EMDataFetcher._calc_recent_3y_dates()  # 如 "2025-12-31,2024-12-31,2023-12-31"
        expected_latest_year = int(dates_str.split(",")[0][:4])  # 如 2025

        # ---- 第 1 步：查找实时缓存目录 ----
        if os.path.exists(STOCK_CACHE_DIR):
            for filename in os.listdir(STOCK_CACHE_DIR):
                if not filename.endswith(".json"):
                    continue
                cache_path = os.path.join(STOCK_CACHE_DIR, filename)
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                # 精确匹配或模糊匹配
                if (cached["code"] == query or cached["name"] == query
                        or query in cached["name"] or cached["name"] in query
                        or query in cached["code"]):
                    # ⚠ 缓存时效性检查：缓存数据的最新年份必须 >= 应有最新年份
                    # 否则视为过期（如缓存是 2021-2023，但当前应有 2023-2025），不返回
                    cached_years = [int(y["year"]) for y in cached.get("years", [])]
                    if cached_years and max(cached_years) >= expected_latest_year:
                        return cached  # 缓存有效，直接返回
                    # 缓存过期，跳出循环走降级逻辑（东方财富重新获取）
                    break

        # ---- 第 2 步：查找静态缓存 ----
        for stock in self._stocks:
            # 精确匹配代码
            if stock["code"] == query:
                return stock
            # 精确匹配名称
            if stock["name"] == query:
                return stock
            # 模糊匹配：查询词是名称的子串，或名称是查询词的子串
            if query in stock["name"] or stock["name"] in query:
                return stock
            # 模糊匹配代码
            if query in stock["code"]:
                return stock
        return None

    def _build_from_realtime(self, realtime_data_json):
        """
        从 agent 传入的 iFinD 实时数据构建股票数据结构。

        参数
        ----
        realtime_data_json : str  JSON 字符串，包含 iFinD 返回的多年财务数据

        格式示例：
            {
                "name": "腾讯控股",
                "code": "00700",
                "market": "HK",
                "year_2023": "<iFinD表格文本>",
                "year_2022": "<iFinD表格文本>",
                "year_2021": "<iFinD表格文本>",
                "info": "<iFinD基本信息表格文本>"  # 可选
            }

        返回
        ----
        dict or None : 完整的股票数据结构，解析失败返回 None
        """
        try:
            data = json.loads(realtime_data_json)
        except json.JSONDecodeError:
            return None

        name = data.get("name", "未知")
        code = data.get("code", "")
        market = data.get("market", "")

        # ---- 解析各年份的财务数据 ----
        year_results = []
        for key in sorted(data.keys()):
            if not key.startswith("year_"):
                continue
            year_str = key.replace("year_", "")  # 如 "2023"
            table_text = data[key]
            # 用适配器解析 iFinD 表格
            parsed = self._adapter.parse_ifind_response(table_text)
            if not parsed:
                # 可能直接是 Markdown 表格，尝试直接解析
                parsed = self._adapter.parse_table(table_text)
            if parsed:
                year_data = self._adapter.build_year_data(parsed, year_str)
                year_results.append(year_data)

        if not year_results:
            return None  # 没有解析到任何年份数据

        # ---- 解析基本信息（可选）----
        info_result = None
        info_text = data.get("info")
        if info_text:
            info_result = self._adapter.parse_ifind_response(info_text)
            if not info_result:
                info_result = self._adapter.parse_table(info_text)

        # ---- 组装完整数据结构 ----
        stock_data = self._adapter.build_stock_data(
            name=name,
            code=code,
            market=market,
            year_results=year_results,
            info_result=info_result,
        )
        return stock_data

    def _fetch_from_em(self, query, start_year=None, end_year=None):
        """
        从东方财富公开 API 获取股票数据（自动获取模式）。

        当本地缓存未命中时，自动调用东方财富接口获取该股票的财务数据。
        无需 API Key，支持任意 A 股股票。

        参数
        ----
        query : str  股票名称或代码

        start_year : int or None
            自定义起始年份。为 None 时自动取最近 3 年。

        end_year : int or None
            自定义结束年份。为 None 时自动取最近 3 年。

        返回
        ----
        dict or None : 股票数据结构，获取失败返回 None
        """
        try:
            return self._fetcher.fetch_stock(
                query, start_year=start_year, end_year=end_year
            )
        except Exception:
            return None

    # ==================== 报告格式化 ====================

    def _format_header(self, stock_data, custom_range=False):
        """格式化报告头部信息"""
        # 根据实际年份数量和是否自定义区间生成标题
        years = stock_data["years"]
        year_range = f"{years[0]['year']}-{years[-1]['year']}"
        if custom_range:
            # 用户指定了时间区间 → 显示具体年份范围
            period_label = f"{year_range}（共{len(years)}年）"
        elif len(years) == 3:
            period_label = "近3年"
        else:
            period_label = f"{year_range}（共{len(years)}年）"

        lines = [
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  {stock_data['name']}（{stock_data['code']}.{stock_data['market']}）",
            f"  行业: {stock_data['industry']}",
            f"  简介: {stock_data['description']}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"【{period_label}核心财务数据】",
        ]

        # 表格化展示逐年数据
        # ⚠ 表头年份必须从数据中动态提取，不能硬编码！
        #    否则数据是 2023-2025 年但表头显示 2021-2023 年，会造成严重误导
        year_labels = [f"{y['year']}年" for y in years]
        header = f"  {'指标':<12} " + "  ".join(lbl.rjust(12) for lbl in year_labels)
        lines.append(header)
        # 分隔线宽度根据表头列数自适应
        lines.append("  " + "-" * (16 + 14 * len(years)))

        # 营业收入
        rev_row = self._format_metric_row("营收(亿)", [y["revenue_yi"] for y in years])
        lines.append(rev_row)

        # 归母净利润
        profit_row = self._format_metric_row("净利(亿)", [y["net_profit_yi"] for y in years])
        lines.append(profit_row)

        # 毛利率
        gm_row = self._format_metric_row("毛利率(%)", [y["gross_margin"] for y in years])
        lines.append(gm_row)

        # 净利率
        nm_row = self._format_metric_row("净利率(%)", [y["net_margin"] for y in years])
        lines.append(nm_row)

        # ROE
        roe_row = self._format_metric_row("ROE(%)", [y["roe"] for y in years])
        lines.append(roe_row)

        # 资产负债率
        dr_row = self._format_metric_row("负债率(%)", [y["debt_ratio"] for y in years])
        lines.append(dr_row)

        # 营收增速
        ryoy_row = self._format_metric_row("营收增速(%)", [y["revenue_yoy"] for y in years])
        lines.append(ryoy_row)

        # 利润增速
        pyoy_row = self._format_metric_row("利润增速(%)", [y["profit_yoy"] for y in years])
        lines.append(pyoy_row)

        return "\n".join(lines)

    @staticmethod
    def _format_metric_row(label, values):
        """格式化一行指标数据，None 显示为 N/A"""
        cells = []
        for v in values:
            if v is None:
                cells.append("N/A".rjust(12))
            elif isinstance(v, float):
                cells.append(f"{v:.2f}".rjust(12))
            else:
                cells.append(str(v).rjust(12))
        return f"  {label:<12} {'  '.join(cells)}"

    # ==================== 维度分析 ====================

    def _analyze_growth(self, years):
        """
        成长性分析：营收和利润的增速趋势。

        核心判断逻辑：
        - 增速持续上升 → 加速增长（利好）
        - 增速持续下降 → 减速增长（警示）
        - 增速由正转负 → 拐点向下（风险）
        - 增速由负转正 → 拐点向上（机会）
        """
        rev_yoy = [y["revenue_yoy"] for y in years]
        profit_yoy = [y["profit_yoy"] for y in years]

        # 判断营收增速趋势（将通用趋势映射为成长性专用术语）
        # _judge_trend 返回 "上升"/"下降"，但在成长性语境下应表述为
        # "加速增长"/"减速增长"，因为增速本身在上升意味着加速
        GROWTH_MAP = {"上升": "加速增长", "下降": "减速增长"}
        rev_trend = GROWTH_MAP.get(self._judge_trend(rev_yoy), self._judge_trend(rev_yoy))
        profit_trend = GROWTH_MAP.get(self._judge_trend(profit_yoy), self._judge_trend(profit_yoy))

        # 计算 CAGR（复合年均增长率），年数根据实际数据跨度动态计算
        n_years = len(years) - 1  # 如 3 年数据 → 2 年 CAGR
        rev_cagr = self._calc_cagr(
            years[0]["revenue_yi"], years[-1]["revenue_yi"], n_years
        )
        profit_cagr = self._calc_cagr(
            years[0]["net_profit_yi"], years[-1]["net_profit_yi"], n_years
        )

        lines = ["【成长性分析】"]
        lines.append(f"  营收 {n_years} 年 CAGR: {rev_cagr:.1f}%  |  趋势: {rev_trend}")
        lines.append(f"  净利 {n_years} 年 CAGR: {profit_cagr:.1f}%  |  趋势: {profit_trend}")

        # 个性化判断（基于具体数据，不是套话）
        if profit_yoy[-1] < 0:
            lines.append(f"  ⚠ 最新年度利润负增长({profit_yoy[-1]:.1f}%)，需重点关注盈利拐点")
        elif rev_trend == "加速增长" and profit_trend == "加速增长":
            lines.append("  ✓ 营收利润双加速，成长动能强劲")
        elif rev_trend == "减速增长":
            lines.append(f"  ⚠ 营收增速放缓({rev_yoy[0]:.1f}%→{rev_yoy[-1]:.1f}%)，增长动力减弱")
        elif profit_trend == "减速增长" and rev_trend == "稳定":
            lines.append("  ⚠ 利润增速放缓但营收稳定，可能是成本上升侵蚀利润")

        return {"text": "\n".join(lines), "rev_trend": rev_trend, "profit_trend": profit_trend}

    def _analyze_profitability(self, years):
        """
        盈利能力分析：毛利率、净利率、ROE 的变化方向。

        核心判断逻辑：
        - ROE > 20% → 优秀盈利能力
        - ROE 15-20% → 良好
        - ROE < 10% → 偏弱
        - ROE 趋势上升 → 盈利能力改善
        - 毛利率下降 → 竞争力可能减弱
        """
        roe_vals = [y["roe"] for y in years]
        gm_vals = [y["gross_margin"] for y in years]
        nm_vals = [y["net_margin"] for y in years]

        roe_trend = self._judge_trend(roe_vals)
        gm_trend = self._judge_trend(gm_vals) if gm_vals[0] is not None else "无数据"
        nm_trend = self._judge_trend(nm_vals)

        latest_roe = roe_vals[-1]
        latest_gm = gm_vals[-1] if gm_vals[-1] is not None else None

        lines = ["【盈利能力分析】"]

        # ROE 分析
        if latest_roe > 25:
            roe_label = "优秀"
        elif latest_roe > 15:
            roe_label = "良好"
        elif latest_roe > 10:
            roe_label = "中等"
        else:
            roe_label = "偏弱"
        lines.append(f"  最新 ROE: {latest_roe:.1f}%（{roe_label}）| 趋势: {roe_trend}")

        # 毛利率分析
        if latest_gm is not None:
            if latest_gm > 80:
                gm_label = "极高（强定价权）"
            elif latest_gm > 50:
                gm_label = "较高"
            elif latest_gm > 30:
                gm_label = "中等"
            else:
                gm_label = "偏低"
            lines.append(f"  最新毛利率: {latest_gm:.1f}%（{gm_label}）| 趋势: {gm_trend}")
        else:
            lines.append("  毛利率: N/A（金融行业不适用）")

        lines.append(f"  净利率趋势: {nm_trend}（{nm_vals[0]:.1f}%→{nm_vals[-1]:.1f}%）")

        # 个性化判断
        if roe_trend == "上升" and latest_roe > 20:
            lines.append("  ✓ ROE 持续走高且处于高位，盈利护城河加深")
        elif roe_trend == "下降":
            lines.append(f"  ⚠ ROE 从 {roe_vals[0]:.1f}% 降至 {latest_roe:.1f}%，盈利能力下滑")
        if gm_vals[0] is not None and gm_trend == "下降":
            lines.append(f"  ⚠ 毛利率下降（{gm_vals[0]:.1f}%→{latest_gm:.1f}%），可能面临竞争或成本压力")

        return {
            "text": "\n".join(lines),
            "roe_trend": roe_trend,
            "latest_roe": latest_roe,
            "gm_trend": gm_trend,
        }

    def _analyze_safety(self, years):
        """
        财务安全分析：资产负债率水平和变化趋势。

        核心判断逻辑：
        - 负债率 < 30% → 低杠杆，财务安全
        - 负债率 30-60% → 中等杠杆
        - 负债率 60-80% → 较高杠杆
        - 负债率 > 80% → 高杠杆，需警惕（金融行业除外）
        """
        dr_vals = [y["debt_ratio"] for y in years]
        dr_trend = self._judge_trend(dr_vals)
        latest_dr = dr_vals[-1]

        lines = ["【财务安全分析】"]

        # 行业差异化判断
        if latest_dr > 85:
            dr_label = "高杠杆"
            lines.append(f"  最新资产负债率: {latest_dr:.1f}%（{dr_label}）| 趋势: {dr_trend}")
            lines.append("  注: 负债率超 85%，若为金融/保险行业属正常，其他行业需警惕")
        elif latest_dr > 60:
            dr_label = "较高杠杆"
            lines.append(f"  最新资产负债率: {latest_dr:.1f}%（{dr_label}）| 趋势: {dr_trend}")
            lines.append("  ⚠ 负债率偏高，关注偿债能力和现金流")
        elif latest_dr > 30:
            dr_label = "中等杠杆"
            lines.append(f"  最新资产负债率: {latest_dr:.1f}%（{dr_label}）| 趋势: {dr_trend}")
        else:
            dr_label = "低杠杆"
            lines.append(f"  最新资产负债率: {latest_dr:.1f}%（{dr_label}）| 趋势: {dr_trend}")
            lines.append("  ✓ 财务结构稳健，偿债风险低")

        if dr_trend == "上升" and latest_dr > 50:
            lines.append(f"  ⚠ 负债率持续上升（{dr_vals[0]:.1f}%→{latest_dr:.1f}%），杠杆风险增加")
        elif dr_trend == "下降":
            lines.append(f"  ✓ 负债率持续下降（{dr_vals[0]:.1f}%→{latest_dr:.1f}%），财务结构改善")

        return {"text": "\n".join(lines), "dr_trend": dr_trend, "latest_dr": latest_dr}

    def _analyze_price(self, stock_data):
        """股价表现分析（如有缓存数据）"""
        perf = stock_data.get("performance")
        if not perf:
            return None

        lines = ["【股价表现分析】"]
        vol = perf.get("annualized_volatility")
        if vol is not None:
            if vol < 15:
                vol_label = "低波动"
            elif vol < 30:
                vol_label = "中等波动"
            else:
                vol_label = "高波动"
            lines.append(f"  年化波动率: {vol:.1f}%（{vol_label}）")

        returns = perf.get("annual_returns", {})
        if returns:
            ret_strs = [f"{k}年: {v:+.1f}%" for k, v in returns.items()]
            lines.append(f"  年度涨跌幅: {' | '.join(ret_strs)}")

            # 判断股价趋势
            ret_values = list(returns.values())
            negative_years = sum(1 for r in ret_values if r < 0)
            if negative_years == len(ret_values):
                lines.append("  ⚠ 连续年度下跌，处于下行通道")
            elif negative_years > len(ret_values) / 2:
                lines.append("  ⚠ 多数年度下跌，股价表现偏弱")
            else:
                lines.append("  ✓ 多数年度正收益，股价表现稳健")

        return "\n".join(lines)

    # ==================== 综合诊断与建议 ====================

    def _generate_diagnosis(self, stock_data, growth, profitability, safety):
        """
        综合诊断：基于各维度分析结果，生成该股独有的特征标签和操作建议。

        这是"不要千篇一律"的核心 —— 每只股票的诊断完全基于其真实数据。
        """
        name = stock_data["name"]
        industry = stock_data["industry"]

        lines = [f"【综合诊断与个性化建议 —— {name}】"]

        # ---- 特征标签提取（基于真实数据）----
        tags = self._extract_tags(stock_data, growth, profitability, safety)
        lines.append(f"  特征标签: {', '.join(tags)}")
        lines.append("")

        # ---- 优势分析 ----
        strengths = self._extract_strengths(stock_data, growth, profitability, safety)
        if strengths:
            lines.append("  ▶ 核心优势:")
            for s in strengths:
                lines.append(f"    · {s}")

        # ---- 风险提示 ----
        risks = self._extract_risks(stock_data, growth, profitability, safety)
        if risks:
            lines.append("  ▶ 风险提示:")
            for r in risks:
                lines.append(f"    · {r}")

        # ---- 操作建议（数据驱动，非套话）----
        lines.append("")
        lines.append("  ▶ 操作建议:")
        advice = self._generate_advice(stock_data, growth, profitability, safety)
        for a in advice:
            lines.append(f"    · {a}")

        # ---- 关注信号 ----
        lines.append("")
        lines.append("  ▶ 后续关注信号:")
        signals = self._generate_signals(stock_data, growth, profitability, safety)
        for sig in signals:
            lines.append(f"    · {sig}")

        lines.append("")
        lines.append("  ⚠ 免责声明: 以上分析基于历史财务数据，不构成投资建议。")
        lines.append("    股市有风险，投资需谨慎。")

        return "\n".join(lines)

    def _extract_tags(self, stock_data, growth, profitability, safety):
        """从数据中提取该股独有的特征标签"""
        tags = []
        years = stock_data["years"]
        latest = years[-1]

        # 盈利能力标签
        if latest["roe"] > 30:
            tags.append("超高ROE")
        elif latest["roe"] > 20:
            tags.append("高ROE")

        if latest["gross_margin"] and latest["gross_margin"] > 80:
            tags.append("超强定价权")
        elif latest["gross_margin"] and latest["gross_margin"] < 30:
            tags.append("薄利多销")

        # 成长性标签
        if latest["revenue_yoy"] > 50:
            tags.append("高速扩张")
        elif latest["revenue_yoy"] < 0:
            tags.append("营收承压")

        if growth["profit_trend"] == "减速增长":
            tags.append("增速放缓")
        elif growth["profit_trend"] == "加速增长":
            tags.append("加速成长")

        # 安全性标签
        if latest["debt_ratio"] > 80:
            tags.append("高杠杆")
        elif latest["debt_ratio"] < 25:
            tags.append("低杠杆")

        # 行业特性标签
        tags.append(stock_data["industry"])

        return tags

    def _extract_strengths(self, stock_data, growth, profitability, safety):
        """提取该股的具体优势（必须引用数据）"""
        strengths = []
        years = stock_data["years"]
        latest = years[-1]
        first = years[0]

        if latest["roe"] > 20 and profitability["roe_trend"] in ("上升", "稳定"):
            strengths.append(
                f"ROE 达 {latest['roe']:.1f}% 且 {profitability['roe_trend']}，"
                f"远超行业平均，盈利护城河深厚"
            )

        if latest["gross_margin"] and latest["gross_margin"] > 80:
            strengths.append(
                f"毛利率 {latest['gross_margin']:.1f}%，拥有极强产品定价权"
            )

        rev_cagr = self._calc_cagr(first["revenue_yi"], latest["revenue_yi"], len(years) - 1)
        n_years = len(years) - 1
        if rev_cagr > 15:
            strengths.append(f"营收 {n_years} 年 CAGR {rev_cagr:.1f}%，增长稳健")

        if safety["latest_dr"] < 30:
            strengths.append(
                f"资产负债率仅 {safety['latest_dr']:.1f}%，财务极其稳健"
            )

        if latest["profit_yoy"] > 15:
            strengths.append(
                f"最新年度利润增长 {latest['profit_yoy']:.1f}%，盈利动能充足"
            )

        return strengths

    def _extract_risks(self, stock_data, growth, profitability, safety):
        """提取该股的具体风险（必须引用数据）"""
        risks = []
        years = stock_data["years"]
        latest = years[-1]
        first = years[0]

        if latest["profit_yoy"] < 0:
            risks.append(
                f"最新年度利润负增长 {latest['profit_yoy']:.1f}%，盈利出现拐点"
            )

        if growth["rev_trend"] == "减速增长":
            risks.append(
                f"营收增速从 {first['revenue_yoy']:.1f}% 降至 {latest['revenue_yoy']:.1f}%，"
                f"增长动力衰减"
            )

        if profitability["roe_trend"] == "下降":
            risks.append(
                f"ROE 从 {first['roe']:.1f}% 下滑至 {latest['roe']:.1f}%，"
                f"资本回报效率降低"
            )

        if profitability["gm_trend"] == "下降" and first["gross_margin"]:
            risks.append(
                f"毛利率从 {first['gross_margin']:.1f}% 降至 {latest['gross_margin']:.1f}%，"
                f"可能面临竞争加剧或成本上升"
            )

        if safety["latest_dr"] > 65 and safety["dr_trend"] == "上升":
            risks.append(
                f"资产负债率 {safety['latest_dr']:.1f}% 且持续上升，杠杆风险需关注"
            )

        # 股价风险
        perf = stock_data.get("performance", {})
        returns = perf.get("annual_returns", {})
        if returns:
            neg_count = sum(1 for v in returns.values() if v < 0)
            if neg_count >= 2:
                risks.append(
                    f"近 {len(returns)} 年中有 {neg_count} 年股价下跌，"
                    f"处于下行周期"
                )

        return risks

    def _generate_advice(self, stock_data, growth, profitability, safety):
        """
        生成数据驱动的操作建议。

        核心原则：基于该股的具体数据和趋势给出建议，绝不套用模板。
        不同股票、不同趋势 → 不同建议。
        """
        advice = []
        years = stock_data["years"]
        latest = years[-1]
        name = stock_data["name"]
        industry = stock_data["industry"]

        # ---- 评分系统：综合各维度给出大方向 ----
        score = 0  # 正分偏多，负分偏空

        # 盈利能力评分
        if latest["roe"] > 25:
            score += 2
        elif latest["roe"] > 15:
            score += 1
        elif latest["roe"] < 10:
            score -= 2

        if profitability["roe_trend"] == "上升":
            score += 1
        elif profitability["roe_trend"] == "下降":
            score -= 1

        # 成长性评分
        if growth["profit_trend"] == "加速增长":
            score += 2
        elif growth["profit_trend"] == "减速增长":
            score -= 1

        if latest["profit_yoy"] < 0:
            score -= 2

        # 安全性评分
        if safety["latest_dr"] > 70 and industry != "保险金融":
            score -= 1
        if safety["dr_trend"] == "下降":
            score += 1

        # 股价趋势评分
        perf = stock_data.get("performance", {})
        returns = perf.get("annual_returns", {})
        if returns:
            neg_count = sum(1 for v in returns.values() if v < 0)
            if neg_count >= 2:
                score -= 1

        # ---- 根据评分给出方向性建议 ----
        if score >= 3:
            advice.append(
                f"综合评分 {score} 分（偏多），{name} 基本面强劲，"
                f"适合中长期持有。建议在回调时逢低布局"
            )
        elif score >= 1:
            advice.append(
                f"综合评分 {score} 分（中性偏多），{name} 基本面尚可但存在不确定性，"
                f"建议持有观察，不宜重仓追高"
            )
        elif score >= -1:
            advice.append(
                f"综合评分 {score} 分（中性），{name} 多空因素交织，"
                f"建议观望为主，等待趋势明朗"
            )
        else:
            advice.append(
                f"综合评分 {score} 分（偏空），{name} 基本面存在隐忧，"
                f"建议谨慎对待，控制仓位"
            )

        # ---- 个性化补充建议（基于具体问题）----
        if latest["profit_yoy"] < 0:
            advice.append(
                f"利润负增长是最大隐患，建议重点跟踪下季度财报是否企稳，"
                f"若连续两季负增长应考虑减仓"
            )

        if growth["rev_trend"] == "减速增长" and industry == "白酒":
            advice.append(
                f"白酒行业增速放缓背景下，关注 {name} 能否通过提价或产品升级"
                f"维持增长，提价公告是重要信号"
            )

        if safety["latest_dr"] > 65 and industry != "保险金融":
            advice.append(
                f"负债率 {safety['latest_dr']:.1f}% 偏高，关注现金流和短债到期情况，"
                f"若融资环境收紧可能承压"
            )

        if profitability["gm_trend"] == "下降":
            advice.append(
                f"毛利率下行趋势下，关注原材料价格和竞争格局变化，"
                f"毛利率若企稳回升则是积极信号"
            )

        # 行业特定建议
        if industry == "新能源电池":
            advice.append(
                f"新能源行业技术迭代快，关注 {name} 的新技术路线进展"
                f"（如固态电池、钠离子电池），技术领先性决定长期价值"
            )
        elif industry == "安防监控":
            advice.append(
                f"安防行业向 AI 智能物联转型，关注 {name} 的 AI 业务收入占比变化，"
                f"创新业务是第二增长曲线"
            )
        elif industry == "保险金融":
            advice.append(
                f"保险行业关注新业务价值增速和内含价值变化，"
                f"寿险改革成效是 {name} 长期投资逻辑的关键"
            )

        return advice

    def _generate_signals(self, stock_data, growth, profitability, safety):
        """生成后续关注信号（帮助用户持续跟踪）"""
        signals = []
        years = stock_data["years"]
        latest = years[-1]

        # 通用信号
        signals.append("每季度财报的营收和利润增速是否延续趋势")
        signals.append("行业政策变化和竞争格局演变")

        # 个性化信号
        if profitability["roe_trend"] == "下降":
            signals.append(f"ROE 能否止跌回升（当前 {latest['roe']:.1f}%）")

        if growth["rev_trend"] == "减速增长":
            signals.append(f"营收增速能否企稳（当前 {latest['revenue_yoy']:.1f}%）")

        if safety["latest_dr"] > 60:
            signals.append(f"资产负债率变化趋势（当前 {safety['latest_dr']:.1f}%）")

        if latest["gross_margin"] is not None:
            signals.append(f"毛利率变化（当前 {latest['gross_margin']:.1f}%）")

        return signals[:4]  # 最多 4 个信号

    # ==================== 工具方法 ====================

    @staticmethod
    def _judge_trend(values):
        """
        判断数值序列的趋势方向。

        逻辑：
        - 持续上升 → "上升" / "加速增长"（如果是增速）
        - 持续下降 → "下降" / "减速增长"（如果是增速）
        - 先降后升 → "触底回升"
        - 先升后降 → "高位回落"
        - 基本持平 → "稳定"
        """
        if len(values) < 2:
            return "数据不足"

        # 过滤 None 值
        valid = [v for v in values if v is not None]
        if len(valid) < 2:
            return "数据不足"

        first, last = valid[0], valid[-1]
        diff = last - first
        avg_change = diff / (len(valid) - 1)

        # 判断是否基本持平（变化幅度 < 1）
        if abs(diff) < 1.0:
            return "稳定"

        # 判断单调性
        is_increasing = all(valid[i] <= valid[i + 1] for i in range(len(valid) - 1))
        is_decreasing = all(valid[i] >= valid[i + 1] for i in range(len(valid) - 1))

        if is_increasing:
            return "上升"
        if is_decreasing:
            return "下降"

        # 非单调：判断拐点
        if len(valid) >= 3:
            if valid[-1] > valid[-2] and valid[-2] < valid[0]:
                return "触底回升"
            if valid[-1] < valid[-2] and valid[-2] > valid[0]:
                return "高位回落"

        return "波动"

    @staticmethod
    def _calc_cagr(start, end, years):
        """计算复合年均增长率（CAGR）"""
        if start <= 0 or end <= 0 or years <= 0:
            return 0.0
        return ((end / start) ** (1.0 / years) - 1) * 100
