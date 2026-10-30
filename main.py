# -*- coding: utf-8 -*-
"""
Harness 项目入口
================
启动交互式多轮对话，集成 ReAct Agent、工作记忆、渐进式 Skill 加载。

用法：
  python main.py

命令：
  输入问题即可对话，支持多轮上下文
  输入 /help    查看帮助
  输入 /skills  查看已注册技能
  输入 /memory  查看当前工作记忆
  输入 /clear   清空工作记忆
  输入 /quit    退出
"""
import os

from config import check_api_keys, MEMORY_WINDOW, MAX_ITERATIONS, MAX_DISPATCH_WORKERS
from tools import ToolRegistry, RagSearchTool, WeatherTool, PoetrySearchTool, StockAnalysisTool, StockQuoteTool, FlashcardTool, StockBatchQueryTool
from skills import SkillLoader
from core import ReactAgent


# ========== 界面装饰 ==========

BANNER = r"""
╔══════════════════════════════════════════════════╗
║          Harness ReAct Agent  v1.0               ║
║          多轮对话 · 工具调用 · 工作记忆           ║
╚══════════════════════════════════════════════════╝
"""

HELP_TEXT = """
┌─ 使用说明 ──────────────────────────────────┐
│ 直接输入问题即可对话，示例：               │
│   · 南方航空2022年净利润是多少？            │
│   · 北京今天天气怎么样？                    │
│   · 帮我找一首描写思乡的古诗                │
│   · 有没有表达月夜孤独的诗词                │
│   · 帮我分析一下贵州茅台的走势              │
│   · 你好，介绍一下你自己                    │
│                                              │
│ 命令：                                       │
│   /help    查看帮助                         │
│   /skills  查看已注册技能                   │
│   /memory  查看工作记忆状态                 │
│   /clear   清空工作记忆                     │
│                                              │
│ 声明性记忆（手动触发更新）：                 │
│   /profile          查看用户档案             │
│   /remember <内容>  添加一条记忆（自动分类） │
│   /remember <分类> | <内容> 指定分类添加     │
│   /forget <关键词>  删除包含关键词的记忆     │
│   /refresh_memory   从近期对话提取偏好更新   │
│                                              │
│ 技能优化（手动触发，直观对比）：             │
│   /optimize_skill <名称> [token|speed|both]  │
│                     优化技能工作流并对比指标  │
│                                              │
│   /quit    退出                             │
└──────────────────────────────────────────────┘
"""


def create_agent(verbose=True):
    """创建并配置 Agent：注册工具 → 加载技能 → 初始化 Agent"""
    # 1. 注册工具（工具实例创建时不发起网络请求，懒加载）
    registry = ToolRegistry()
    registry.register(RagSearchTool())
    registry.register(WeatherTool())
    registry.register(PoetrySearchTool())
    registry.register(StockAnalysisTool())
    registry.register(StockQuoteTool())
    registry.register(StockBatchQueryTool(max_workers=MAX_DISPATCH_WORKERS, verbose=verbose))
    registry.register(FlashcardTool())

    # 2. 创建技能加载器（仅读取元数据，不导入技能模块）
    skill_loader = SkillLoader()

    # 3. 创建 Agent（注入工具注册表 + 技能加载器）
    agent = ReactAgent(
        tool_registry=registry,
        skill_loader=skill_loader,
        verbose=verbose,
    )
    return agent, skill_loader


def show_skills(skill_loader):
    """展示已注册的技能列表"""
    print("\n已注册技能（Markdown 工作流驱动）：")
    for s in skill_loader.list_all():
        fname = os.path.basename(s.get("file", ""))
        print(f"  · {s['name']}: {s['description']}")
        print(f"    工作流文件: {fname}")
        print(f"    关键词: {', '.join(s['keywords'][:8])}...")
        print(f"    工具: {', '.join(s['required_tools'])}")
    print()


def show_memory(agent):
    """展示工作记忆状态"""
    ctx = agent.memory.get_context()
    print(f"\n工作记忆窗口: {MEMORY_WINDOW} 条 | 最大推理轮次: {MAX_ITERATIONS}")
    print(f"当前记忆条数: {len(agent.memory.items)}")
    print(f"摘要长度: {len(agent.memory.summary)} 字")
    if ctx:
        print("-" * 40)
        print(ctx[:500])
    print()


# ========== 声明性记忆命令处理 ==========

def show_profile(agent):
    """展示声明性记忆（用户档案）"""
    print(agent.declarative_memory.display())


def handle_remember(agent, args):
    """
    处理 /remember 命令：添加一条声明性记忆。

    支持两种格式：
      /remember <内容>            → LLM 自动分类后添加
      /remember <分类> | <内容>    → 指定分类添加

    参数
    ----
    agent : ReactAgent
    args  : str  /remember 之后的参数文本
    """
    args = args.strip()
    if not args:
        print("用法：/remember <内容> 或 /remember <分类> | <内容>")
        print("分类可选：兴趣爱好、习惯偏好、背景信息、其他备注")
        return

    # 检查是否指定了分类（格式：分类 | 内容）
    if "|" in args:
        parts = args.split("|", 1)
        category = parts[0].strip()
        content = parts[1].strip()
        if not content:
            print("内容不能为空")
            return
        # 校验分类名
        from core.declarative_memory import CATEGORIES
        if category not in CATEGORIES:
            print(f"无效分类：{category}")
            print(f"可选分类：{', '.join(CATEGORIES)}")
            return
        # 直接添加到指定分类
        if agent.declarative_memory.add(category, content):
            print(f"已记住 [{category}]: {content}")
        else:
            print("添加失败（内容可能为空或已存在）")
    else:
        # 未指定分类 → 用 LLM 自动分类
        content = args
        print("正在分类...")
        category = agent.declarative_memory.classify_and_add(content, agent.llm)
        print(f"已记住 [{category}]: {content}")


def handle_forget(agent, args):
    """
    处理 /forget 命令：删除包含关键词的记忆条目。

    参数
    ----
    agent : ReactAgent
    args  : str  关键词
    """
    keyword = args.strip()
    if not keyword:
        print("用法：/forget <关键词>")
        print("示例：/forget 科幻  → 删除所有包含'科幻'的记忆条目")
        return

    removed = agent.declarative_memory.remove(keyword)
    if removed:
        print(f"已删除 {len(removed)} 条记忆：")
        for item in removed:
            print(f"  · {item}")
    else:
        print(f"未找到包含'{keyword}'的记忆条目")


def handle_refresh_memory(agent):
    """
    处理 /refresh_memory 命令：从近期对话中提取用户偏好，更新声明性记忆。

    流程：
      1. 从工作记忆获取近期对话文本
      2. 调用 LLM 提取用户偏好
      3. 合并到声明性记忆中（去重）
    """
    # 从工作记忆获取对话上下文
    conversation = agent.memory.get_context()
    if not conversation:
        print("近期对话为空，无法提取记忆")
        print("请先进行几轮对话，再使用 /refresh_memory 提取偏好")
        return

    print("正在从近期对话中提取用户偏好...")
    result = agent.declarative_memory.refresh_from_conversation(
        conversation, agent.llm
    )

    if "error" in result:
        print(f"提取失败：{result['error']}")
        return

    if not result:
        print("未从对话中发现新的用户偏好信息")
        return

    # 展示提取结果
    total = 0
    for cat, count in result.items():
        print(f"  [{cat}] 新增 {count} 条")
        total += count
    print(f"共新增 {total} 条记忆，已保存到 memory.md")


# ========== 技能优化命令处理 ==========

def handle_optimize_skill(agent, skill_loader, args):
    """
    处理 /optimize_skill 命令：手动触发技能工作流优化。

    流程：
      1. 查找指定技能的 .md 文件
      2. 调用 SkillOptimizer 分析并优化
      3. 展示前后对比报告
      4. 展示 LLM 的优化说明
      5. 询问用户是否保存优化结果

    参数
    ----
    agent       : ReactAgent
    skill_loader: SkillLoader
    args        : str  命令参数（技能名 + 可选优化目标）
    """
    from core.skill_optimizer import SkillOptimizer

    args = args.strip()
    if not args:
        print("用法：/optimize_skill <技能名> [token|speed|both]")
        print("示例：/optimize_skill flashcard token")
        print("      /optimize_skill flashcard speed")
        print("      /optimize_skill flashcard both")
        # 列出可用技能
        print("\n可用技能：")
        for s in skill_loader.list_all():
            print(f"  · {s['name']}: {s['description']}")
        return

    # 解析参数：技能名 + 优化目标
    parts = args.split()
    skill_name = parts[0]
    optimize_goal = parts[1] if len(parts) > 1 else "token"

    # 校验优化目标
    if optimize_goal not in ("token", "speed", "both"):
        print(f"无效的优化目标: {optimize_goal}")
        print("可选: token（压缩token）, speed（提升效率）, both（两者兼顾）")
        return

    # 查找技能文件
    target_skill = None
    for s in skill_loader.list_all():
        if s["name"] == skill_name:
            target_skill = s
            break

    if not target_skill:
        print(f"未找到技能: {skill_name}")
        print("可用技能：")
        for s in skill_loader.list_all():
            print(f"  · {s['name']}")
        return

    filepath = target_skill["file"]
    print(f"正在优化技能 [{skill_name}]，优化目标: {optimize_goal}")
    print(f"文件: {os.path.basename(filepath)}")
    print("-" * 55)

    # 执行优化
    optimizer = SkillOptimizer(agent.llm)
    result = optimizer.optimize_skill(filepath, optimize_goal)

    if "error" in result:
        print(f"优化失败: {result['error']}")
        if "raw_response" in result:
            print(f"LLM 原始返回: {result['raw_response']}")
        return

    # 展示对比报告
    print(result["comparison"])

    # 展示 LLM 的优化说明
    if result.get("llm_analysis"):
        print("LLM 优化说明:")
        print("-" * 55)
        print(result["llm_analysis"])
        print()

    # 展示优化前后正文预览（各前 15 行）
    print("=" * 55)
    print("优化前正文预览（前 15 行）:")
    print("-" * 55)
    orig_lines = result["original_body"].split("\n")[:15]
    for line in orig_lines:
        print(f"  {line}")
    print()

    print("优化后正文预览（前 15 行）:")
    print("-" * 55)
    opt_lines = result["optimized_body"].split("\n")[:15]
    for line in opt_lines:
        print(f"  {line}")
    print()

    # 询问是否保存
    print("=" * 55)
    print("是否保存优化结果？（原始文件将备份为 .md.bak）")
    print("  输入 y 保存   输入其他取消")
    try:
        choice = input("选择: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "n"

    if choice == "y":
        saved_path = optimizer.save_optimized_skill(result, backup=True)
        print(f"\n已保存优化结果到: {os.path.basename(saved_path)}")
        print(f"原始文件已备份: {os.path.basename(saved_path)}.bak")
        print("注意：需要重启程序才能加载优化后的技能")
    else:
        print("\n已取消保存，优化结果仅作预览")


def main():
    """主循环：交互式多轮对话"""
    print(BANNER)

    # 检查 API Key 配置
    missing = check_api_keys()
    if missing:
        print("⚠️  以下 API Key 尚未配置：")
        for k in missing:
            print(f"   · {k}")
        print("   请复制 .env.example 为 .env 并填入真实 Key 后重试。")
        print("   （天气查询工具无需 API Key，但仍需 DeepSeek 进行对话）\n")

    print(f"配置：工作记忆窗口={MEMORY_WINDOW} | 最大推理轮次={MAX_ITERATIONS}")
    print(HELP_TEXT)

    # 创建 Agent
    agent, skill_loader = create_agent(verbose=True)

    # 交互循环
    while True:
        try:
            user_input = input("🧑 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input == "/quit":
            print("再见！")
            break
        elif user_input == "/help":
            print(HELP_TEXT)
            continue
        elif user_input == "/skills":
            show_skills(skill_loader)
            continue
        elif user_input == "/memory":
            show_memory(agent)
            continue
        elif user_input == "/clear":
            agent.memory.clear()
            print("工作记忆已清空\n")
            continue
        elif user_input == "/profile":
            show_profile(agent)
            continue
        elif user_input.startswith("/remember"):
            # /remember 命令：添加声明性记忆
            # 提取 /remember 之后的参数
            args = user_input[len("/remember"):]
            handle_remember(agent, args)
            continue
        elif user_input.startswith("/forget"):
            # /forget 命令：删除声明性记忆条目
            args = user_input[len("/forget"):]
            handle_forget(agent, args)
            continue
        elif user_input == "/refresh_memory":
            # /refresh_memory 命令：从对话中提取偏好更新记忆
            handle_refresh_memory(agent)
            continue
        elif user_input.startswith("/optimize_skill"):
            # /optimize_skill 命令：手动触发技能优化
            args = user_input[len("/optimize_skill"):]
            handle_optimize_skill(agent, skill_loader, args)
            continue

        # 正常对话
        print("🤖 助手: ")
        try:
            answer = agent.chat(user_input)
            print(f"\n{answer}\n")
        except Exception as e:
            print(f"\n❌ 出错了: {e}\n")


if __name__ == "__main__":
    main()
