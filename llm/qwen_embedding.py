# -*- coding: utf-8 -*-
"""
千问向量模型客户端
==================
负责调用千问（通义千问 / DashScope）的 Embedding 接口，
将文本转换为向量，供 RAG 检索使用。

千问提供了 OpenAI 兼容接口，因此同样使用 openai SDK，
只需将 base_url 指向 DashScope 兼容端点即可。

关键设计 —— 懒加载 + 批量处理 + 并发加速：
  - 网络客户端懒加载，首次调用才初始化
  - embed() 支持批量传入多条文本，减少 API 调用次数
  - 大规模向量化时使用线程池并发请求，大幅加速（10K 语料从 30 分钟降至数分钟）
  - 支持进度回调，让调用方显示向量化进度
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_EMBEDDING_MODEL


class QwenEmbedding:
    """千问向量模型客户端（懒加载 + 并发加速）"""

    # 每次请求最大文本条数
    # 千问 text-embedding-v3 接口限制：单次请求不超过 10 条文本，
    # 超过会报 400 InternalError.Algo.InvalidParameter:
    #   batch size is invalid, it should not be larger than 10
    BATCH_SIZE = 10

    # 并发线程数（同时发送多个批次请求，加速大规模向量化）
    # 设置为 5 是兼顾速度和 API 限流的安全值
    MAX_WORKERS = 5

    def __init__(self):
        self._client = None
        self.model = QWEN_EMBEDDING_MODEL

    def _ensure_client(self):
        """首次调用时创建 OpenAI 客户端"""
        if self._client is not None:
            return
        if not QWEN_API_KEY:
            raise RuntimeError(
                "未配置 QWEN_API_KEY，请在 .env 文件中设置后重试。"
            )
        self._client = OpenAI(
            api_key=QWEN_API_KEY,
            base_url=QWEN_BASE_URL,
        )

    def _embed_batch(self, batch):
        """向量化单个批次（内部方法，供线程池调用）。

        每个线程独立创建 OpenAI 客户端，避免线程安全问题。
        """
        # 线程内创建独立客户端（openai SDK 的客户端不是线程安全的）
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        resp = client.embeddings.create(
            model=self.model,
            input=batch,
        )
        # 按 index 排序确保顺序正确
        return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]

    def embed(self, texts, progress_callback=None):
        """
        批量文本向量化（支持并发加速 + 进度回调）。

        参数
        ----
        texts             : str | list[str]
            单条文本或文本列表
        progress_callback : callable(done, total) | None
            进度回调函数，每完成一个批次调用一次。
            done : 已完成的文本数
            total: 总文本数

        返回
        ----
        list[list[float]] : 向量列表（每条文本对应一个向量，顺序与输入一致）
        """
        self._ensure_client()

        # 统一转为列表处理
        single = isinstance(texts, str)
        if single:
            texts = [texts]

        total = len(texts)
        # 只有一条文本时直接调用（查询场景），无需并发
        if total <= self.BATCH_SIZE:
            return self._embed_batch(texts)

        # ---- 大规模向量化：分批 + 并发请求 ----
        # 将文本切分为多个批次
        batches = []
        for i in range(0, total, self.BATCH_SIZE):
            batches.append((i, texts[i: i + self.BATCH_SIZE]))

        # 预分配结果数组（按原始索引存放，保证顺序正确）
        all_vectors = [None] * total
        done_count = 0

        # 使用线程池并发处理批次
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            # 提交所有批次任务
            future_to_batch = {
                executor.submit(self._embed_batch, batch): (start_idx, batch)
                for start_idx, batch in batches
            }
            # 按完成顺序收集结果
            for future in as_completed(future_to_batch):
                start_idx, batch = future_to_batch[future]
                vectors = future.result()
                # 将结果放回正确的位置
                for j, vec in enumerate(vectors):
                    all_vectors[start_idx + j] = vec
                # 更新进度
                done_count += len(batch)
                if progress_callback:
                    progress_callback(done_count, total)

        return all_vectors

    def embed_one(self, text):
        """单条文本向量化，返回单个向量（list[float]）。"""
        return self.embed(text)[0]
