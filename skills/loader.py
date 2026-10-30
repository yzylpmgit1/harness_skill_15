# -*- coding: utf-8 -*-
"""
渐进式技能加载器（Markdown 驱动 · 严格信息隔离版）
====================================================
每个技能类型对应一个 .md 工作流文件，用声明式 Markdown 定义：
  - frontmatter（--- 之间的部分）：机器可读的元数据（名称、关键词、所需工具）
  - 正文：工作流描述，直接注入 ReAct 系统提示词

三阶段渐进式加载（严格信息隔离）：

  阶段 1 — 发现（Discovery）
      逐行扫描 skills/ 目录下所有 .md 文件，【只读取 frontmatter 部分】。
      遇到第二个 --- 立即停止读取该文件，正文绝不进入内存。
      纯文本 IO，零 Python 模块导入，零正文泄露。

  阶段 2 — 路由（Route）
      LLM 语义判断或关键词匹配，【只基于 name + description】做决策。
      LLM 无法看到任何技能的工作流步骤、脚本路径或内部逻辑。

  阶段 3 — 激活（Activate）
      只有被选中的技能，才会【按需读取完整 .md 文件】提取正文。
      此时正文才首次进入内存，并缓存供后续使用。
      未被选中的技能正文永远不会被读取。

MD 文件格式示例：
    ---
    name: my_skill
    description: 技能描述
    keywords: 关键词1,关键词2,关键词3
    required_tools: tool_a,tool_b
    ---

    # 技能工作流

    ## 工作流程
    1. 步骤一
    2. 步骤二

新增技能只需：在 skills/ 目录下新建一个 .md 文件即可，无需修改任何 Python 代码。
"""
import os
import glob

# 技能文件所在目录（本文件所在目录）
SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_frontmatter_only(filepath):
    """
    只读取文件的 frontmatter 部分（--- 之间的内容）。

    【严格信息隔离】：逐行读取，遇到第二个 --- 立即停止，
    正文字节永远不会被读入内存。

    【安全保证】：如果文件缺少闭合的 ---（frontmatter 不完整），
    返回空字典，避免正文被误读为元数据。

    参数
    ----
    filepath : str  .md 文件路径

    返回
    ----
    dict : 元数据字典（name, description, keywords, required_tools）
           如果 frontmatter 不完整或不存在，返回空字典
    """
    metadata = {}
    in_frontmatter = False
    frontmatter_closed = False  # 标记是否找到了闭合的 ---
    frontmatter_lines = []

    # 底层容错：文件丢失或读取异常时返回空字典，不影响其他技能加载
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    if not in_frontmatter:
                        # 第一个 ---：进入 frontmatter 区块
                        in_frontmatter = True
                        continue
                    else:
                        # 第二个 ---：frontmatter 结束，立即停止读取
                        # 不再读取后续任何行（正文被隔离）
                        frontmatter_closed = True
                        break
                if in_frontmatter:
                    frontmatter_lines.append(line)
    except FileNotFoundError:
        print(f"  [Loader] 警告：文件不存在: {os.path.basename(filepath)}")
        return {}
    except Exception as e:
        print(f"  [Loader] 警告：读取文件失败: {os.path.basename(filepath)} - {e}")
        return {}

    # 安全检查：如果 frontmatter 未闭合，返回空字典
    # 防止正文内容被误解析为元数据（信息隔离保护）
    if in_frontmatter and not frontmatter_closed:
        print(f"  [Loader] 警告：{os.path.basename(filepath)} 的 frontmatter 缺少闭合 ---，已跳过")
        return {}

    # 文件没有 frontmatter（不以 --- 开头）
    if not in_frontmatter:
        return {}

    # 解析 frontmatter 中的每一行
    for line in frontmatter_lines:
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # keywords 和 required_tools 是逗号分隔列表
        if key in ("keywords", "required_tools"):
            metadata[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            metadata[key] = value

    return metadata


def _read_body(filepath):
    """
    按需读取文件的正文部分（frontmatter 之后的内容）。

    仅在技能被选中激活时调用，实现真正的懒加载。
    逐行读取，跳过 frontmatter 后只收集正文行。

    参数
    ----
    filepath : str  .md 文件路径

    返回
    ----
    str : 正文文本（frontmatter 之后的全部内容）
          如果文件无 frontmatter，返回整个文件内容
    """
    body_lines = []
    in_frontmatter = False
    frontmatter_passed = False  # 是否已越过 frontmatter

    # 底层容错：文件丢失或读取异常时返回空字符串，不影响其他技能加载
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not frontmatter_passed:
                    # 还在 frontmatter 区域，判断是否需要跳过
                    if stripped == "---":
                        if not in_frontmatter:
                            # 第一个 ---：进入 frontmatter
                            in_frontmatter = True
                            continue
                        else:
                            # 第二个 ---：frontmatter 结束，后续都是正文
                            frontmatter_passed = True
                            continue
                    if in_frontmatter:
                        # frontmatter 内的行，跳过
                        continue
                    # 没有 frontmatter 的文件：所有行都是正文
                    body_lines.append(line)
                else:
                    # frontmatter 之后的正文区域
                    body_lines.append(line)
    except FileNotFoundError:
        print(f"  [Loader] 警告：文件不存在: {os.path.basename(filepath)}")
        return ""
    except Exception as e:
        print(f"  [Loader] 警告：读取文件失败: {os.path.basename(filepath)} - {e}")
        return ""

    return "\n".join(body_lines).strip()


class SkillLoader:
    """
    渐进式技能加载器（Markdown 驱动 · 严格信息隔离）。

    扫描 skills/ 目录下的 .md 文件，分三阶段加载：

    阶段 1 — 发现：只读取 frontmatter，不接触正文
      每个技能定义是一个字典（不含正文）：
        {
          "name":           技能名称,
          "description":    技能描述,
          "keywords":       触发关键词列表,
          "required_tools": 所需工具名称列表,
          "file":           源文件路径,
        }

    阶段 2 — 路由：基于 name + description 做决策，正文不可见

    阶段 3 — 激活：按需读取被选中技能的正文，缓存供复用
    """

    def __init__(self, skills_dir=None):
        self.skills_dir = skills_dir or SKILLS_DIR
        # 阶段 1 — 发现：只读取 frontmatter（正文未进入内存）
        self._skills = self._discover()
        # 已激活的技能正文缓存：filepath -> body_str（只有被选中的才在这里）
        # 用文件路径做 key，避免重名技能缓存冲突
        self._activated = {}
        # 最近一次匹配结果（供 Agent 做日志输出）
        self.last_matched = []

    def _discover(self):
        """
        阶段 1 — 发现：扫描目录，只读取每个 .md 文件的 frontmatter。

        【信息隔离保证】：此方法逐行读取文件，遇到第二个 --- 立即停止，
        正文字节不会进入内存。技能字典中不包含 prompt_addon 或任何正文内容。

        【重名检测】：如果多个 .md 文件声明了相同的 name，输出警告并保留第一个。
        """
        skills = []
        seen_names = {}  # name -> filepath，用于检测重名
        pattern = os.path.join(self.skills_dir, "*.md")
        for filepath in sorted(glob.glob(pattern)):
            # 只读取 frontmatter，正文被隔离
            metadata = _read_frontmatter_only(filepath)
            if not metadata.get("name"):
                # frontmatter 不存在或不完整（_read_frontmatter_only 已输出警告）
                # 这里对完全无 frontmatter 的文件补充提示
                if not metadata:
                    print(f"  [Loader] 警告：{os.path.basename(filepath)} 无有效 frontmatter，已跳过")
                continue  # 跳过无效文件

            name = metadata["name"]

            # 重名检测：同名技能只保留第一个，输出警告
            if name in seen_names:
                print(f"  [Loader] 警告：技能名 '{name}' 重复！"
                      f"{os.path.basename(filepath)} 与 {os.path.basename(seen_names[name])} 同名，"
                      f"已跳过后者")
                continue
            seen_names[name] = filepath

            skill = {
                "name": name,
                "description": metadata.get("description", ""),
                "keywords": metadata.get("keywords", []),
                "required_tools": metadata.get("required_tools", []),
                # 注意：不保存 prompt_addon / body —— 正文未读取
                "file": filepath,
            }
            skills.append(skill)
        return skills

    def list_all(self):
        """
        返回所有已发现技能的元数据（用于展示和路由）。

        【信息隔离保证】：返回的字典中只有元数据，不包含任何正文内容。
        LLM 路由阶段使用此方法获取技能列表，无法看到工作流步骤。
        """
        return self._skills

    def match(self, query):
        """
        阶段 2 — 关键词匹配（回退方案）。

        仅基于 keywords 做字符串匹配，不读取正文。

        参数
        ----
        query : str  用户输入

        返回
        ----
        list[dict] : 匹配到的技能元数据列表（不含正文）
        """
        matched = []
        for skill in self._skills:
            # 任一关键词出现在用户输入中即视为匹配
            if any(kw in query for kw in skill["keywords"]):
                matched.append(skill)
        self.last_matched = matched
        return matched

    def activate(self, skill):
        """
        阶段 3 — 激活：按需读取技能的工作流正文。

        【真正的懒加载】：只有被选中的技能才会在此处首次读取其 .md 文件的正文。
        在此之前，正文字节从未进入内存。
        读取后缓存到 self._activated，后续激活直接取缓存。

        【缓存 key】：使用文件路径而非技能名，避免重名技能缓存冲突。

        参数
        ----
        skill : dict  技能元数据（来自 match() 或 LLM 路由的返回）

        返回
        ----
        str : 工作流正文（注入 ReAct 系统提示词）
              文件读取失败时返回空字符串
        """
        filepath = skill.get("file")
        if not filepath:
            return ""

        # 用文件路径做缓存 key（避免重名冲突）
        if filepath not in self._activated:
            # 此时才首次读取文件正文
            try:
                self._activated[filepath] = _read_body(filepath)
            except FileNotFoundError:
                print(f"  [Loader] 警告：技能文件已丢失: {os.path.basename(filepath)}")
                self._activated[filepath] = ""
            except Exception as e:
                print(f"  [Loader] 警告：读取技能文件失败: {os.path.basename(filepath)} - {e}")
                self._activated[filepath] = ""
        return self._activated[filepath]
