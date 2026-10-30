# -*- coding: utf-8 -*-
"""
RAG 向量检索工具
================
使用千问向量模型 + FAISS 进行知识库检索。

工作流程：
  1. 首次调用时从 data/rag_corpus.json 读取语料
  2. 调用千问向量模型将语料批量向量化（并发加速 + 进度显示）
  3. 构建 FAISS 索引并持久化到 vectorstore/ 目录
  4. 后续调用通过语料哈希校验，直接加载已有索引，无需重复向量化
  5. 查询时：将问题向量化 → FAISS 检索 → 返回 top_k 最相关片段

关键设计 —— 懒加载索引 + 哈希校验缓存：
  - 构造时不做任何 IO 或网络请求
  - 首次 run() 时才读取语料、调用 API、构建索引
  - 缓存校验：计算语料文件内容的 MD5 哈希，与缓存哈希比对
    - 哈希一致 → 直接加载缓存（毫秒级）
    - 哈希不一致 → 重新构建索引（语料有变更）
  - 这样配合"渐进式 Skill 加载"，只有真正需要 RAG 时才产生开销
"""
import os
import json
import hashlib
import time

import numpy as np
import faiss

from tools.base import BaseTool
from llm.qwen_embedding import QwenEmbedding
from config import (
    RAG_CORPUS_PATH,
    VECTORSTORE_DIR,
    FAISS_INDEX_PATH,
    FAISS_META_PATH,
    TOP_K,
)

# 缓存哈希文件路径（记录上次构建索引时的语料哈希）
FAISS_HASH_PATH = os.path.join(VECTORSTORE_DIR, "qwen_corpus_hash.txt")


def _compute_corpus_hash():
    """计算语料文件的 MD5 哈希，用于判断语料是否有变更。"""
    hasher = hashlib.md5()
    with open(RAG_CORPUS_PATH, "rb") as f:
        # 分块读取，避免大文件占用过多内存
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


class RagSearchTool(BaseTool):
    """RAG 知识库检索工具"""

    name = "rag_search"
    description = (
        '搜索金融研报知识库，获取股票财务数据、经营分析等信息。'
        '输入 JSON: {"query": "你的搜索关键词"}'
    )

    def __init__(self):
        self.embedder = None   # 千问向量客户端（懒加载）
        self.index = None      # FAISS 索引
        self.documents = []    # 语料文档列表
        self._ready = False    # 是否已初始化

    def _ensure_ready(self):
        """确保 FAISS 索引就绪：有有效缓存则加载，无则构建。"""
        if self._ready:
            return

        if self._has_valid_cache():
            # 缓存有效，直接加载（毫秒级）
            print("  [RAG] 检测到有效缓存，直接加载索引...")
            self._load_index()
        else:
            # 缓存不存在或语料已变更，需要重新构建
            self._build_index()

        self._ready = True

    def _has_valid_cache(self):
        """
        检查缓存是否有效：
        1. 索引文件和元数据文件都存在
        2. 语料文件的 MD5 哈希与缓存记录一致（语料未变更）
        """
        if not (os.path.exists(FAISS_INDEX_PATH) and os.path.exists(FAISS_META_PATH)):
            return False
        if not os.path.exists(FAISS_HASH_PATH):
            return False
        # 比对语料哈希
        current_hash = _compute_corpus_hash()
        with open(FAISS_HASH_PATH, "r") as f:
            cached_hash = f.read().strip()
        return current_hash == cached_hash

    def _build_index(self):
        """从语料库构建 FAISS 索引（使用千问向量模型，并发加速）"""
        # ---- 第 1 步：读取语料 ----
        with open(RAG_CORPUS_PATH, "r", encoding="utf-8") as f:
            corpus = json.load(f)
        self.documents = corpus
        texts = [doc["content"] for doc in corpus]

        # ---- 第 2 步：懒加载向量客户端，批量向量化（并发 + 进度）----
        if self.embedder is None:
            self.embedder = QwenEmbedding()

        total = len(texts)
        print(f"  [RAG] 正在用千问向量模型向量化 {total} 条语料（5 线程并发）...")
        start_time = time.time()

        # 进度回调：每完成 10% 打印一次进度
        last_percent = [0]  # 用列表包装以便闭包内修改

        def on_progress(done, total):
            percent = int(done / total * 100)
            # 每完成 10% 打印一次，或全部完成时打印
            if percent >= last_percent[0] + 10 or done == total:
                last_percent[0] = percent
                elapsed = time.time() - start_time
                if done < total:
                    # 预估剩余时间
                    speed = done / elapsed if elapsed > 0 else 0
                    remaining = (total - done) / speed if speed > 0 else 0
                    print(f"  [RAG] 进度: {done}/{total} ({percent}%) "
                          f"已用 {elapsed:.0f}s，预计还需 {remaining:.0f}s")
                else:
                    print(f"  [RAG] 向量化完成: {done}/{total}，耗时 {elapsed:.1f}s")

        embeddings = self.embedder.embed(texts, progress_callback=on_progress)
        vectors = np.array(embeddings, dtype=np.float32)

        # ---- 第 3 步：构建 FAISS 索引 ----
        dim = vectors.shape[1]
        # 使用内积（Inner Product）相似度；配合 L2 归一化等价于余弦相似度
        self.index = faiss.IndexFlatIP(dim)
        faiss.normalize_L2(vectors)  # L2 归一化，使内积 = 余弦相似度
        self.index.add(vectors)

        # ---- 第 4 步：持久化保存（索引 + 元数据 + 语料哈希）----
        os.makedirs(VECTORSTORE_DIR, exist_ok=True)
        faiss.write_index(self.index, FAISS_INDEX_PATH)
        with open(FAISS_META_PATH, "w", encoding="utf-8") as f:
            json.dump(corpus, f, ensure_ascii=False, indent=2)
        # 保存语料哈希，下次启动时用于判断是否需要重建
        corpus_hash = _compute_corpus_hash()
        with open(FAISS_HASH_PATH, "w") as f:
            f.write(corpus_hash)
        print(f"  [RAG] 索引构建完成并已缓存（维度={dim}，文档数={total}）")

    def _load_index(self):
        """加载已有的 FAISS 索引和元数据"""
        self.index = faiss.read_index(FAISS_INDEX_PATH)
        with open(FAISS_META_PATH, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def run(self, query: str, top_k: int = TOP_K):
        """
        检索知识库，返回最相关的 top_k 条结果。

        参数
        ----
        query  : str  搜索关键词
        top_k  : int  返回结果数量
        """
        self._ensure_ready()

        # 懒加载向量客户端
        if self.embedder is None:
            self.embedder = QwenEmbedding()

        # 查询向量化（单条，无需并发）
        query_vec = np.array([self.embedder.embed_one(query)], dtype=np.float32)
        faiss.normalize_L2(query_vec)

        # FAISS 检索
        scores, indices = self.index.search(query_vec, top_k)

        # 组装结果
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                doc = self.documents[idx]
                results.append({
                    "content": doc["content"],
                    "score": float(score),
                    "source": doc.get("metadata", {}).get("source_file", ""),
                })

        if not results:
            return "未在知识库中找到相关内容。"

        # 格式化输出（供 Agent 作为 Observation 阅读）
        output = []
        for i, r in enumerate(results, 1):
            output.append(
                f"[结果{i}] 相似度:{r['score']:.4f}\n"
                f"来源:{r['source']}\n"
                f"内容:{r['content']}"
            )
        return "\n\n".join(output)
