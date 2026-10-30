# -*- coding: utf-8 -*-
"""
技能优化器（Skill Optimizer）
=============================
对 skill 的 Markdown 工作流文件进行 LLM 驱动的优化，
从 token 消耗、执行效率等角度压缩提示词，并生成前后对比报告。

核心流程（手动触发）：
  1. 读取 skill 的 .md 文件（frontmatter + 正文）
  2. 计算优化前指标（字符数、估算 token、行数、规则条数等）
  3. 调用 LLM 对正文进行优化（保留语义，压缩冗余）
  4. 计算优化后指标
  5. 生成对比报告（表格 + 内容预览）
  6. 用户确认后保存优化结果

设计要点：
  - 只优化正文（body），不动 frontmatter（元数据必须保持不变）
  - token 估算：中文按 1 字 ≈ 1.5 token，英文按 4 字符 ≈ 1 token
  - 优化目标可配置：token 压缩 / 执行效率 / 两者兼顾
"""
import os
import re
import json

from skills.loader import _read_frontmatter_only, _read_body


# ==================== 指标计算 ====================

def estimate_tokens(text):
    """
    估算文本的 token 数量。

    估算规则（粗略近似）：
      - 中文字符：每个约 1.5 token
      - 英文/ASCII：每 4 个字符约 1 token
      - 混合文本按字符类型分别计算后求和

    参数
    ----
    text : str  待估算的文本

    返回
    ----
    int : 估算的 token 数
    """
    chinese_chars = 0
    ascii_chars = 0

    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            chinese_chars += 1
        else:
            ascii_chars += 1

    # 中文 1 字 ≈ 1.5 token，英文 4 字符 ≈ 1 token
    return int(chinese_chars * 1.5 + ascii_chars / 4)


def compute_metrics(text):
    """
    计算文本的各项指标。

    参数
    ----
    text : str  待分析的文本

    返回
    ----
    dict : 包含各项指标的字典
      - chars       : 总字符数
      - lines       : 总行数
      - tokens      : 估算 token 数
      - words       : 估算词数（按空格和标点分割）
      - rules       : 规则条数（以 - 开头的列表项）
      - sections    : 章节数（以 ## 开头的标题）
    """
    return {
        "chars": len(text),
        "lines": text.count("\n") + 1,
        "tokens": estimate_tokens(text),
        "words": len(re.findall(r'\S+', text)),
        "rules": len(re.findall(r'^\s*[-]\s', text, re.MULTILINE)),
        "sections": len(re.findall(r'^##\s', text, re.MULTILINE)),
    }


# ==================== 技能优化器 ====================

class SkillOptimizer:
    """
    技能优化器：读取 skill 文件 → 分析指标 → LLM 优化 → 生成对比报告。

    参数
    ----
    llm : DeepSeekClient  LLM 客户端实例
    """

    def __init__(self, llm):
        self.llm = llm

    def optimize_skill(self, skill_filepath, optimize_goal="token"):
        """
        优化一个技能文件，返回优化前后的内容和指标对比。

        参数
        ----
        skill_filepath : str  技能 .md 文件路径
        optimize_goal  : str  优化目标
                           "token"   → 优先压缩 token 消耗
                           "speed"   → 优先提升执行效率（减少推理步骤）
                           "both"    → 两者兼顾

        返回
        ----
        dict : {
            "skill_name":      技能名称,
            "original_body":   原始正文,
            "optimized_body":  优化后正文,
            "original_metrics": 原始指标,
            "optimized_metrics": 优化后指标,
            "comparison":      对比报告文本,
            "llm_analysis":    LLM 的优化说明,
        }
        """
        # ---- 1. 读取文件 ----
        if not os.path.exists(skill_filepath):
            return {"error": f"文件不存在: {skill_filepath}"}

        with open(skill_filepath, "r", encoding="utf-8") as f:
            full_content = f.read()

        # 读取 frontmatter（元数据，不优化）和 body（正文，优化目标）
        frontmatter = _read_frontmatter_only(skill_filepath)
        original_body = _read_body(skill_filepath)

        if not frontmatter.get("name"):
            return {"error": "文件缺少有效的 frontmatter"}

        skill_name = frontmatter["name"]

        # ---- 2. 计算优化前指标 ----
        original_metrics = compute_metrics(original_body)

        # ---- 3. 调用 LLM 优化正文 ----
        from core.prompts import SKILL_OPTIMIZATION_PROMPT

        goal_desc = {
            "token": "优先压缩 token 消耗：删除冗余描述、合并重复规则、"
                     "用简洁表达替代冗长句子，目标减少 40% 以上 token",
            "speed": "优先提升执行效率：精简工作流步骤、减少 Agent 需要的"
                     "推理轮次、明确工具调用参数格式，减少试错",
            "both": "同时优化 token 消耗和执行效率",
        }.get(optimize_goal, "优先压缩 token 消耗")

        prompt = SKILL_OPTIMIZATION_PROMPT.format(
            skill_name=skill_name,
            optimize_goal=goal_desc,
            original_body=original_body,
        )

        try:
            llm_response = self.llm.chat(
                [
                    {"role": "system", "content": "你是一个提示词工程师，擅长优化 Agent 技能的工作流定义。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,   # 低温度保证优化稳定
                max_tokens=2000,
            )
        except Exception as e:
            return {"error": f"LLM 调用失败: {e}"}

        # ---- 4. 解析 LLM 返回 ----
        optimized_body, llm_analysis = self._parse_optimization_response(llm_response)

        if not optimized_body:
            return {
                "error": "无法从 LLM 返回中提取优化结果",
                "raw_response": llm_response[:500],
            }

        # ---- 5. 计算优化后指标 ----
        optimized_metrics = compute_metrics(optimized_body)

        # ---- 6. 生成对比报告 ----
        comparison = self._build_comparison_report(
            skill_name, original_metrics, optimized_metrics, optimize_goal
        )

        return {
            "skill_name": skill_name,
            "filepath": skill_filepath,
            "frontmatter": frontmatter,
            "original_body": original_body,
            "optimized_body": optimized_body,
            "original_metrics": original_metrics,
            "optimized_metrics": optimized_metrics,
            "comparison": comparison,
            "llm_analysis": llm_analysis,
        }

    def save_optimized_skill(self, result, backup=True):
        """
        将优化后的技能保存回文件。

        参数
        ----
        result : dict  optimize_skill() 的返回值
        backup : bool  是否备份原始文件（保存为 .md.bak）

        返回
        ----
        str : 保存的文件路径
        """
        filepath = result["filepath"]
        frontmatter = result["frontmatter"]
        optimized_body = result["optimized_body"]

        # 备份原始文件
        if backup:
            backup_path = filepath + ".bak"
            if not os.path.exists(backup_path):
                import shutil
                shutil.copy2(filepath, backup_path)

        # 重建文件：frontmatter + 优化后的正文
        # 手动构建 frontmatter 文本
        fm_lines = ["---"]
        for key in ["name", "description", "keywords", "required_tools"]:
            if key in frontmatter:
                value = frontmatter[key]
                if isinstance(value, list):
                    value = ",".join(value)
                fm_lines.append(f"{key}: {value}")
        fm_lines.append("---")
        fm_lines.append("")

        new_content = "\n".join(fm_lines) + "\n" + optimized_body

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

        return filepath

    # ==================== 内部方法 ====================

    def _parse_optimization_response(self, response):
        """
        解析 LLM 的优化返回。

        期望格式：
          [优化说明]
          ...
          [优化结果]
          ...优化后的正文...

        返回
        ----
        (optimized_body, llm_analysis) : (str, str)
            optimized_body : 优化后的正文文本
            llm_analysis   : LLM 的优化说明
        """
        response = response.strip()

        # 尝试按标记分割
        if "[优化结果]" in response:
            parts = response.split("[优化结果]", 1)
            llm_analysis = parts[0].replace("[优化说明]", "").strip()
            optimized_body = parts[1].strip()
            return optimized_body, llm_analysis

        # 回退：尝试按 JSON 格式解析
        try:
            result = json.loads(response)
            if isinstance(result, dict):
                return result.get("optimized_body", ""), result.get("analysis", "")
        except json.JSONDecodeError:
            pass

        # 再回退：如果返回中包含 markdown 格式的正文，尝试提取
        # 找到第一个 "# " 开头的行作为正文起点
        match = re.search(r'(# .+)', response, re.DOTALL)
        if match:
            optimized_body = match.group(1).strip()
            llm_analysis = response[:match.start()].strip()
            return optimized_body, llm_analysis

        return "", ""

    @staticmethod
    def _build_comparison_report(skill_name, orig, opt, goal):
        """
        构建优化前后对比报告。

        参数
        ----
        skill_name : str   技能名称
        orig       : dict  原始指标
        opt        : dict  优化后指标
        goal       : str   优化目标

        返回
        ----
        str : 格式化的对比报告
        """
        lines = []
        lines.append(f"{'=' * 55}")
        lines.append(f"  技能优化对比报告: {skill_name}")
        lines.append(f"  优化目标: {goal}")
        lines.append(f"{'=' * 55}")
        lines.append("")

        # 指标对比表
        lines.append(f"{'指标':<12} {'优化前':>10} {'优化后':>10} {'变化':>10} {'降幅':>8}")
        lines.append("-" * 55)

        for key in ["chars", "lines", "tokens", "words", "rules", "sections"]:
            label_map = {
                "chars": "字符数",
                "lines": "行数",
                "tokens": "Token数",
                "words": "词数",
                "rules": "规则数",
                "sections": "章节数",
            }
            o_val = orig[key]
            n_val = opt[key]
            diff = n_val - o_val
            pct = f"{(diff / o_val * 100):+.1f}%" if o_val > 0 else "N/A"

            lines.append(
                f"{label_map[key]:<12} {o_val:>10} {n_val:>10} {diff:>+10} {pct:>8}"
            )

        lines.append("")
        lines.append(f"{'-' * 55}")

        # 总结
        token_reduction = orig["tokens"] - opt["tokens"]
        if token_reduction > 0:
            token_pct = token_reduction / orig["tokens"] * 100
            lines.append(
                f"  Token 节省: {token_reduction} 个 ({token_pct:.1f}%)"
            )
            lines.append(
                f"  每次对话注入提示词减少 {token_reduction} token"
            )
        else:
            lines.append(f"  Token 变化: {token_reduction:+d}（未减少）")

        lines.append("")

        return "\n".join(lines)
