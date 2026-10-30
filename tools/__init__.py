# -*- coding: utf-8 -*-
"""工具层：定义 Agent 可调用的工具基类与注册表。"""
from tools.base import BaseTool, ToolRegistry
from tools.rag_search import RagSearchTool
from tools.weather import WeatherTool
from tools.poetry_search import PoetrySearchTool
from tools.stock_analysis import StockAnalysisTool
from tools.stock_quote_tool import StockQuoteTool
from tools.flashcard import FlashcardTool
from tools.stock_batch_query import StockBatchQueryTool

__all__ = ["BaseTool", "ToolRegistry", "RagSearchTool", "WeatherTool", "PoetrySearchTool", "StockAnalysisTool", "StockQuoteTool", "FlashcardTool", "StockBatchQueryTool"]
