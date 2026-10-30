# -*- coding: utf-8 -*-
"""
古诗词搜索工具
==============
根据用户描述的场景、情感或意境，从诗词语料库中检索匹配的古诗词。

工作流程：
  1. 首次调用时从 data/poetry_corpus.json 读取语料（懒加载）
  2. 对用户描述进行多维度标签匹配（主题、情感、场景、关键词）
  3. 按匹配分数排序，返回 top_k 首最相关的诗词

匹配算法 —— 双向标签匹配 + 加权评分：
  - 正向匹配：检查诗词的每个标签是否出现在用户查询中
    例如：标签"思乡"出现在查询"我想找一首思乡的诗"中 → 命中
  - 反向匹配：提取查询中的 2 字片段，检查是否命中诗词标签
    例如：查询中的"月光"命中了某诗的 keywords → 命中
  - 加权评分：不同标签类别权重不同
    主题(themes)    权重 3  ← 最重要，直接反映诗词核心内容
    情感(emotions)  权重 3  ← 重要，用户常按情感搜索
    场景(scenes)    权重 2  ← 中等重要，如"月夜""春天"
    关键词(keywords) 权重 2  ← 中等重要，包含原文词汇和联想词
  - 额外加分：查询中的词出现在诗词原文中，每命中一个 +1 分
"""
import os
import json

from tools.base import BaseTool
from config import POETRY_CORPUS_PATH


class PoetrySearchTool(BaseTool):
    """古诗词搜索工具：根据用户描述检索匹配的古诗词"""

    name = "poetry_search"
    description = (
        '根据用户描述的场景、情感或意境，搜索匹配的古诗词。'
        '输入 JSON: {"query": "描述内容（如：思乡 月夜 孤独）", "top_k": 5}'
    )

    # 标签类别及其匹配权重（数值越大越重要）
    TAG_WEIGHTS = {
        "themes": 3,   # 主题标签（思乡、离别、山水等）—— 最核心
        "emotions": 3, # 情感标签（思念、忧伤、豪迈等）—— 用户常按情感搜索
        "scenes": 2,   # 场景标签（月夜、春天、边塞等）—— 描述性搜索
        "keywords": 2, # 关键词标签（原文词汇 + 联想词）—— 补充匹配
    }

    def __init__(self):
        """构造时不做任何 IO，首次调用 run() 时才加载语料（懒加载）"""
        self._corpus = None    # 诗词语料列表
        self._ready = False    # 是否已加载

    def _ensure_ready(self):
        """确保语料库已加载（懒加载模式，避免启动时读取文件）"""
        if self._ready:
            return
        with open(POETRY_CORPUS_PATH, "r", encoding="utf-8") as f:
            self._corpus = json.load(f)
        self._ready = True

    def run(self, query: str, top_k: int = 5):
        """
        搜索匹配的古诗词。

        参数
        ----
        query  : str  用户描述（场景、情感、意境等，如"思乡 月夜 孤独"）
        top_k  : int  返回结果数量（默认 5 首）

        返回
        ----
        str : 格式化的诗词搜索结果，供 Agent 作为 Observation 阅读
        """
        self._ensure_ready()

        # ---- 第 1 步：对每首诗计算匹配分数 ----
        scored_poems = []
        for poem in self._corpus:
            score, matched_tags = self._compute_score(query, poem)
            if score > 0:
                scored_poems.append((score, matched_tags, poem))

        # ---- 第 2 步：按分数降序排序 ----
        scored_poems.sort(key=lambda x: x[0], reverse=True)

        # ---- 第 3 步：取 top_k 首并格式化输出 ----
        top_results = scored_poems[:top_k]

        if not top_results:
            return (
                "未找到匹配的诗词。建议尝试用以下方式描述：\n"
                "1. 直接说出情感（如：思乡、离别、忧伤、豪迈）\n"
                "2. 描述场景（如：月夜、春天、边塞、山水）\n"
                "3. 使用诗词中的意象（如：明月、梅花、秋风）"
            )

        # 格式化每首诗的输出
        output_parts = [f"共找到 {len(scored_poems)} 首相关诗词，展示前 {len(top_results)} 首：\n"]
        for i, (score, matched_tags, poem) in enumerate(top_results, 1):
            output_parts.append(self._format_poem(i, score, matched_tags, poem))

        return "\n\n".join(output_parts)

    def _compute_score(self, query, poem):
        """
        计算查询与单首诗的匹配分数（双向标签匹配 + 内容匹配）。

        参数
        ----
        query : str       用户查询文本
        poem  : dict      单首诗的语料数据

        返回
        ----
        (score, matched_tags) : (float, list[str])
            score        : 总匹配分数
            matched_tags : 命中的标签列表（用于展示匹配原因）
        """
        score = 0.0
        matched_tags = []

        # ---- 正向匹配：检查诗词标签是否出现在查询中 ----
        for field, weight in self.TAG_WEIGHTS.items():
            for tag in poem.get(field, []):
                if tag in query:
                    score += weight
                    matched_tags.append(tag)

        # ---- 反向匹配：提取查询中的 2 字片段，检查是否命中标签 ----
        # 遍历查询中所有相邻的 2 个字，看是否匹配某个标签
        all_tags = (
            poem.get("themes", [])
            + poem.get("emotions", [])
            + poem.get("scenes", [])
            + poem.get("keywords", [])
        )
        for i in range(len(query) - 1):
            substr = query[i: i + 2]
            # 如果这个 2 字片段命中了某个标签，且之前未记录
            if substr in all_tags and substr not in matched_tags:
                score += 1  # 反向匹配权重较低（避免重复加分）
                matched_tags.append(substr)

        # ---- 内容匹配：查询中的词出现在诗词原文中，额外加分 ----
        content = poem.get("content", "")
        for i in range(len(query) - 1):
            substr = query[i: i + 2]
            if substr in content and substr not in matched_tags:
                score += 0.5  # 内容匹配权重最低
                # 不加入 matched_tags（避免列表过长）

        return score, matched_tags

    def _format_poem(self, index, score, matched_tags, poem):
        """将单首诗格式化为可读文本"""
        lines = [
            f"━━━ [{index}] {poem['title']} ━━━",
            f"朝代: {poem['dynasty']}  作者: {poem['author']}  体裁: {poem['type']}",
            f"匹配度: {score:.1f}  命中标签: {', '.join(matched_tags) if matched_tags else '无'}",
            f"",
            f"原文:",
            poem["content"],
            f"",
            f"译文: {poem['translation']}",
            f"赏析: {poem['appreciation']}",
        ]

        # 附加标签信息（帮助 Agent 理解匹配原因）
        tag_info = []
        if poem.get("themes"):
            tag_info.append(f"主题: {'/'.join(poem['themes'])}")
        if poem.get("emotions"):
            tag_info.append(f"情感: {'/'.join(poem['emotions'])}")
        if poem.get("scenes"):
            tag_info.append(f"场景: {'/'.join(poem['scenes'])}")
        if tag_info:
            lines.append("  | ".join(tag_info))

        return "\n".join(lines)
