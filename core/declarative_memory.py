# -*- coding: utf-8 -*-
"""
声明性记忆（Declarative Memory）
================================
记录用户的兴趣爱好、习惯偏好、背景信息等长期有效的个人信息。

与工作记忆的区别：
  - 工作记忆（WorkingMemory）：短期对话上下文，滑动窗口 + 自动摘要，重启后丢失
  - 声明性记忆（DeclarativeMemory）：长期用户档案，持久化到 memory.md，重启不丢失

设计要点：
  1. 持久化：所有记忆存储在 memory/memory.md 文件中
  2. 手动触发更新：不会自动从对话中提取，需用户通过命令显式触发
  3. 结构化分区：按"兴趣爱好 / 习惯偏好 / 背景信息 / 其他备注"分类存储
  4. 上下文注入：每次对话时，将记忆内容注入系统提示词，让 Agent 参考用户偏好

支持的更新方式（均为手动触发）：
  - /remember <内容>          添加一条记忆（LLM 自动分类）
  - /remember <分类> | <内容>  指定分类添加
  - /forget <关键词>           删除包含关键词的条目
  - /refresh_memory            从近期对话中提取偏好并更新
  - /profile                   查看当前记忆
"""
import os
import re
import json

# 声明性记忆的固定分类（顺序即为展示顺序）
CATEGORIES = ["兴趣爱好", "习惯偏好", "背景信息", "其他备注"]

# memory.md 文件的头部模板（说明 + 分隔线），每次保存时自动拼接
_FILE_HEADER = """\
# 用户声明性记忆

> 此文件记录用户的兴趣爱好、习惯偏好等长期信息，由 Agent 在对话时自动读取并参考。
> 更新方式：**手动触发**（不会自动从对话中提取），请使用以下命令：
>   - `/remember <内容>`        添加一条记忆（自动分类）
>   - `/remember <分类> | <内容>` 指定分类添加记忆
>   - `/forget <关键词>`         删除包含关键词的记忆条目
>   - `/refresh_memory`          从近期对话中提取偏好并更新（手动触发）
>   - `/profile`                 查看当前声明性记忆

---
"""

# 每个分类的注释说明（HTML 注释，保存时写入文件，解析时跳过）
_CATEGORY_COMMENTS = {
    "兴趣爱好": "记录用户喜欢的事物、爱好、关注领域等",
    "习惯偏好": "记录用户的交流习惯、回答风格偏好等",
    "背景信息": "记录用户的职业、专业领域、技术背景等",
    "其他备注": "不属于以上类别的补充信息",
}


class DeclarativeMemory:
    """
    声明性记忆管理器。

    负责 memory.md 文件的读取、解析、修改和保存。
    所有写操作（add / remove / refresh）都会立即持久化到文件。

    参数
    ----
    memory_path : str
        memory.md 文件的路径（由 config.py 传入）
    """

    def __init__(self, memory_path):
        self.memory_path = memory_path
        # 记忆数据：{分类名: [条目1, 条目2, ...]}
        # 初始化为空列表，后续从文件加载
        self.data = {cat: [] for cat in CATEGORIES}
        # 从文件加载已有记忆
        self.load()

    # ==================== 文件读写 ====================

    def load(self):
        """
        从 memory.md 文件加载记忆数据。

        解析规则：
          - 按 `## 分类名` 划分区段
          - 每个区段下以 `- ` 开头的行视为一条记忆条目
          - HTML 注释 `<!-- -->` 和空行被跳过
          - `（暂无）` 等占位文本被跳过

        如果文件不存在，使用默认空数据（首次运行时自动创建）。
        """
        # 文件不存在 → 保持空数据，等 save() 时创建
        if not os.path.exists(self.memory_path):
            return

        with open(self.memory_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 按分类解析：找到每个 `## 分类名` 之后的内容
        current_category = None
        for line in content.split("\n"):
            stripped = line.strip()

            # 检查是否是分类标题（## 开头）
            if stripped.startswith("## "):
                cat_name = stripped[3:].strip()
                # 只识别预定义的分类
                if cat_name in CATEGORIES:
                    current_category = cat_name
                else:
                    current_category = None  # 未知的分类标题，跳过其内容
                continue

            # 不在任何分类下 → 跳过
            if current_category is None:
                continue

            # 跳过 HTML 注释
            if stripped.startswith("<!--"):
                continue

            # 跳过空行
            if not stripped:
                continue

            # 跳过占位文本（如"（暂无）"）
            if stripped in ("（暂无）", "(暂无)", "（无）", "(无)"):
                continue

            # 提取列表项（- 开头）
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    self.data[current_category].append(item)
            elif stripped.startswith("-"):
                # 兼容 `-内容`（无空格）的写法
                item = stripped[1:].strip()
                if item:
                    self.data[current_category].append(item)

    def save(self):
        """
        将当前记忆数据保存回 memory.md 文件。

        文件结构：
          1. 固定头部（说明文档 + 分隔线）
          2. 各分类区块（## 标题 + 注释 + 条目列表）

        如果目录不存在，自动创建。
        """
        # 确保目录存在
        dir_path = os.path.dirname(self.memory_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        lines = [_FILE_HEADER]

        # 逐个分类输出
        for cat in CATEGORIES:
            lines.append(f"## {cat}\n")
            # 写入分类注释
            comment = _CATEGORY_COMMENTS.get(cat, "")
            if comment:
                lines.append(f"<!-- {comment} -->\n")

            items = self.data.get(cat, [])
            if items:
                for item in items:
                    lines.append(f"- {item}\n")
            else:
                lines.append("（暂无）\n")
            lines.append("\n")  # 分类之间空一行

        with open(self.memory_path, "w", encoding="utf-8") as f:
            f.write("".join(lines))

    # ==================== 读取（注入用）====================

    def get_context(self):
        """
        获取格式化的记忆文本，供注入 Agent 提示词使用。

        返回格式：
          【用户档案】
          兴趣爱好: 条目1、条目2
          习惯偏好: 条目1
          ...

        如果所有分类都为空，返回空字符串（不注入）。
        """
        parts = []
        for cat in CATEGORIES:
            items = self.data.get(cat, [])
            if items:
                parts.append(f"{cat}: {'、'.join(items)}")

        if not parts:
            return ""  # 无记忆内容，不注入

        return "【用户档案】\n" + "\n".join(parts)

    def is_empty(self):
        """检查是否所有分类都为空"""
        return all(len(items) == 0 for items in self.data.values())

    # ==================== 手动更新操作 ====================

    def add(self, category, content):
        """
        向指定分类添加一条记忆。

        参数
        ----
        category : str  分类名（必须是 CATEGORIES 之一）
        content  : str  记忆内容

        返回
        ----
        bool : 是否添加成功（分类不存在时返回 False）
        """
        if category not in CATEGORIES:
            return False

        content = content.strip()
        if not content:
            return False

        # 避免重复添加完全相同的条目
        if content not in self.data[category]:
            self.data[category].append(content)
            self.save()
        return True

    def remove(self, keyword):
        """
        删除所有包含关键词的记忆条目（跨所有分类搜索）。

        参数
        ----
        keyword : str  搜索关键词，包含该词的条目会被删除

        返回
        ----
        list[str] : 被删除的条目列表（用于向用户确认删除了什么）
        """
        removed = []
        for cat in CATEGORIES:
            # 保留不包含关键词的条目
            kept = []
            for item in self.data[cat]:
                if keyword in item:
                    removed.append(f"[{cat}] {item}")
                else:
                    kept.append(item)
            self.data[cat] = kept

        if removed:
            self.save()
        return removed

    def clear_all(self):
        """清空所有记忆（慎用）"""
        self.data = {cat: [] for cat in CATEGORIES}
        self.save()

    # ==================== 展示 ====================

    def display(self):
        """
        返回格式化的记忆展示文本（供 /profile 命令输出）。

        比 get_context() 更详细，包含分类标题和逐条列表。
        """
        lines = []
        total = 0
        for cat in CATEGORIES:
            items = self.data.get(cat, [])
            total += len(items)
            lines.append(f"  【{cat}】")
            if items:
                for item in items:
                    lines.append(f"    · {item}")
            else:
                lines.append(f"    （暂无）")
            lines.append("")

        header = f"声明性记忆（共 {total} 条）"
        return header + "\n" + "\n".join(lines)

    # ==================== LLM 辅助操作 ====================

    def classify_and_add(self, content, llm):
        """
        使用 LLM 自动分类后添加一条记忆。

        流程：
          1. 把内容和可选分类交给 LLM，让它判断属于哪个分类
          2. 将内容添加到 LLM 判定的分类下
          3. 保存到文件

        参数
        ----
        content : str           记忆内容
        llm     : DeepSeekClient  LLM 客户端实例

        返回
        ----
        str : 实际归入的分类名（失败时返回 "其他备注"）
        """
        # 延迟导入，避免循环依赖
        from core.prompts import MEMORY_CLASSIFY_PROMPT

        prompt = MEMORY_CLASSIFY_PROMPT.format(
            categories="\n".join(f"- {c}" for c in CATEGORIES),
            content=content,
        )

        try:
            response = llm.chat(
                [
                    {"role": "system", "content": "你是一个信息分类助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,   # 低温度保证分类稳定
                max_tokens=20,     # 只需要分类名，限制长度省成本
            )
            # 清理 LLM 返回的空白和标点
            category = response.strip().strip("「」【】""\"'")
        except Exception:
            # LLM 调用失败 → 归入默认分类
            category = "其他备注"

        # 校验分类名是否合法
        if category not in CATEGORIES:
            # 尝试模糊匹配（LLM 可能返回 "兴趣" 而非 "兴趣爱好"）
            for cat in CATEGORIES:
                if cat in category or category in cat:
                    category = cat
                    break
            else:
                category = "其他备注"

        self.add(category, content)
        return category

    def refresh_from_conversation(self, conversation_text, llm):
        """
        使用 LLM 从近期对话中提取用户偏好，更新声明性记忆。

        流程：
          1. 把对话内容 + 已有记忆交给 LLM
          2. LLM 返回 JSON 格式的新增记忆（按分类组织）
          3. 合并到现有记忆中（去重）
          4. 保存到文件

        参数
        ----
        conversation_text : str  近期对话的文本（来自工作记忆）
        llm               : DeepSeekClient  LLM 客户端实例

        返回
        ----
        dict : 各分类新增的条目数，如 {"兴趣爱好": 2, "习惯偏好": 1}
        """
        from core.prompts import MEMORY_EXTRACTION_PROMPT

        # 构建已有记忆的文本描述
        existing = self.get_context() or "（暂无）"

        prompt = MEMORY_EXTRACTION_PROMPT.format(
            conversation=conversation_text,
            existing_memory=existing,
        )

        try:
            response = llm.chat(
                [
                    {"role": "system", "content": "你是一个用户画像提取助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
        except Exception as e:
            return {"error": f"LLM 调用失败: {e}"}

        # 解析 LLM 返回的 JSON
        extracted = self._parse_extraction_json(response)
        if extracted is None:
            return {"error": "无法解析 LLM 返回的记忆内容"}

        # 合并到现有记忆（去重）
        added_counts = {}
        for cat in CATEGORIES:
            new_items = extracted.get(cat, [])
            if not isinstance(new_items, list):
                continue
            count = 0
            for item in new_items:
                item = str(item).strip()
                if not item:
                    continue
                # 去重：已有相同条目则跳过
                if item not in self.data[cat]:
                    self.data[cat].append(item)
                    count += 1
            if count > 0:
                added_counts[cat] = count

        # 只在有新增时保存
        if added_counts:
            self.save()

        return added_counts

    @staticmethod
    def _parse_extraction_json(response):
        """
        解析 LLM 返回的记忆提取 JSON。

        LLM 可能返回：
          - 纯 JSON：{"兴趣爱好": ["..."], ...}
          - 带解释的混合内容：...提取结果如下：{"..."} ...
          - 空对象：{}

        返回
        ----
        dict : 解析出的记忆字典
        None  : 完全无法解析
        """
        response = response.strip()

        # 尝试直接解析
        try:
            result = json.loads(response)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 回退：用正则提取第一个 JSON 对象
        match = re.search(r'\{.*?\}', response, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return None
