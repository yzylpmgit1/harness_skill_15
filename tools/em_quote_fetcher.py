# -*- coding: utf-8 -*-
"""
多源 K 线行情数据获取模块
==========================
通过多个公开免费接口获取任意 A 股的多时间粒度行情数据。
无需 API Key，无需注册，完全免费。

数据源策略（三级回退）：
  1. 腾讯财经接口（web.ifzq.gtimg.cn）
     - 支持：日线、周线、月线（前复权）
     - 优势：数据格式规范，支持日期范围
  2. 新浪财经接口（money.finance.sina.com.cn）
     - 支持：5分钟、15分钟、30分钟、60分钟、日线
     - 优势：分钟级数据支持好
  3. 东方财富接口（push2his.eastmoney.com）
     - 支持：全粒度
     - 作为补充备用（部分网络环境可能不可达）

支持的时间粒度：
  - 分钟级：5 分钟、15 分钟、30 分钟、60 分钟
  - 日线：每个交易日的开高低收
  - 周线：每周汇总
  - 月线：每月汇总

股票搜索和实时行情使用东方财富接口：
  - 搜索接口：searchapi.eastmoney.com（稳定可用）
  - 实时行情：push2.eastmoney.com（稳定可用）

使用示例：
  from tools.em_quote_fetcher import EMQuoteFetcher

  fetcher = EMQuoteFetcher()
  # 获取铜陵有色最近 30 天的日 K 线
  quotes = fetcher.fetch_klines("铜陵有色", period="daily", beg="20260601", end="20260630")
  # 获取贵州茅台近 2 年的月 K 线
  quotes = fetcher.fetch_klines("贵州茅台", period="monthly", beg="20240101", end="20260730")
  # 获取贵州茅台 60 分钟 K 线
  quotes = fetcher.fetch_klines("贵州茅台", period="60min")
"""
import requests
from datetime import datetime, timedelta


class EMQuoteFetcher:
    """
    多源 K 线行情数据获取器。

    支持任意 A 股的多时间粒度 K 线数据获取。
    自动选择最佳数据源，保证数据可用性。
    """

    # ============================================================
    # 东方财富接口（股票搜索 + 实时行情）
    # ============================================================
    SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
    INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"

    # ============================================================
    # 腾讯财经接口（日/周/月 K 线）
    # ============================================================
    TENCENT_KLINE_URL = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    # ============================================================
    # 新浪财经接口（分钟级 + 日 K 线）
    # ============================================================
    SINA_KLINE_URL = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"

    # 固定 token（东方财富公开接口通用值）
    UT_TOKEN = "f057cbcbce2a86e2866ab8877db1d059"

    # HTTP 请求头（模拟浏览器）
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://quote.eastmoney.com/",
    }

    # 请求超时（秒）
    TIMEOUT = 15

    # 时间粒度到腾讯 type 的映射
    # 腾讯支持: day, week, month
    TENCENT_TYPE_MAP = {
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
    }

    # 时间粒度到新浪 scale 的映射
    # 新浪支持: 5, 15, 30, 60（分钟）, 240（日线）
    # 注意：新浪不支持 1 分钟线，1min 会回退到 5min
    SINA_SCALE_MAP = {
        "1min": 5,       # 回退到 5 分钟
        "5min": 5,
        "15min": 15,
        "30min": 30,
        "60min": 60,
        "daily": 240,
    }

    def __init__(self):
        """初始化数据获取器"""
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    # ============================================================
    # 公开方法
    # ============================================================

    def fetch_klines(self, query, period="daily", beg=None, end=None, limit=None):
        """
        获取股票 K 线行情数据（主入口方法）。

        自动选择最佳数据源：
          - 日线/周线/月线 → 腾讯财经接口
          - 分钟级（5/15/30/60min） → 新浪财经接口

        参数
        ----
        query  : str   股票名称（如"铜陵有色"）或代码（如"000630"）
        period : str   时间粒度，可选值：
                       "1min"/"5min"/"15min"/"30min"/"60min"（分钟级）
                       "daily"（日线，默认）
                       "weekly"（周线）
                       "monthly"（月线）
        beg    : str or None  开始日期，格式 yyyyMMdd（如 "20260101"）。
                              为 None 时自动取默认范围。
        end    : str or None  结束日期，格式 yyyyMMdd。
                              为 None 时取当前日期。
        limit  : int or None  返回条数上限。为 None 时不限制。

        返回
        ----
        dict or None : 行情数据结构，失败返回 None。结构如下：
            {
                "code": "000630",
                "name": "铜陵有色",
                "market": "SZ",
                "period": "daily",
                "beg": "20260601",
                "end": "20260630",
                "klines": [
                    {
                        "date": "2026-06-01",
                        "open": 3.45,
                        "close": 3.50,
                        "high": 3.52,
                        "low": 3.43,
                        "volume": 12345600,     # 成交量（手）
                        "amount": None,          # 成交额（元，部分数据源不提供）
                        "amplitude": 2.61,       # 振幅（%）
                        "pct_change": 1.45,      # 涨跌幅（%）
                        "change": 0.05,          # 涨跌额（元）
                        "turnover": None,        # 换手率（%，部分数据源不提供）
                    },
                    ...
                ]
            }
        """
        # 第 1 步：搜索股票代码
        stock_info = self._search_stock(query)
        if not stock_info:
            return None

        code = stock_info["code"]
        name = stock_info["name"]
        market = stock_info["market"]

        # 生成腾讯/新浪格式代码（如 sh600519, sz000630）
        sina_symbol = f"{'sh' if market == 'SH' else 'sz'}{code}"

        # 第 2 步：设置默认时间范围
        if end is None:
            end = datetime.now().strftime("%Y%m%d")
        if beg is None:
            end_dt = datetime.strptime(end, "%Y%m%d")
            if period in ("1min", "5min", "15min", "30min", "60min"):
                # 分钟线默认取最近 5 个交易日
                beg = (end_dt - timedelta(days=7)).strftime("%Y%m%d")
            elif period == "daily":
                # 日线默认取最近 30 天
                beg = (end_dt - timedelta(days=30)).strftime("%Y%m%d")
            elif period == "weekly":
                # 周线默认取最近 1 年
                beg = (end_dt - timedelta(days=365)).strftime("%Y%m%d")
            elif period == "monthly":
                # 月线默认取最近 2 年
                beg = (end_dt - timedelta(days=730)).strftime("%Y%m%d")

        # 第 3 步：根据粒度选择数据源获取 K 线
        klines = None

        if period in self.TENCENT_TYPE_MAP:
            # 日/周/月线 → 优先用腾讯接口
            klines = self._fetch_tencent_klines(sina_symbol, period, beg, end, limit)
            # 腾讯失败时回退到新浪（仅日线）
            if klines is None and period == "daily":
                klines = self._fetch_sina_klines(sina_symbol, period, beg, end, limit)

        elif period in self.SINA_SCALE_MAP:
            # 分钟级 → 用新浪接口
            klines = self._fetch_sina_klines(sina_symbol, period, beg, end, limit)

        if klines is None or not klines:
            return None

        # 第 4 步：组装返回结构
        return {
            "code": code,
            "name": name,
            "market": market,
            "period": period,
            "beg": beg,
            "end": end,
            "klines": klines,
        }

    def fetch_realtime_quote(self, query):
        """
        获取股票实时行情快照（使用东方财富接口）。

        参数
        ----
        query : str  股票名称或代码

        返回
        ----
        dict or None : 实时行情数据
        """
        stock_info = self._search_stock(query)
        if not stock_info:
            return None

        code = stock_info["code"]
        name = stock_info["name"]
        market = stock_info["market"]
        secid = f"{'1' if market == 'SH' else '0'}.{code}"

        try:
            resp = self._session.get(
                self.INFO_URL,
                params={
                    "secid": secid,
                    "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f170,f171,f162,f164,f116,f117",
                    "ut": self.UT_TOKEN,
                },
                timeout=self.TIMEOUT,
            )
            data = resp.json().get("data", {})
            if not data:
                return None

            return {
                "code": code,
                "name": data.get("f58", name),
                "price": data.get("f43"),
                "change": data.get("f171"),
                "pct_change": data.get("f170"),
                "open": data.get("f46"),
                "high": data.get("f44"),
                "low": data.get("f45"),
                "pre_close": data.get("f60"),
                "volume": data.get("f47"),
                "amount": data.get("f48"),
                "turnover": data.get("f168"),
                "pe": data.get("f162"),
                "pb": data.get("f164"),
                "market_cap": data.get("f116"),
                "float_market_cap": data.get("f117"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            return None

    # ============================================================
    # 股票搜索（东方财富搜索接口）
    # ============================================================

    # 沪市代码前缀：股票 + ETF/基金
    #   60xxxx  沪市主板
    #   68xxxx  科创板
    #   90xxxx  沪市 B 股
    #   50xxxx  沪市基金/ETF（如 510300 沪深300ETF）
    #   51xxxx  沪市 ETF（如 516920 芯片ETF汇添富）
    #   56xxxx  沪市 ETF
    #   58xxxx  科创板 ETF
    SH_PREFIXES = ("60", "68", "90", "50", "51", "56", "58")

    # 深市代码前缀：股票 + ETF/基金
    #   00xxxx  深市主板/中小板
    #   30xxxx  创业板
    #   20xxxx  深市 B 股
    #   15xxxx  深市 ETF（如 159915 创业板ETF）
    #   16xxxx  深市基金/LOF
    #   18xxxx  深市 ETF
    SZ_PREFIXES = ("00", "30", "20", "15", "16", "18")

    def _search_stock(self, query):
        """
        搜索股票/ETF/基金，返回代码、名称、市场信息。

        策略：搜索 API 优先（快速可靠，自动返回正确市场），
              失败时回退到代码前缀推断 + push2 名称查询。

        返回
        ----
        dict or None : {"code": "516920", "name": "芯片ETF汇添富", "market": "SH"}
        """
        query = query.strip()

        # ---- 策略 1：优先调用搜索 API（最快最可靠）----
        # 搜索 API 支持股票名称和代码，自动返回正确的 MktNum
        search_result = self._search_via_api(query)
        if search_result:
            return search_result

        # ---- 策略 2：纯数字代码 → 前缀推断市场 + push2 查名称 ----
        # 当搜索 API 未命中时（如某些新股/冷门品种），用代码前缀推断
        if query.isdigit() and len(query) == 6:
            if query.startswith(self.SH_PREFIXES):
                market = "SH"
            elif query.startswith(self.SZ_PREFIXES):
                market = "SZ"
            else:
                # 未知前缀，默认深市
                market = "SZ"

            name = self._fetch_stock_name(query, market)
            if name:
                return {"code": query, "name": name, "market": market}

        return None

    def _search_via_api(self, query):
        """
        通过东方财富搜索 API 查询股票/ETF/基金。

        参数
        ----
        query : str  股票名称或代码

        返回
        ----
        dict or None : {"code": "516920", "name": "芯片ETF汇添富", "market": "SH"}
        """
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={
                    "input": query,
                    "type": "14",  # 14 = 股票+基金+ETF
                    "token": "D43BF722C8E33BDC906FB84D85E326E8",
                    "count": "10",
                },
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            qct = data.get("QuotationCodeTable", {})
            if isinstance(qct, dict):
                results = qct.get("Data", [])
            else:
                results = qct
            if not results:
                return None

            # 优先匹配精确代码，其次取第一个结果
            query_stripped = query.strip()
            for item in results:
                code = item.get("Code", "")
                name = item.get("Name", "")
                mkt = item.get("MktNum", "")
                if mkt in ("0", "1") and len(code) == 6:
                    # 如果查询是纯数字代码，优先匹配精确代码
                    if query_stripped == code:
                        market = "SH" if mkt == "1" else "SZ"
                        return {"code": code, "name": name, "market": market}

            # 没有精确匹配，取第一个有效结果
            for item in results:
                code = item.get("Code", "")
                name = item.get("Name", "")
                mkt = item.get("MktNum", "")
                if mkt in ("0", "1") and len(code) == 6:
                    market = "SH" if mkt == "1" else "SZ"
                    return {"code": code, "name": name, "market": market}

            return None
        except Exception:
            return None

    def _fetch_stock_name(self, code, market):
        """通过行情接口获取股票名称"""
        try:
            secid = f"{'1' if market == 'SH' else '0'}.{code}"
            resp = self._session.get(
                self.INFO_URL,
                params={"secid": secid, "fields": "f57,f58", "ut": self.UT_TOKEN},
                timeout=self.TIMEOUT,
            )
            data = resp.json().get("data", {})
            return data.get("f58")
        except Exception:
            return None

    # ============================================================
    # 腾讯财经 K 线接口（日/周/月线）
    # ============================================================

    def _fetch_tencent_klines(self, symbol, period, beg, end, limit=None):
        """
        通过腾讯财经接口获取日/周/月 K 线数据。

        参数
        ----
        symbol : str  腾讯格式代码（如 "sh600519"）
        period : str  时间粒度（daily/weekly/monthly）
        beg    : str  开始日期 yyyyMMdd
        end    : str  结束日期 yyyyMMdd
        limit  : int or None  返回条数上限

        返回
        ----
        list[dict] or None : 结构化 K 线数据列表
        """
        # 腾讯 K 线类型
        ktype = self.TENCENT_TYPE_MAP.get(period)
        if ktype is None:
            return None

        # 腾讯日期格式：yyyy-MM-dd
        beg_fmt = f"{beg[:4]}-{beg[4:6]}-{beg[6:8]}"
        end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]}"

        # 默认条数：腾讯要求传入 count
        count = limit if limit else 1000

        # 构造请求参数：param=sh600519,day,2026-06-01,2026-07-30,1000,qfq
        param_str = f"{symbol},{ktype},{beg_fmt},{end_fmt},{count},qfq"

        try:
            resp = self._session.get(
                self.TENCENT_KLINE_URL,
                params={"param": param_str},
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                return None

            # 腾讯返回的数据键名：qfqday / qfqweek / qfqmonth
            stock_data = data.get("data", {}).get(symbol, {})
            data_key = f"qfq{ktype}"
            raw_klines = stock_data.get(data_key)

            # 部分股票可能返回不带 qfq 前缀的键
            if not raw_klines:
                raw_klines = stock_data.get(ktype)

            if not raw_klines:
                return None

            # 解析腾讯 K 线数据
            # 格式: [date, open, close, high, low, volume]
            return self._parse_tencent_klines(raw_klines)

        except Exception:
            return None

    @staticmethod
    def _parse_tencent_klines(raw_klines):
        """
        解析腾讯财经 K 线数据为统一格式。

        腾讯原始格式（数组）：
            [日期, 开盘价, 收盘价, 最高价, 最低价, 成交量]
            示例: ["2026-06-17", "1229.976", "1211.976", "1231.746", "1210.536", "44803.000"]

        注意：腾讯的数组顺序是 [日期, 开, 收, 高, 低, 量]，
              不是 [日期, 开, 高, 低, 收, 量]，需要特别留意。

        返回
        ----
        list[dict] : 统一格式的 K 线数据列表，包含计算得出的涨跌幅等指标
        """
        def safe_float(val):
            """安全转换为 float"""
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def safe_int(val):
            """安全转换为 int"""
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None

        klines = []
        prev_close = None  # 用于计算涨跌幅

        for raw in raw_klines:
            if len(raw) < 6:
                continue

            date = raw[0]
            open_price = safe_float(raw[1])
            close_price = safe_float(raw[2])
            high = safe_float(raw[3])
            low = safe_float(raw[4])
            volume = safe_int(raw[5])

            # 计算涨跌幅和涨跌额（需要前一根的收盘价）
            if prev_close is not None and prev_close > 0 and close_price is not None:
                change = close_price - prev_close
                pct_change = (change / prev_close) * 100
            else:
                change = None
                pct_change = None

            # 计算振幅 = (最高 - 最低) / 前收盘 * 100
            if prev_close is not None and prev_close > 0 and high is not None and low is not None:
                amplitude = ((high - low) / prev_close) * 100
            else:
                amplitude = None

            klines.append({
                "date": date,
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": None,          # 腾讯不提供成交额
                "amplitude": amplitude,
                "pct_change": pct_change,
                "change": change,
                "turnover": None,        # 腾讯不提供换手率
            })

            # 更新前收盘价
            if close_price is not None:
                prev_close = close_price

        return klines

    # ============================================================
    # 新浪财经 K 线接口（分钟级 + 日线）
    # ============================================================

    def _fetch_sina_klines(self, symbol, period, beg, end, limit=None):
        """
        通过新浪财经接口获取分钟级或日 K 线数据。

        参数
        ----
        symbol : str  新浪格式代码（如 "sh600519"）
        period : str  时间粒度（5min/15min/30min/60min/daily）
        beg    : str  开始日期 yyyyMMdd
        end    : str  结束日期 yyyyMMdd
        limit  : int or None  返回条数上限

        返回
        ----
        list[dict] or None : 结构化 K 线数据列表
        """
        scale = self.SINA_SCALE_MAP.get(period)
        if scale is None:
            return None

        # 新浪接口通过 datalen 控制返回条数
        # 不支持日期范围，需要获取足够数据后按日期过滤
        datalen = limit if limit else 1000

        try:
            resp = self._session.get(
                self.SINA_KLINE_URL,
                params={
                    "symbol": symbol,
                    "scale": str(scale),
                    "ma": "no",
                    "datalen": str(datalen),
                },
                timeout=self.TIMEOUT,
            )

            # 新浪返回的是 JSON 数组
            raw_klines = resp.json()
            if not raw_klines:
                return None

            # 解析新浪 K 线数据
            klines = self._parse_sina_klines(raw_klines)

            # 按日期范围过滤
            # 新浪日期格式：日线为 "2026-06-18"，分钟线为 "2026-07-30 14:40:00"
            beg_fmt = f"{beg[:4]}-{beg[4:6]}-{beg[6:8]}"
            end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]}"

            filtered = []
            for k in klines:
                # 取日期部分进行比较（分钟线只取日期）
                kline_date = k["date"][:10]  # "2026-07-30" 或 "2026-07-30 14:40:00" → "2026-07-30"
                if beg_fmt <= kline_date <= end_fmt:
                    filtered.append(k)

            return filtered if filtered else None

        except Exception:
            return None

    @staticmethod
    def _parse_sina_klines(raw_klines):
        """
        解析新浪财经 K 线数据为统一格式。

        新浪原始格式（JSON 数组）：
            [{"day": "2026-07-30 14:40:00", "open": "1354.920",
              "high": "1356.970", "low": "1354.900", "close": "1356.490",
              "volume": "81831"}, ...]

        返回
        ----
        list[dict] : 统一格式的 K 线数据列表，包含计算得出的涨跌幅等指标
        """
        def safe_float(val):
            """安全转换为 float"""
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def safe_int(val):
            """安全转换为 int"""
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None

        klines = []
        prev_close = None

        for raw in raw_klines:
            date = raw.get("day", "")
            open_price = safe_float(raw.get("open"))
            close_price = safe_float(raw.get("close"))
            high = safe_float(raw.get("high"))
            low = safe_float(raw.get("low"))
            volume = safe_int(raw.get("volume"))

            # 计算涨跌幅
            if prev_close is not None and prev_close > 0 and close_price is not None:
                change = close_price - prev_close
                pct_change = (change / prev_close) * 100
            else:
                change = None
                pct_change = None

            # 计算振幅
            if prev_close is not None and prev_close > 0 and high is not None and low is not None:
                amplitude = ((high - low) / prev_close) * 100
            else:
                amplitude = None

            klines.append({
                "date": date,
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": None,          # 新浪不提供成交额
                "amplitude": amplitude,
                "pct_change": pct_change,
                "change": change,
                "turnover": None,        # 新浪不提供换手率
            })

            if close_price is not None:
                prev_close = close_price

        return klines
