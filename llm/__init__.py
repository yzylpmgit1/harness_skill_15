# -*- coding: utf-8 -*-
"""LLM 客户端层：封装 DeepSeek 对话模型与千问向量模型。"""
from llm.deepseek_client import DeepSeekClient
from llm.qwen_embedding import QwenEmbedding

__all__ = ["DeepSeekClient", "QwenEmbedding"]
