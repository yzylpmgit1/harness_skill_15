# -*- coding: utf-8 -*-
"""
技能层（Skills）— Markdown 驱动
================================
每个技能类型对应一个 .md 工作流文件，用声明式 Markdown 定义：
  - frontmatter（--- 之间）：机器可读的元数据（名称、关键词、所需工具）
  - 正文：工作流描述，注入 ReAct 系统提示词

渐进式加载三阶段：发现（扫描 MD）→ 匹配（关键词）→ 激活（注入正文）

新增技能：在 skills/ 目录下新建一个 .md 文件即可，无需修改任何 Python 代码。
"""
from skills.loader import SkillLoader

__all__ = ["SkillLoader"]
