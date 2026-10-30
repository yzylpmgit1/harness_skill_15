# -*- coding: utf-8 -*-
"""
iFinD 数据适配器
================
将 iFinD（同花顺金融数据）接口返回的 Markdown 表格文本，
解析为 stock_analysis 工具所需的统一数据结构。

工作原理：
  1. iFinD 接口返回 JSON，其中 data.answer 是一段 Markdown 表格文本
  2. 本模块解析该表格，提取表头与数据行，建立 "列名 → 值" 映射
  3. 将映射后的指标值转换为 stock_analysis 所需的字段名和单位

指标名称映射关系（iFinD 列名 → 内部字段名）：
  ┌──────────────────────────────────┬──────────────────┐
  │ iFinD 列名                        │ 内部字段名        │
  ├──────────────────────────────────┼──────────────────┤
  │ 销售毛利率（单位：%）               │ gross_margin     │
  │ 销售净利率（单位：%）               │ net_margin       │
  │ 净资产收益率ROE（单位：%）          │ roe              │
  │ 资产负债率（单位：%）               │ debt_ratio       │
  │ 营业收入(同比增长率)（单位：%）     │ revenue_yoy      │
  │ 归属母公司股东的净利润(同比增长率)  │ profit_yoy       │
  │ 营业收入（单位：元）                │ revenue_yi       │
  │ 归属于母公司所有者的净利润（单位:元）│ net_profit_yi    │
  └──────────────────────────────────┴──────────────────┘

使用示例：
  from tools.ifind_adapter import IFindAdapter

  adapter = IFindAdapter()
  # 解析 iFinD 返回的 Markdown 表格
  parsed = adapter.parse_table(markdown_text)
  # 构建单年份数据
  year_data = adapter.build_year_data(parsed, "2023")
  # 构建完整股票数据
  stock_data = adapter.build_stock_data(
      name="腾讯控股", code="00700", market="HK",
      year_results=[year_2023, year_2022, year_2021],
      info_result=info_parsed,
  )
"""
import os
import json
import re


class IFindAdapter:
    """
    iFinD 数据适配器：解析 iFinD 返回的 Markdown 表格，
    转换为 stock_analysis 工具所需的统一数据结构。
    """

    # ============================================================
    # iFinD 列名 → 内部字段名的映射表
    # ============================================================
    # 财务指标映射（iFinD 表头列名 → 内部字段名）
    # 注意：iFinD 的列名包含单位说明，需要做模糊匹配
    FINANCIAL_COLUMN_MAP = {
        # 毛利率
        "销售毛利率": "gross_margin",
        # 净利率
        "销售净利率": "net_margin",
        # ROE
        "净资产收益率": "roe",
        # 资产负债率
        "资产负债率": "debt_ratio",
        # 营收同比增长率
        "营业收入(同比增长率)": "revenue_yoy",
        "营业收入(同比增长率": "revenue_yoy",  # 兼容括号不匹配的情况
        # 归母净利润同比增长率（比"净利润同比增长率"更准确）
        "归属母公司股东的净利润(同比增长率)": "profit_yoy",
        "归属母公司股东的净利润(同比增长率": "profit_yoy",
        # 营业收入（单位：元，值带"亿"字）
        "营业收入": "revenue_yi",
        # 归母净利润（单位：元，值带"亿"字）
        "归属于母公司所有者的净利润": "net_profit_yi",
    }

    # 基本信息映射
    INFO_COLUMN_MAP = {
        "所属新证监会行业": "industry",
        "所属申万行业": "industry",
        "主营业务": "description",
    }

    def parse_table(self, text):
        """
        解析 iFinD 返回的 Markdown 表格文本，返回 "列名 → 值" 字典。

        iFinD 表格格式：
            |证券代码|证券简称|日期|指标1|指标2|...|
            |---|---|---|---|---|...|
            |600519.SH|贵州茅台|20231231|91.96|36.18|...|

        参数
        ----
        text : str  iFinD 返回的原始文本（data.answer 字段内容）

        返回
        ----
        dict : {列名: 值} 的字典
        """
        if not text:
            return {}

        lines = text.strip().split("\n")
        header = None       # 表头列表
        data_values = None  # 数据值列表

        for line in lines:
            line = line.strip()
            # 只处理以 | 开头的行（表格行）
            if not line.startswith("|"):
                continue
            # 跳过分隔符行（|---|---|...）
            if re.match(r"^\|[-\s|]+\|$", line):
                continue
            # 分割单元格（去掉首尾的空 |）
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # 第一个非分隔符行是表头
            if header is None:
                header = cells
            else:
                # 第二个非分隔符行是数据
                data_values = cells
                break

        if not header or not data_values:
            return {}

        return dict(zip(header, data_values))

    def parse_ifind_response(self, response_text):
        """
        解析 iFinD MCP 工具返回的完整 JSON 响应文本。

        iFinD MCP 返回格式：
            [{"type": "text", "text": "{\"code\":1,...,\"data\":{\"answer\":\"...\"}}"}]

        本方法提取其中的 data.answer（Markdown 表格），再调用 parse_table。

        参数
        ----
        response_text : str  MCP 工具返回的原始文本

        返回
        ----
        dict : 解析后的 "列名 → 值" 字典
        """
        try:
            # MCP 返回的是 JSON 数组，取第一个元素的 text 字段
            outer = json.loads(response_text)
            if isinstance(outer, list) and len(outer) > 0:
                outer = outer[0]
            # 外层 text 是 JSON 字符串
            inner_text = outer.get("text", "") if isinstance(outer, dict) else ""
            inner = json.loads(inner_text)
            # 提取 data.answer
            answer = inner.get("data", {}).get("answer", "")
            return self.parse_table(answer)
        except (json.JSONDecodeError, KeyError, TypeError):
            # 如果 JSON 解析失败，尝试直接当作 Markdown 表格解析
            return self.parse_table(response_text)

    def _find_column(self, parsed, target_key):
        """
        在解析结果中查找匹配的列值。
        使用模糊匹配：列名包含 target_key 的关键部分即视为匹配。

        参数
        ----
        parsed  : dict  parse_table 返回的字典
        key     : str   FINANCIAL_COLUMN_MAP 中的 key

        返回
        ----
        str or None : 匹配到的值
        """
        for col_name, value in parsed.items():
            # 去掉列名中的单位说明（括号内内容），只比较核心名称
            col_core = re.sub(r"（.*?）", "", col_name).strip()
            if col_core == target_key or target_key in col_name:
                return value
        return None

    def _parse_percentage(self, val):
        """
        解析百分比值。
        iFinD 返回的百分比已经是数值（如 "91.9649"），无需额外处理。

        参数
        ----
        val : str  原始值字符串

        返回
        ----
        float or None : 解析后的浮点数
        """
        if not val or val in ("--", "null", "None", ""):
            return None
        # 去除可能的百分号和空白
        val = val.replace("%", "").replace(" ", "").strip()
        try:
            return float(val)
        except ValueError:
            return None

    def _parse_yi(self, val):
        """
        解析金额值，统一转换为"亿元"单位。

        iFinD 返回的营业收入/净利润值格式可能为：
          - "1476.936亿" → 1476.936
          - "14769360000" → 147.6936（纯数字，单位为元，需除以 1e8）
          - "--" → None

        参数
        ----
        val : str  原始值字符串

        返回
        ----
        float or None : 以"亿元"为单位的浮点数
        """
        if not val or val in ("--", "null", "None", ""):
            return None
        val = val.strip()
        # 情况 1：值带"亿"字 → 直接去掉"亿"取数值
        if "亿" in val:
            num_str = val.replace("亿", "").strip()
            try:
                return float(num_str)
            except ValueError:
                return None
        # 情况 2：纯数字 → 判断量级，可能是"元"需要转换
        try:
            num = float(val.replace(",", ""))
            # 如果数值很大（>1亿），说明单位是"元"，转换为"亿元"
            if num > 1e8:
                return round(num / 1e8, 4)
            # 否则假设已经是"亿元"
            return num
        except ValueError:
            return None

    def build_year_data(self, parsed, year):
        """
        从解析后的字典构建单年份的财务数据结构。

        参数
        ----
        parsed : dict  parse_table 返回的 "列名 → 值" 字典
        year   : str   年份（如 "2023"）

        返回
        ----
        dict : 单年份财务数据，格式与 stock_metrics.json 一致
        """
        return {
            "year": year,
            # 营业收入（亿元）
            "revenue_yi": self._parse_yi(
                self._find_column(parsed, "营业收入")
            ),
            # 归母净利润（亿元）
            "net_profit_yi": self._parse_yi(
                self._find_column(parsed, "归属于母公司所有者的净利润")
            ),
            # 毛利率（%）
            "gross_margin": self._parse_percentage(
                self._find_column(parsed, "销售毛利率")
            ),
            # 净利率（%）
            "net_margin": self._parse_percentage(
                self._find_column(parsed, "销售净利率")
            ),
            # ROE（%）
            "roe": self._parse_percentage(
                self._find_column(parsed, "净资产收益率")
            ),
            # 资产负债率（%）
            "debt_ratio": self._parse_percentage(
                self._find_column(parsed, "资产负债率")
            ),
            # 营收同比增长率（%）
            "revenue_yoy": self._parse_percentage(
                self._find_column(parsed, "营业收入(同比增长率)")
            ),
            # 归母净利润同比增长率（%）
            "profit_yoy": self._parse_percentage(
                self._find_column(parsed, "归属母公司股东的净利润(同比增长率)")
            ),
        }

    def build_stock_data(self, name, code, market, year_results, info_result=None):
        """
        组装完整的股票数据结构，格式与 stock_metrics.json 一致。

        参数
        ----
        name         : str           股票名称
        code         : str           股票代码（如 "600519"）
        market       : str           市场标识（"SH" / "SZ" / "HK" 等）
        year_results : list[dict]    各年份的财务数据（build_year_data 的返回值列表）
        info_result  : dict, 可选     基本信息解析结果（parse_table 的返回值）

        返回
        ----
        dict : 完整的股票数据结构
        """
        # 从基本信息中提取行业和描述
        industry = "未知"
        description = ""
        if info_result:
            # 尝试匹配行业字段
            for key in ("所属新证监会行业", "所属申万行业", "所属行业"):
                if key in info_result:
                    industry = info_result[key]
                    break
            # 提取主营业务描述
            if "主营业务" in info_result:
                description = info_result["主营业务"]

        # 按年份升序排列（最旧年份在前，与 stock_metrics.json 格式一致）
        # 分析代码中用 years[-1] 取最新年份，years[0] 取最旧年份
        sorted_years = sorted(year_results, key=lambda y: y["year"])

        stock_data = {
            "code": code,
            "name": name,
            "market": market,
            "industry": industry,
            "description": description,
            "years": sorted_years,
            "data_source": "iFinD实时获取",  # 标记数据来源
        }
        return stock_data

    def save_to_cache(self, stock_data, cache_dir):
        """
        将股票数据保存到本地缓存文件，避免重复调用 iFinD。

        缓存文件路径：{cache_dir}/{code}.json

        参数
        ----
        stock_data : dict  完整的股票数据结构
        cache_dir  : str   缓存目录路径
        """
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{stock_data['code']}.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(stock_data, f, ensure_ascii=False, indent=2)
        return cache_path

    def load_from_cache(self, code, cache_dir):
        """
        从本地缓存加载股票数据。

        参数
        ----
        code      : str  股票代码
        cache_dir : str  缓存目录路径

        返回
        ----
        dict or None : 缓存的股票数据，未找到则返回 None
        """
        cache_path = os.path.join(cache_dir, f"{code}.json")
        if not os.path.exists(cache_path):
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
