# -*- coding: utf-8 -*-
"""
DeepSeek 大模型客户端
=====================
负责调用 DeepSeek 进行对话推理。
DeepSeek 兼容 OpenAI 接口格式，因此直接使用 openai SDK 即可。

关键设计 —— 懒加载（Lazy Init）：
  构造时不创建网络客户端，直到首次调用 chat() 才初始化。
  这样即使 API Key 尚未配置，也不会在实例化时报错，
  只有真正发起请求时才检查 Key 是否存在。
"""
from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE


class DeepSeekClient:
    """DeepSeek 对话客户端（懒加载）"""

    def __init__(self):
        # 标记：网络客户端尚未初始化
        self._client = None
        self.model = DEEPSEEK_MODEL

    def _ensure_client(self):
        """首次调用时创建 OpenAI 客户端"""
        if self._client is not None:
            return
        if not DEEPSEEK_API_KEY:
            raise RuntimeError(
                "未配置 DEEPSEEK_API_KEY，请在 .env 文件中设置后重试。"
            )
        # DeepSeek 兼容 OpenAI 接口，只需替换 base_url
        self._client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )

    def chat(self, messages, temperature=TEMPERATURE, stop=None, max_tokens=2048):
        """
        调用 DeepSeek 进行对话（非流式，等待完整响应后返回）。

        参数
        ----
        messages : list[dict]
            消息列表，格式为 [{"role": "system", "content": "..."}, ...]
        temperature : float
            生成温度，越高越随机
        stop : list[str] | None
            停止序列（ReAct 模式中用 ["Observation:"] 截断输出）
        max_tokens : int
            最大生成 token 数

        返回
        ----
        str : 模型生成的完整文本
        """
        self._ensure_client()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stop=stop,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def chat_stream(self, messages, temperature=TEMPERATURE, stop=None, max_tokens=2048):
        """
        调用 DeepSeek 进行流式对话（逐字返回，适合前端打字机效果）。

        与 chat() 的区别：
          - chat()    等待完整响应后一次性返回字符串
          - chat_stream() 是生成器，逐个 yield 文本片段

        参数与 chat() 完全相同，详见 chat() 的文档。

        返回
        ----
        generator : 每次 yield 一个文本片段（str）
        """
        self._ensure_client()
        # stream=True 开启流式返回，SDK 会返回一个迭代器
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stop=stop,
            max_tokens=max_tokens,
            stream=True,   # 关键参数：开启流式
        )
        # 逐个 chunk 提取文本内容并 yield
        for chunk in response:
            # 每个 chunk 包含一个 delta 对象，content 字段是文本片段
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
