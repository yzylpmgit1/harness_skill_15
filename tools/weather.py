# -*- coding: utf-8 -*-
"""
城市天气查询工具
================
使用 Open-Meteo 免费 API 查询指定城市的当前天气。
Open-Meteo 无需 API Key，适合演示与教学。

工作流程：
  1. 城市名 → 经纬度（调用 Geocoding API）
  2. 经纬度 → 当前天气（调用 Forecast API）
  3. 将天气代码转换为中文描述
"""
import requests

from tools.base import BaseTool


class WeatherTool(BaseTool):
    """城市天气查询工具"""

    name = "weather"
    description = (
        '查询指定城市的实时天气（温度、湿度、风速、天气状况）。'
        '输入 JSON: {"city": "城市名（如 北京、上海）"}'
    )

    # Open-Meteo 接口地址（免费，无需 API Key）
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

    def run(self, city: str):
        """
        查询城市天气。

        参数
        ----
        city : str  城市名称（中文或英文均可）
        """
        # ---- 第 1 步：城市名 → 经纬度 ----
        try:
            geo_resp = requests.get(
                self.GEOCODE_URL,
                params={"name": city, "count": 1, "language": "zh"},
                timeout=10,
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
        except Exception as e:
            return f"地理编码请求失败: {e}"

        if not geo_data.get("results"):
            return f"未找到城市: {city}，请尝试使用中文或英文城市名。"

        loc = geo_data["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]

        # ---- 第 2 步：经纬度 → 当前天气 ----
        try:
            weather_resp = requests.get(
                self.WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,"
                               "wind_speed_10m,weather_code",
                    "timezone": "auto",
                },
                timeout=10,
            )
            weather_resp.raise_for_status()
            w = weather_resp.json().get("current", {})
        except Exception as e:
            return f"天气查询请求失败: {e}"

        # ---- 第 3 步：格式化输出 ----
        temp = w.get("temperature_2m", "N/A")
        humidity = w.get("relative_humidity_2m", "N/A")
        wind = w.get("wind_speed_10m", "N/A")
        code = w.get("weather_code", 0)
        desc = self._weather_code_to_text(code)

        region = loc.get("admin1", "")
        country = loc.get("country", "")
        location = f"{city}({region}, {country})" if region else f"{city}({country})"

        return (
            f"城市: {location}\n"
            f"天气: {desc}\n"
            f"温度: {temp}°C\n"
            f"湿度: {humidity}%\n"
            f"风速: {wind} km/h"
        )

    @staticmethod
    def _weather_code_to_text(code):
        """将 WMO 天气代码转换为中文描述"""
        mapping = {
            0: "晴", 1: "大体晴朗", 2: "局部多云", 3: "阴",
            45: "雾", 48: "雾凇",
            51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
            56: "冻毛毛雨", 57: "强冻毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨",
            66: "冻雨", 67: "强冻雨",
            71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
            80: "阵雨", 81: "中阵雨", 82: "大阵雨",
            85: "阵雪", 86: "强阵雪",
            95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
        }
        return mapping.get(code, f"未知天气(代码{code})")
