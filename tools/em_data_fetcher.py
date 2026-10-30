# -*- coding: utf-8 -*-
"""
东方财富公开 API 数据获取模块
================================
通过东方财富的公开 Web 接口获取任意 A 股股票的 3 年财务数据。
无需 API Key，无需注册，完全免费。

数据来源：东方财富网 F10 数据中心
  - 利润表接口：lrbAjaxNew → 营收、净利润、毛利率、净利率
  - 资产负债表接口：zcfzbAjaxNew → 负债率、ROE
  - 股票基本信息接口：push2.eastmoney.com → 行业、名称

工作流程：
  1. 根据用户输入搜索股票代码
  2. 获取近 3 年年报利润表（营收、净利润、增速）
  3. 获取近 3 年年报资产负债表（总负债、总资产 → 负债率）
  4. 计算毛利率、净利率、ROE 等衍生指标
  5. 组装为与 stock_metrics.json 一致的数据结构

使用示例：
  from tools.em_data_fetcher import EMDataFetcher

  fetcher = EMDataFetcher()
  stock_data = fetcher.fetch_stock("铜陵有色")
  # stock_data 格式与 stock_metrics.json 中单只股票的结构完全一致
"""
import requests
import json
import time
from datetime import datetime


class EMDataFetcher:
    """
    东方财富数据获取器：获取任意 A 股的 3 年财务数据。

    所有数据通过 HTTP GET 请求获取，无需安装额外库（仅依赖 requests）。
    """

    # 东方财富 API 基础配置
    SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
    INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    # 利润表接口（返回 3 年年报数据）
    INCOME_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/lrbAjaxNew"
    # 资产负债表接口（返回 3 年年报数据）
    BALANCE_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/zcfzbAjaxNew"
    # 财务指标接口（返回最近几期的指标值）
    INDICATOR_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/zyzbAjaxNew"
    # 公司概况接口（返回行业、主营业务等信息）
    COMPANY_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"

    # HTTP 请求头（模拟浏览器，避免被识别为爬虫）
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://emweb.securities.eastmoney.com/",
    }

    # 请求超时时间（秒）
    TIMEOUT = 15

    def __init__(self):
        """初始化数据获取器"""
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    # ============================================================
    # 公开方法
    # ============================================================

    def fetch_stock(self, query, start_year=None, end_year=None):
        """
        获取股票的财务数据（主入口方法）。

        参数
        ----
        query : str  股票名称（如"铜陵有色"）或代码（如"000630"）

        start_year : int or None
            自定义起始年份（如 2020）。为 None 时自动取最近 3 年。

        end_year : int or None
            自定义结束年份（如 2022）。为 None 时自动取最近 3 年。
            当 start_year 和 end_year 同时给出时，获取 [start_year, end_year] 区间的年报数据。

        返回
        ----
        dict or None : 股票数据结构（与 stock_metrics.json 格式一致），失败返回 None
        """
        # 第 1 步：搜索股票代码
        stock_info = self._search_stock(query)
        if not stock_info:
            return None

        code = stock_info["code"]
        name = stock_info["name"]
        market = stock_info["market"]  # "SH" 或 "SZ"
        em_code = stock_info["em_code"]  # 东方财富格式如 "SZ000630"

        # 第 2 步：获取基本信息（行业）
        industry = self._fetch_industry(em_code, market)

        # 第 3 步：确定查询日期（自定义区间 or 最近 3 年）
        if start_year is not None and end_year is not None:
            # 用户指定了时间区间
            dates = self._calc_dates_from_range(start_year, end_year)
        else:
            # 默认：动态计算最近 3 年
            dates = self._calc_recent_3y_dates()

        # 第 4 步：获取利润表
        income_data = self._fetch_income_statement(em_code, dates)
        if not income_data:
            return None  # 利润表是核心数据，获取失败则放弃

        # 第 5 步：获取资产负债表
        balance_data = self._fetch_balance_sheet(em_code, dates)

        # 第 6 步：组装财务数据
        years = self._build_years_data(income_data, balance_data)
        if not years:
            return None

        # 第 7 步：组装完整股票数据结构
        stock_data = {
            "code": code,
            "name": name,
            "market": market,
            "industry": industry or "未知",
            "description": f"{name}（{code}.{market}），数据来源：东方财富",
            "years": years,
            "data_source": "东方财富实时获取",
        }
        return stock_data

    # ============================================================
    # 股票搜索
    # ============================================================

    def _search_stock(self, query):
        """
        搜索股票，返回代码、名称、市场信息。

        参数
        ----
        query : str  股票名称或代码

        返回
        ----
        dict or None : {"code": "000630", "name": "铜陵有色", "market": "SZ", "em_code": "SZ000630"}
        """
        # 如果输入是纯数字，当作股票代码处理
        query = query.strip()
        if query.isdigit() and len(query) == 6:
            # 根据代码前缀判断市场
            if query.startswith(("60", "68", "90")):
                market = "SH"
            else:
                market = "SZ"
            em_code = f"{market}{query}"
            # 获取真实名称
            name = self._fetch_stock_name(query, market)
            if name:
                return {
                    "code": query,
                    "name": name,
                    "market": market,
                    "em_code": em_code,
                }

        # 调用搜索 API
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={
                    "input": query,
                    "type": "14",
                    "token": "D43BF722C8E33BDC906FB84D85E326E8",
                    "count": "10",
                },
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            # 东方财富搜索 API 返回格式：{"QuotationCodeTable": {"Data": [...]}}
            qct = data.get("QuotationCodeTable", {})
            if isinstance(qct, dict):
                results = qct.get("Data", [])
            else:
                results = qct  # 兼容旧格式（直接是列表）
            if not results:
                return None

            # 筛选 A 股（排除港股、美股、基金等）
            for item in results:
                code = item.get("Code", "")
                name = item.get("Name", "")
                mkt = item.get("MktNum", "")
                # 只保留 A 股（沪深）
                if mkt in ("0", "1") and len(code) == 6:
                    market = "SH" if mkt == "1" else "SZ"
                    em_code = f"{market}{code}"
                    return {
                        "code": code,
                        "name": name,
                        "market": market,
                        "em_code": em_code,
                    }
            return None
        except Exception:
            return None

    def _fetch_stock_name(self, code, market):
        """通过行情接口获取股票名称"""
        try:
            secid = f"{'1' if market == 'SH' else '0'}.{code}"
            resp = self._session.get(
                self.INFO_URL,
                params={"secid": secid, "fields": "f57,f58"},
                timeout=self.TIMEOUT,
            )
            data = resp.json().get("data", {})
            return data.get("f58")
        except Exception:
            return None

    def _fetch_industry(self, em_code, market):
        """
        获取股票所属行业和主营业务。

        使用东方财富 F10 公司概况接口，返回字段说明：
          - jbzl.sshy: 所属行业（如"有色金属"）
          - jbzl.sszjhhy: 证监会行业（如"制造业-有色金属冶炼和压延加工业"）
          - jbzl.gsmc: 公司全称

        参数
        ----
        em_code : str  东方财富格式代码（如 "SZ000630"）
        market  : str  市场标识（未使用，保留兼容）

        返回
        ----
        str : 行业名称，获取失败返回 None
        """
        try:
            resp = self._session.get(
                self.COMPANY_URL,
                params={"code": em_code},
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            jbzl = data.get("jbzl", {})
            # 优先取所属行业（sshy），其次取证监会行业
            industry = jbzl.get("sshy") or jbzl.get("sszjhhy")
            return industry
        except Exception:
            return None

    # ============================================================
    # 财务报表获取
    # ============================================================

    @staticmethod
    def _calc_recent_3y_dates():
        """
        动态计算最近 3 个已披露年报的日期。

        年报披露规则：A 股年报须在次年 4 月 30 日前披露。
        因此：
          - 当前月份 > 4 月：上一年年报已基本披露完毕 → 取 [去年, 前年, 大前年]
          - 当前月份 <= 4 月：上一年年报尚未披露完 → 取 [前年, 大前年, 更前年]

        返回
        ----
        str : 逗号分隔的日期字符串，如 "2025-12-31,2024-12-31,2023-12-31"
        """
        now = datetime.now()
        current_year = now.year

        if now.month <= 4:
            # 1-4 月：上年年报可能未发完，保守取上上年往前 3 年
            years = [current_year - 2, current_year - 3, current_year - 4]
        else:
            # 5-12 月：上年年报基本发完
            years = [current_year - 1, current_year - 2, current_year - 3]

        return ",".join(f"{y}-12-31" for y in years)

    @staticmethod
    def _calc_dates_from_range(start_year, end_year):
        """
        根据用户指定的年份区间生成查询日期字符串。

        参数
        ----
        start_year : int  起始年份（如 2020）
        end_year   : int  结束年份（如 2022）

        返回
        ----
        str : 逗号分隔的日期字符串，按年份降序排列（东方财富 API 要求）
              如 "2022-12-31,2021-12-31,2020-12-31"
        """
        # 生成从 end_year 到 start_year 的所有年份（降序）
        years = list(range(end_year, start_year - 1, -1))
        return ",".join(f"{y}-12-31" for y in years)

    def _fetch_income_statement(self, em_code, dates=None):
        """
        获取利润表年报数据。

        东方财富利润表接口返回字段说明（关键字段）：
          - OPERATE_INCOME: 营业收入（元）
          - OPERATE_INCOME_YOY: 营业收入同比增长率（%）
          - OPERATE_COST: 营业成本（元）→ 可计算毛利率
          - PARENT_NETPROFIT: 归母净利润（元）
          - PARENT_NETPROFIT_YOY: 归母净利润同比增长率（%）
          - NETPROFIT: 净利润（元）→ 可计算净利率
          - REPORT_DATE: 报告日期

        参数
        ----
        em_code : str  东方财富格式代码（如 "SZ000630"）
        dates   : str or None
            逗号分隔的日期字符串。为 None 时自动取最近 3 年。

        返回
        ----
        list[dict] : 利润表记录列表（每条是一个年度）
        """
        if dates is None:
            dates = self._calc_recent_3y_dates()
        try:
            resp = self._session.get(
                self.INCOME_URL,
                params={
                    "companyType": "4",
                    "reportDateType": "0",  # 年报
                    "reportType": "1",      # 合并报表
                    "dates": dates,
                    "code": em_code,
                },
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            return data.get("data", [])
        except Exception:
            return []

    def _fetch_balance_sheet(self, em_code, dates=None):
        """
        获取资产负债表年报数据。

        关键字段：
          - TOTAL_ASSETS: 资产总计（元）
          - TOTAL_LIABILITIES: 负债合计（元）→ 可计算资产负债率
          - TOTAL_EQUITY: 所有者权益合计（元）→ 可计算 ROE

        参数
        ----
        em_code : str  东方财富格式代码
        dates   : str or None
            逗号分隔的日期字符串。为 None 时自动取最近 3 年。

        返回
        ----
        list[dict] : 资产负债表记录列表
        """
        if dates is None:
            dates = self._calc_recent_3y_dates()
        try:
            resp = self._session.get(
                self.BALANCE_URL,
                params={
                    "companyType": "4",
                    "reportDateType": "0",
                    "reportType": "1",
                    "dates": dates,
                    "code": em_code,
                },
                timeout=self.TIMEOUT,
            )
            data = resp.json()
            return data.get("data", [])
        except Exception:
            return []

    # ============================================================
    # 数据组装
    # ============================================================

    def _build_years_data(self, income_data, balance_data):
        """
        将利润表和资产负债表数据组装为 3 年财务数据结构。

        参数
        ----
        income_data  : list[dict]  利润表记录列表
        balance_data : list[dict]  资产负债表记录列表

        返回
        ----
        list[dict] : 3 年财务数据，格式与 stock_metrics.json 一致（按年份升序）
        """
        # 将资产负债表按报告日期索引，方便查找
        balance_map = {}
        for item in balance_data:
            report_date = item.get("REPORT_DATE", "")
            if report_date:
                # 提取年份（如 "2023-12-31" → "2023"）
                year = report_date[:4]
                balance_map[year] = item

        years = []
        for income in income_data:
            report_date = income.get("REPORT_DATE", "")
            if not report_date:
                continue
            year = report_date[:4]

            # ---- 从利润表提取数据 ----
            revenue = income.get("OPERATE_INCOME")          # 营业收入（元）
            operating_cost = income.get("OPERATE_COST")      # 营业成本（元）
            net_profit = income.get("PARENT_NETPROFIT")      # 归母净利润（元）
            total_netprofit = income.get("NETPROFIT")        # 净利润总额（元）
            revenue_yoy = income.get("OPERATE_INCOME_YOY")   # 营收增速（%）
            profit_yoy = income.get("PARENT_NETPROFIT_YOY")  # 归母净利润增速（%）

            # ---- 计算毛利率 ----
            # 毛利率 = (营业收入 - 营业成本) / 营业收入 × 100
            gross_margin = None
            if revenue and operating_cost and revenue > 0:
                gross_margin = round((revenue - operating_cost) / revenue * 100, 2)

            # ---- 计算净利率 ----
            # 净利率 = 归母净利润 / 营业收入 × 100
            net_margin = None
            if net_profit and revenue and revenue > 0:
                net_margin = round(net_profit / revenue * 100, 2)

            # ---- 从资产负债表计算负债率 ----
            debt_ratio = None
            balance = balance_map.get(year)
            if balance:
                total_liab = balance.get("TOTAL_LIABILITIES")
                total_assets = balance.get("TOTAL_ASSETS")
                if total_liab and total_assets and total_assets > 0:
                    debt_ratio = round(total_liab / total_assets * 100, 2)

            # ---- 计算 ROE ----
            # ROE = 归母净利润 / 所有者权益合计 × 100
            roe = None
            if balance and net_profit:
                total_equity = balance.get("TOTAL_EQUITY")
                if total_equity and total_equity > 0:
                    roe = round(net_profit / total_equity * 100, 2)

            year_data = {
                "year": year,
                # 营业收入（转换为亿元）
                "revenue_yi": round(revenue / 1e8, 2) if revenue else None,
                # 归母净利润（转换为亿元）
                "net_profit_yi": round(net_profit / 1e8, 2) if net_profit else None,
                # 毛利率（%）
                "gross_margin": gross_margin,
                # 净利率（%）
                "net_margin": net_margin,
                # ROE（%）
                "roe": roe,
                # 资产负债率（%）
                "debt_ratio": debt_ratio,
                # 营收同比增长率（%）
                "revenue_yoy": round(revenue_yoy, 2) if revenue_yoy is not None else None,
                # 归母净利润同比增长率（%）
                "profit_yoy": round(profit_yoy, 2) if profit_yoy is not None else None,
            }
            years.append(year_data)

        # 按年份升序排列（旧→新，与 stock_metrics.json 格式一致）
        years.sort(key=lambda y: y["year"])
        return years
