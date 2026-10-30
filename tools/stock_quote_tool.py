# -*- coding: utf-8 -*-
"""
股票行情查询分析工具
====================
根据用户输入的股票名称/代码和时间粒度，从东方财富获取 K 线行情数据，
进行走势分析和技术指标计算，生成结构化的行情报告。

与 stock_analysis（财报分析）的区别：
  - stock_analysis    : 基于【年报财务数据】分析基本面（营收、利润、ROE 等）
  - stock_quote_tool  : 基于【K线行情数据】分析走势（价格、成交量、技术指标等）

支持的时间粒度：
  - 分钟级（1min/5min/15min/30min/60min）：盘中走势
  - 日线（daily）：每日行情
  - 周线（weekly）：周度趋势
  - 月线（monthly）：月度趋势

分析维度：
  1. 行情概览 —— 区间涨跌幅、最高最低价、成交量
  2. 走势分析 —— 趋势方向、均线位置、连续涨跌
  3. 技术指标 —— MA均线、波动率、成交量变化
  4. 关键价位 —— 支撑位/压力位（近期高低点）
  5. 操作参考 —— 基于技术面的短期参考
"""
from tools.base import BaseTool
from tools.em_quote_fetcher import EMQuoteFetcher


class StockQuoteTool(BaseTool):
    """股票行情查询工具：获取 K 线数据 → 技术分析 → 走势报告"""

    name = "stock_quote"
    description = (
        '查询指定股票的K线行情数据并分析走势。'
        '输入 JSON: {"stock": "股票名称或代码", "period": "时间粒度", "beg": "起始日期", "end": "结束日期"}'
        'period可选: daily(日线)/weekly(周线)/monthly(月线)/60min(60分钟线) 等'
        '日期格式: yyyyMMdd（如 20260101）；不传日期时自动取近期数据'
        '适合查看股价走势、涨跌情况、成交量变化等行情类问题'
    )

    def __init__(self):
        """初始化行情查询工具"""
        self._fetcher = EMQuoteFetcher()

    def run(self, stock: str, period: str = "daily", beg: str = None, end: str = None, limit: int = None):
        """
        查询股票 K 线行情并生成分析报告。

        参数
        ----
        stock  : str   股票名称（如"铜陵有色"）或代码（如"000630"）
        period : str   时间粒度，默认 "daily"。
                       可选值：1min/5min/15min/30min/60min/daily/weekly/monthly
        beg    : str or None  起始日期 yyyyMMdd（如 "20260101"）
        end    : str or None  结束日期 yyyyMMdd
        limit  : int or None  返回条数上限

        返回
        ----
        str : 结构化行情分析报告
        """
        # ---- 第 1 步：获取 K 线数据 ----
        quote_data = self._fetcher.fetch_klines(
            stock, period=period, beg=beg, end=end, limit=limit
        )
        if not quote_data:
            return f"未找到股票或获取行情数据失败: {stock}\n请检查股票名称/代码是否正确。"

        klines = quote_data["klines"]
        if not klines:
            return f"获取到 0 条 K 线数据，可能是非交易日或日期范围无效。\n股票: {stock}，粒度: {period}"

        # ---- 第 2 步：组装报告 ----
        report_parts = []
        report_parts.append(self._format_overview(quote_data))
        report_parts.append(self._analyze_trend(klines, period))
        report_parts.append(self._calc_technical_indicators(klines))
        report_parts.append(self._analyze_key_levels(klines))
        report_parts.append(self._generate_reference(quote_data, klines))

        return "\n\n".join(report_parts)

    # ==================== 报告格式化 ====================

    def _format_overview(self, quote_data):
        """格式化行情概览"""
        klines = quote_data["klines"]
        name = quote_data["name"]
        code = quote_data["code"]
        market = quote_data["market"]
        period = quote_data["period"]
        beg = quote_data["beg"]
        end = quote_data["end"]

        # 粒度中文映射
        period_cn = {
            "1min": "1分钟", "5min": "5分钟", "15min": "15分钟",
            "30min": "30分钟", "60min": "60分钟",
            "daily": "日线", "weekly": "周线", "monthly": "月线",
        }.get(period, period)

        # 计算区间统计
        first = klines[0]
        last = klines[-1]
        all_highs = [k["high"] for k in klines if k["high"] is not None]
        all_lows = [k["low"] for k in klines if k["low"] is not None]
        all_volumes = [k["volume"] for k in klines if k["volume"] is not None]

        period_high = max(all_highs) if all_highs else None
        period_low = min(all_lows) if all_lows else None
        avg_volume = sum(all_volumes) / len(all_volumes) if all_volumes else None

        # 区间涨跌幅
        if first["close"] and last["close"] and first["close"] > 0:
            total_change = (last["close"] - first["close"]) / first["close"] * 100
        else:
            total_change = None

        lines = [
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  {name}（{code}.{market}）行情分析",
            f"  粒度: {period_cn} | 区间: {beg} ~ {end} | 共 {len(klines)} 根K线",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"【行情概览】",
        ]

        if total_change is not None:
            trend_icon = "↑" if total_change > 0 else "↓" if total_change < 0 else "→"
            lines.append(f"  区间涨跌幅: {total_change:+.2f}% {trend_icon}")
        lines.append(f"  起始收盘价: {first['close']}")
        lines.append(f"  最新收盘价: {last['close']}")
        if period_high is not None:
            lines.append(f"  区间最高价: {period_high}")
        if period_low is not None:
            lines.append(f"  区间最低价: {period_low}")
        if avg_volume is not None:
            # 成交量转换为万手
            lines.append(f"  日均成交量: {avg_volume / 10000:.1f} 万手")

        # 最近5根K线简表
        lines.append("")
        lines.append(f"  最近 {min(5, len(klines))} 根K线:")
        lines.append(f"  {'日期':<20} {'开盘':>8} {'收盘':>8} {'最高':>8} {'最低':>8} {'涨跌幅':>8}")
        lines.append("  " + "-" * 68)
        for k in klines[-5:]:
            pct = f"{k['pct_change']:+.2f}%" if k['pct_change'] is not None else "N/A"
            lines.append(
                f"  {k['date']:<20} {k['open']:>8.2f} {k['close']:>8.2f} "
                f"{k['high']:>8.2f} {k['low']:>8.2f} {pct:>8}"
            )

        return "\n".join(lines)

    # ==================== 走势分析 ====================

    def _analyze_trend(self, klines, period):
        """分析价格走势趋势"""
        closes = [k["close"] for k in klines if k["close"] is not None]
        if len(closes) < 3:
            return "【走势分析】\n  数据不足，无法分析趋势"

        lines = ["【走势分析】"]

        # 1. 整体趋势方向
        first_close = closes[0]
        last_close = closes[-1]
        if first_close > 0:
            total_pct = (last_close - first_close) / first_close * 100
        else:
            total_pct = 0

        if total_pct > 5:
            trend_label = "上升趋势"
        elif total_pct < -5:
            trend_label = "下降趋势"
        else:
            trend_label = "震荡走势"
        lines.append(f"  整体趋势: {trend_label}（区间{total_pct:+.1f}%）")

        # 2. 近期走势（最后1/3的K线）
        recent_count = max(3, len(closes) // 3)
        recent_closes = closes[-recent_count:]
        recent_pct = (recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100 if recent_closes[0] > 0 else 0
        if recent_pct > 3:
            recent_label = "近期走强"
        elif recent_pct < -3:
            recent_label = "近期走弱"
        else:
            recent_label = "近期横盘"
        lines.append(f"  近期走势: {recent_label}（近{recent_count}根{recent_pct:+.1f}%）")

        # 3. 连续涨跌天数
        consecutive = 0
        direction = None
        for k in reversed(klines):
            pct = k.get("pct_change")
            if pct is None:
                break
            if direction is None:
                direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
                consecutive = 1
            elif (pct > 0 and direction == "up") or (pct < 0 and direction == "down"):
                consecutive += 1
            else:
                break

        if consecutive > 0 and direction != "flat":
            cn_period = {"daily": "日", "weekly": "周", "monthly": "月"}.get(period, "根")
            action = "上涨" if direction == "up" else "下跌"
            lines.append(f"  连续{action}: {consecutive} {cn_period}")
            if consecutive >= 5:
                lines.append(f"  ⚠ 已连续{action}{consecutive}{cn_period}，注意回调风险")

        # 4. 均线位置（如果数据够长）
        if len(closes) >= 20:
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20
            last_close = closes[-1]
            if last_close > ma5 > ma20:
                lines.append(f"  均线多头排列: 价格({last_close:.2f}) > MA5({ma5:.2f}) > MA20({ma20:.2f})")
            elif last_close < ma5 < ma20:
                lines.append(f"  均线空头排列: 价格({last_close:.2f}) < MA5({ma5:.2f}) < MA20({ma20:.2f})")
            else:
                lines.append(f"  均线交织: 价格({last_close:.2f}), MA5({ma5:.2f}), MA20({ma20:.2f})")

        return "\n".join(lines)

    # ==================== 技术指标 ====================

    def _calc_technical_indicators(self, klines):
        """计算技术指标"""
        closes = [k["close"] for k in klines if k["close"] is not None]
        volumes = [k["volume"] for k in klines if k["volume"] is not None]
        lines = ["【技术指标】"]

        # 1. 均线
        if len(closes) >= 5:
            ma5 = sum(closes[-5:]) / 5
            lines.append(f"  MA5: {ma5:.2f}")
        if len(closes) >= 10:
            ma10 = sum(closes[-10:]) / 10
            lines.append(f"  MA10: {ma10:.2f}")
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            lines.append(f"  MA20: {ma20:.2f}")
        if len(closes) >= 60:
            ma60 = sum(closes[-60:]) / 60
            lines.append(f"  MA60: {ma60:.2f}")

        # 2. 波动率（基于日涨跌幅的标准差）
        pct_changes = [k["pct_change"] for k in klines if k["pct_change"] is not None]
        if len(pct_changes) >= 5:
            avg_pct = sum(pct_changes) / len(pct_changes)
            variance = sum((p - avg_pct) ** 2 for p in pct_changes) / len(pct_changes)
            volatility = variance ** 0.5
            if volatility < 1.5:
                vol_label = "低波动"
            elif volatility < 3:
                vol_label = "中等波动"
            else:
                vol_label = "高波动"
            lines.append(f"  波动率: {volatility:.2f}%（{vol_label}）")

        # 3. 成交量分析
        if len(volumes) >= 5:
            avg_vol = sum(volumes[-5:]) / 5
            recent_avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
            if recent_avg_vol > 0:
                vol_ratio = avg_vol / recent_avg_vol
                if vol_ratio > 1.5:
                    lines.append(f"  成交量: 近5日均量是近20日的 {vol_ratio:.1f} 倍（放量）")
                elif vol_ratio < 0.5:
                    lines.append(f"  成交量: 近5日均量是近20日的 {vol_ratio:.1f} 倍（缩量）")
                else:
                    lines.append(f"  成交量: 近5日均量是近20日的 {vol_ratio:.1f} 倍（正常）")

        # 4. RSI 简易计算（14周期）
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(1, min(15, len(closes))):
                diff = closes[i] - closes[i - 1]
                gains.append(max(0, diff))
                losses.append(max(0, -diff))
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100
            if rsi > 70:
                rsi_label = "超买"
            elif rsi < 30:
                rsi_label = "超卖"
            else:
                rsi_label = "正常"
            lines.append(f"  RSI(14): {rsi:.1f}（{rsi_label}）")

        return "\n".join(lines)

    # ==================== 关键价位 ====================

    def _analyze_key_levels(self, klines):
        """分析关键支撑位和压力位"""
        lines = ["【关键价位】"]

        # 使用近期高低点作为支撑/压力
        recent = klines[-min(20, len(klines)):]
        highs = [k["high"] for k in recent if k["high"] is not None]
        lows = [k["low"] for k in recent if k["low"] is not None]

        if not highs or not lows:
            lines.append("  数据不足")
            return "\n".join(lines)

        recent_high = max(highs)
        recent_low = min(lows)
        last_close = klines[-1]["close"]

        lines.append(f"  近期压力位: {recent_high:.2f}（区间最高价）")
        lines.append(f"  近期支撑位: {recent_low:.2f}（区间最低价）")
        lines.append(f"  当前价位: {last_close:.2f}")

        # 计算当前位置在区间中的位置
        if recent_high > recent_low:
            position = (last_close - recent_low) / (recent_high - recent_low) * 100
            if position > 80:
                pos_label = "接近压力位"
            elif position < 20:
                pos_label = "接近支撑位"
            else:
                pos_label = "区间中部"
            lines.append(f"  位置: {pos_label}（{position:.0f}%）")

        return "\n".join(lines)

    # ==================== 操作参考 ====================

    def _generate_reference(self, quote_data, klines):
        """生成基于技术面的操作参考"""
        name = quote_data["name"]
        closes = [k["close"] for k in klines if k["close"] is not None]
        pct_changes = [k["pct_change"] for k in klines if k["pct_change"] is not None]

        lines = [f"【操作参考 —— {name}】"]

        # 综合技术面评分
        score = 0

        # 趋势评分
        if len(closes) >= 2:
            total_pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
            if total_pct > 10:
                score += 2
            elif total_pct > 0:
                score += 1
            elif total_pct < -10:
                score -= 2
            else:
                score -= 1

        # 均线评分
        if len(closes) >= 20:
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20
            if closes[-1] > ma5 > ma20:
                score += 2
            elif closes[-1] < ma5 < ma20:
                score -= 2

        # RSI 评分
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(1, min(15, len(closes))):
                diff = closes[i] - closes[i - 1]
                gains.append(max(0, diff))
                losses.append(max(0, -diff))
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            if avg_loss > 0:
                rsi = 100 - (100 / (1 + avg_gain / avg_loss))
            else:
                rsi = 100
            if rsi > 70:
                score -= 1
            elif rsi < 30:
                score += 1

        # 连续涨跌评分
        if pct_changes:
            consecutive = 0
            direction = None
            for pct in reversed(pct_changes):
                if direction is None:
                    direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
                    consecutive = 1
                elif (pct > 0 and direction == "up") or (pct < 0 and direction == "down"):
                    consecutive += 1
                else:
                    break
            if consecutive >= 5:
                score -= 1  # 连续涨跌过多，回调风险

        # 生成建议
        if score >= 3:
            lines.append(f"  技术面评分: {score} 分（偏多）")
            lines.append(f"  趋势向上且技术面配合，短期偏强运行")
            lines.append(f"  关注上方压力位能否突破，突破可看高一线")
        elif score >= 1:
            lines.append(f"  技术面评分: {score} 分（中性偏多）")
            lines.append(f"  走势偏强但需确认，可持有观察")
            lines.append(f"  重点关注均线支撑是否有效")
        elif score >= -1:
            lines.append(f"  技术面评分: {score} 分（中性）")
            lines.append(f"  多空交织，方向不明，建议观望")
            lines.append(f"  等待趋势明朗后再做决策")
        else:
            lines.append(f"  技术面评分: {score} 分（偏空）")
            lines.append(f"  走势偏弱，注意下方支撑位")
            lines.append(f"  若跌破支撑位需考虑风险控制")

        lines.append("")
        lines.append("  ⚠ 免责声明: 以上分析基于K线技术面，不构成投资建议。")
        lines.append("    技术分析有局限性，请结合基本面综合判断。")

        return "\n".join(lines)
