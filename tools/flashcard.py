# -*- coding: utf-8 -*-
"""
单词闪卡工具
============
提供单词测验、浏览、复习功能，从本地词库读取数据。

支持的操作：
  - quiz    随机抽取单词进行测验（显示英文，用户猜中文）
  - list    列出所有单词
  - review  按难度筛选单词进行复习
  - detail  查看某个单词的详细信息

设计要点：
  - 懒加载：首次调用时才读取 JSON 词库
  - 无外部依赖：纯本地数据，不需要 API Key
"""
import os
import json
import random

from tools.base import BaseTool
from config import DATA_DIR


# 词库文件路径
FLASHCARD_WORDS_PATH = os.path.join(DATA_DIR, "flashcard_words.json")


class FlashcardTool(BaseTool):
    """
    单词闪卡工具：测验、浏览、复习单词。

    所有功能基于本地 JSON 词库，无需网络请求。
    """

    name = "flashcard"
    description = (
        "单词闪卡工具：支持随机测验、浏览单词列表、按难度复习。"
        '输入 JSON: {"action": "quiz|list|review|detail", '
        '"count": 5, "difficulty": "easy|medium|hard", "word": "serendipity"}'
    )

    def __init__(self):
        """构造时不做 IO，首次调用 run() 时才加载词库（懒加载）"""
        self._words = None    # 单词列表
        self._ready = False   # 是否已加载

    def _ensure_ready(self):
        """确保词库已加载（懒加载）"""
        if self._ready:
            return
        with open(FLASHCARD_WORDS_PATH, "r", encoding="utf-8") as f:
            self._words = json.load(f)
        self._ready = True

    def run(self, action="quiz", count=5, difficulty=None, word=None):
        """
        执行闪卡操作。

        参数
        ----
        action    : str  操作类型（quiz / list / review / detail）
        count     : int  返回的单词数量（用于 quiz 和 review）
        difficulty: str  难度筛选（easy / medium / hard），仅 review 使用
        word      : str  要查看详情的单词，仅 detail 使用

        返回
        ----
        str : 格式化的结果文本
        """
        self._ensure_ready()

        if action == "quiz":
            return self._quiz(count)
        elif action == "list":
            return self._list_words()
        elif action == "review":
            return self._review(difficulty, count)
        elif action == "detail":
            return self._detail(word)
        else:
            return f"未知操作: {action}。支持的操作: quiz, list, review, detail"

    def _quiz(self, count=5):
        """
        随机抽取单词进行测验。

        返回格式：每个单词显示英文和音标，隐藏中文翻译，
        让用户自己回忆，然后附上答案。
        """
        count = min(count, len(self._words))
        sampled = random.sample(self._words, count)

        parts = [f"=== 单词测验（共 {count} 个）===\n"]

        for i, w in enumerate(sampled, 1):
            parts.append(f"【第 {i} 题】")
            parts.append(f"  英文: {w['word']}")
            parts.append(f"  音标: {w['phonetic']}")
            parts.append(f"  （请先自己回忆中文意思，再往下看答案）")
            parts.append(f"  答案: {w['translation']}")
            parts.append(f"  例句: {w['example']}")
            parts.append(f"        {w['example_translation']}")
            parts.append("")

        parts.append("测验完成！答对几个？可以用 review 复习错题。")
        return "\n".join(parts)

    def _list_words(self):
        """列出所有单词的简要信息"""
        parts = [f"=== 词库一览（共 {len(self._words)} 个单词）===\n"]

        for i, w in enumerate(self._words, 1):
            parts.append(
                f"  {i}. {w['word']}  {w['phonetic']}  "
                f"[{w['difficulty']}]  {w['translation']}"
            )

        return "\n".join(parts)

    def _review(self, difficulty=None, count=5):
        """
        按难度筛选单词进行复习。

        参数
        ----
        difficulty : str  难度（easy/medium/hard），为 None 时不筛选
        count      : int  返回数量
        """
        if difficulty:
            filtered = [w for w in self._words if w["difficulty"] == difficulty]
            label = f"难度 [{difficulty}]"
        else:
            filtered = self._words[:]
            label = "全部难度"

        if not filtered:
            return f"未找到难度为 [{difficulty}] 的单词。"

        count = min(count, len(filtered))
        sampled = random.sample(filtered, count)

        parts = [f"=== 复习模式 · {label}（共 {count} 个）===\n"]

        for i, w in enumerate(sampled, 1):
            parts.append(f"【{i}】{w['word']}  {w['phonetic']}")
            parts.append(f"    释义: {w['translation']}")
            parts.append(f"    例句: {w['example']}")
            parts.append(f"          {w['example_translation']}")
            parts.append(f"    难度: {w['difficulty']}  标签: {', '.join(w['tags'])}")
            parts.append("")

        return "\n".join(parts)

    def _detail(self, word):
        """查看某个单词的详细信息"""
        if not word:
            return "请指定要查看的单词: {\"action\": \"detail\", \"word\": \"serendipity\"}"

        # 在词库中查找（忽略大小写）
        target = None
        for w in self._words:
            if w["word"].lower() == word.lower():
                target = w
                break

        if not target:
            return f"词库中未找到单词: {word}"

        parts = [
            f"=== 单词详情 ===",
            f"  英文: {target['word']}",
            f"  音标: {target['phonetic']}",
            f"  释义: {target['translation']}",
            f"  难度: {target['difficulty']}",
            f"  标签: {', '.join(target['tags'])}",
            f"  例句: {target['example']}",
            f"  译文: {target['example_translation']}",
        ]
        return "\n".join(parts)
