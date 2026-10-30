# -*- coding: utf-8 -*-
"""
Harness Web 界面后端
====================
基于 Flask 的 API 服务器，为赛博朋克风格前端提供数据接口。

API 列表：
  GET  /api/memory                    获取声明性记忆内容
  POST /api/memory/remember           添加记忆
  POST /api/memory/forget             删除记忆
  POST /api/memory/refresh            从对话提取偏好
  GET  /api/skills                    获取所有技能列表
  GET  /api/skill/<name>/body         获取技能正文
  POST /api/skill/<name>/optimize     优化技能
  GET  /api/skill/<name>/backup       获取优化前备份
  POST /api/chat                      对话接口（ReAct Agent 多轮对话）
  POST /api/chat/clear                清空对话记忆

启动方式：
  python web/server.py
  然后浏览器访问 http://localhost:5000
"""
import os
import sys
import io
import re
import json
from contextlib import redirect_stdout

# 将项目根目录加入 Python 路径，使 web/ 子目录也能导入项目模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, request, jsonify, render_template, Response, stream_with_context

from core.declarative_memory import DeclarativeMemory, CATEGORIES
from core.skill_optimizer import SkillOptimizer, compute_metrics, estimate_tokens
from skills.loader import SkillLoader, _read_frontmatter_only, _read_body
from llm.deepseek_client import DeepSeekClient
from config import DECLARATIVE_MEMORY_PATH, MAX_DISPATCH_WORKERS

# 延迟导入 Agent 相关模块（避免启动时就初始化 LLM 连接）
from tools import ToolRegistry, RagSearchTool, WeatherTool, PoetrySearchTool, StockAnalysisTool, StockQuoteTool, FlashcardTool, StockBatchQueryTool
from skills import SkillLoader as _SkillLoaderClass
from core import ReactAgent

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# ==================== 全局实例（懒加载）====================

_llm_client = None
_skill_loader = None
_declarative_memory = None
_agent = None       # ReAct Agent 实例（保持多轮对话状态）


def get_llm():
    """获取 LLM 客户端实例（懒加载）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = DeepSeekClient()
    return _llm_client


def get_agent():
    """
    获取全局 ReactAgent 实例（懒加载）。

    Agent 内部持有工作记忆（滑动窗口 + 摘要），因此必须用全局单例，
    不能每次请求都创建新的，否则多轮对话上下文会丢失。
    """
    global _agent
    if _agent is None:
        # 1. 注册工具
        registry = ToolRegistry()
        registry.register(RagSearchTool())
        registry.register(WeatherTool())
        registry.register(PoetrySearchTool())
        registry.register(StockAnalysisTool())
        registry.register(StockQuoteTool())
        registry.register(StockBatchQueryTool(max_workers=MAX_DISPATCH_WORKERS, verbose=True))
        registry.register(FlashcardTool())

        # 2. 加载技能
        skill_loader = _SkillLoaderClass()

        # 3. 创建 Agent（开启 verbose 以便捕获推理过程）
        _agent = ReactAgent(
            tool_registry=registry,
            skill_loader=skill_loader,
            verbose=True,
        )
    return _agent


def parse_react_trace(raw_output):
    """
    从 Agent 的 stdout 捕获中解析 ReAct 推理过程。

    Agent verbose 模式会 print 如下格式的日志：
      [Skill] 已加载技能(llm): poetry_search
      [Thought] ...
      [Action] tool_name | Input: {...}
      [Observation] ...
      [Final Answer] ...

    本函数将其解析为结构化的步骤列表，供前端展示。

    参数
    ----
    raw_output : str  redirect_stdout 捕获的完整输出

    返回
    ----
    list[dict] : 推理步骤列表，每步含 type/text 字段
    """
    steps = []
    lines = raw_output.strip().split("\n")
    current_step = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 匹配 [Skill] / [Thought] / [Action] / [Observation] / [Final Answer]
        match = re.match(r"\[(Skill|Thought|Action|Observation|Final Answer)\]\s*(.*)", line)
        if match:
            tag = match.group(1)
            content = match.group(2)

            # 将 tag 映射为前端可用的类型
            type_map = {
                "Skill": "skill",
                "Thought": "thought",
                "Action": "action",
                "Observation": "observation",
                "Final Answer": "final",
            }
            step_type = type_map.get(tag, tag.lower())

            current_step = {"type": step_type, "text": content}
            steps.append(current_step)
        else:
            # 多行内容的续行
            if current_step:
                current_step["text"] += "\n" + line

    return steps


def get_skill_loader():
    """获取技能加载器实例（懒加载）"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader


def get_declarative_memory():
    """获取声明性记忆实例（每次重新加载文件，保证数据最新）"""
    return DeclarativeMemory(DECLARATIVE_MEMORY_PATH)


def _invalidate_skill_cache(filepath):
    """
    清除技能正文缓存，使文件修改后立即生效。

    需要清除两处缓存：
      1. Agent 内部的 SkillLoader._activated（对话用，activate() 的懒加载缓存）
      2. 全局 _skill_loader 的 _activated（API 展示用，虽然 get_skills() 每次重新
         读文件，但 activate() 仍有缓存，保险起见一并清除）

    参数
    ----
    filepath : str  被修改的技能文件路径
    """
    # 1. 清除 Agent 内部的技能缓存
    if _agent is not None and _agent.skills is not None:
        _agent.skills._activated.pop(filepath, None)

    # 2. 清除 API 展示用的技能加载器缓存
    if _skill_loader is not None:
        _skill_loader._activated.pop(filepath, None)


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """渲染主页面"""
    return render_template("index.html")


# ==================== 声明性记忆 API ====================

@app.route("/api/memory", methods=["GET"])
def get_memory():
    """
    获取声明性记忆内容。

    返回：
      - raw: memory.md 原始文本
      - categories: 按分类解析的记忆数据
      - total: 总条目数
    """
    dm = get_declarative_memory()
    # 读取原始文件内容
    raw = ""
    if os.path.exists(DECLARATIVE_MEMORY_PATH):
        with open(DECLARATIVE_MEMORY_PATH, "r", encoding="utf-8") as f:
            raw = f.read()

    return jsonify({
        "raw": raw,
        "categories": dm.data,
        "total": sum(len(v) for v in dm.data.values()),
    })


@app.route("/api/memory/remember", methods=["POST"])
def remember_memory():
    """
    添加一条声明性记忆。

    请求体：
      {"content": "记忆内容", "category": "分类名（可选，不传则自动分类）"}
    """
    data = request.get_json()
    content = data.get("content", "").strip()
    category = data.get("category", "").strip()

    if not content:
        return jsonify({"error": "内容不能为空"}), 400

    dm = get_declarative_memory()

    if category:
        # 指定分类
        if category not in CATEGORIES:
            return jsonify({"error": f"无效分类: {category}"}), 400
        success = dm.add(category, content)
        return jsonify({
            "success": success,
            "category": category,
            "content": content,
        })
    else:
        # 自动分类（调用 LLM）
        llm = get_llm()
        category = dm.classify_and_add(content, llm)
        return jsonify({
            "success": True,
            "category": category,
            "content": content,
        })


@app.route("/api/memory/forget", methods=["POST"])
def forget_memory():
    """
    删除包含关键词的记忆条目。

    请求体：
      {"keyword": "关键词"}
    """
    data = request.get_json()
    keyword = data.get("keyword", "").strip()

    if not keyword:
        return jsonify({"error": "关键词不能为空"}), 400

    dm = get_declarative_memory()
    removed = dm.remove(keyword)

    return jsonify({
        "removed": removed,
        "count": len(removed),
    })


@app.route("/api/memory/refresh", methods=["POST"])
def refresh_memory():
    """
    从近期对话中提取偏好，更新声明性记忆。

    请求体：
      {"conversation": "对话文本（可选，不传则用空字符串）"}
    """
    data = request.get_json() or {}
    conversation = data.get("conversation", "")

    if not conversation.strip():
        return jsonify({
            "error": "对话内容为空，请先进行几轮对话再提取偏好",
        }), 400

    dm = get_declarative_memory()
    llm = get_llm()
    result = dm.refresh_from_conversation(conversation, llm)

    if "error" in result:
        return jsonify({"error": result["error"]}), 500

    return jsonify({
        "added": result,
        "total_added": sum(result.values()) if result else 0,
    })


# ==================== 技能 API ====================

@app.route("/api/skills", methods=["GET"])
def get_skills():
    """
    获取所有技能列表（含元数据 + 指标）。

    返回每个技能的：
      - name, description, keywords, required_tools
      - body_chars, body_tokens, body_lines, body_rules（正文字段指标）
    """
    loader = get_skill_loader()
    skills = []

    for s in loader.list_all():
        # 读取正文计算指标（容错：文件缺失时跳过，不影响其他技能展示）
        try:
            body = _read_body(s["file"])
            metrics = compute_metrics(body)
        except FileNotFoundError:
            body = ""
            metrics = {"chars": 0, "lines": 0, "tokens": 0, "words": 0, "rules": 0, "sections": 0}

        # 检查是否有 .bak 备份文件（存在说明已被优化保存过）
        has_backup = os.path.exists(s["file"] + ".bak")

        skills.append({
            "name": s["name"],
            "description": s["description"],
            "keywords": s["keywords"],
            "required_tools": s["required_tools"],
            "file": os.path.basename(s["file"]),
            "metrics": metrics,
            "has_backup": has_backup,
        })

    return jsonify({"skills": skills})


@app.route("/api/skill/<name>/body", methods=["GET"])
def get_skill_body(name):
    """获取技能的正文内容"""
    loader = get_skill_loader()
    for s in loader.list_all():
        if s["name"] == name:
            # 容错：文件缺失或读取异常时返回友好错误，不抛 500
            try:
                body = _read_body(s["file"])
                return jsonify({
                    "name": name,
                    "body": body,
                    "metrics": compute_metrics(body),
                })
            except FileNotFoundError:
                return jsonify({"error": f"技能文件已丢失: {os.path.basename(s['file'])}"}), 500
            except Exception as e:
                return jsonify({"error": f"读取技能文件失败: {e}"}), 500
    return jsonify({"error": f"未找到技能: {name}"}), 404


@app.route("/api/skill/<name>/optimize", methods=["POST"])
def optimize_skill(name):
    """
    优化技能工作流。

    请求体：
      {"goal": "token|speed|both"}
    """
    data = request.get_json() or {}
    goal = data.get("goal", "token")

    if goal not in ("token", "speed", "both"):
        return jsonify({"error": f"无效目标: {goal}"}), 400

    loader = get_skill_loader()
    target = None
    for s in loader.list_all():
        if s["name"] == name:
            target = s
            break

    if not target:
        return jsonify({"error": f"未找到技能: {name}"}), 404

    # 执行优化
    llm = get_llm()
    optimizer = SkillOptimizer(llm)
    result = optimizer.optimize_skill(target["file"], goal)

    if "error" in result:
        return jsonify({"error": result["error"]}), 500

    # 返回优化结果（不自动保存，由前端决定）
    return jsonify({
        "skill_name": result["skill_name"],
        "original_body": result["original_body"],
        "optimized_body": result["optimized_body"],
        "original_metrics": result["original_metrics"],
        "optimized_metrics": result["optimized_metrics"],
        "comparison": result["comparison"],
        "llm_analysis": result.get("llm_analysis", ""),
        "filepath": result.get("filepath", ""),
    })


@app.route("/api/skill/<name>/save", methods=["POST"])
def save_optimized_skill(name):
    """
    保存优化后的技能到文件（备份原始文件）。

    设计要点：
    1. 已优化的技能也能正常保存（.bak 已存在时跳过备份，直接更新优化版本）
    2. 文件写入操作有完整异常保护，任何错误都返回 JSON（不返回 HTML 500 页面）
    3. 保存后清除技能缓存，使优化内容在对话框中立即生效

    请求体：
      {"optimized_body": "优化后的正文"}
    """
    data = request.get_json() or {}
    optimized_body = data.get("optimized_body", "")

    if not optimized_body.strip():
        return jsonify({"error": "优化后的正文为空"}), 400

    loader = get_skill_loader()
    target = None
    for s in loader.list_all():
        if s["name"] == name:
            target = s
            break

    if not target:
        return jsonify({"error": f"未找到技能: {name}"}), 404

    filepath = target["file"]
    frontmatter = _read_frontmatter_only(filepath)

    # 容错：frontmatter 为空说明文件已丢失或损坏，无法安全保存
    if not frontmatter.get("name"):
        return jsonify({"error": f"技能文件元数据读取失败或文件已丢失: {os.path.basename(filepath)}"}), 500

    # ---- 文件操作区（全部用 try/except 保护，确保任何异常都返回 JSON 而非 HTML）----
    import shutil
    backup_path = filepath + ".bak"
    backup_created = False

    try:
        # 备份原始文件（仅在 .bak 不存在时备份，保留最初的原始版本）
        # 已优化的技能 .bak 已存在，跳过备份，直接覆盖更新优化版本
        if not os.path.exists(backup_path):
            shutil.copy2(filepath, backup_path)
            backup_created = True

        # 重建文件：frontmatter + 优化后的正文
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

    except PermissionError:
        return jsonify({"error": f"文件被占用或权限不足: {os.path.basename(filepath)}"}), 500
    except OSError as e:
        return jsonify({"error": f"文件操作失败: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"保存失败: {e}"}), 500

    # 清除 Agent 内部的技能正文缓存，使优化后的内容在对话框中立即生效
    # （activate() 有懒加载缓存，不清除的话会用旧正文）
    _invalidate_skill_cache(filepath)

    return jsonify({
        "success": True,
        "filepath": filepath,
        "backup": backup_path,
        "backup_created": backup_created,
    })


@app.route("/api/skill/<name>/backup", methods=["GET"])
def get_skill_backup(name):
    """获取技能的备份文件内容（优化前的版本）"""
    loader = get_skill_loader()
    for s in loader.list_all():
        if s["name"] == name:
            backup_path = s["file"] + ".bak"
            if os.path.exists(backup_path):
                with open(backup_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return jsonify({
                    "exists": True,
                    "content": content,
                })
            else:
                return jsonify({
                    "exists": False,
                    "message": "无备份文件",
                })
    return jsonify({"error": f"未找到技能: {name}"}), 404


@app.route("/api/skill/<name>/restore", methods=["POST"])
def restore_skill(name):
    """
    从 .bak 备份文件恢复技能到优化前的原始版本。

    流程：
      1. 检查 .bak 文件是否存在
      2. 用 .bak 内容覆盖当前 .md 文件
      3. 删除 .bak 文件（恢复后不再需要）
      4. 清除技能缓存
    """
    loader = get_skill_loader()
    target = None
    for s in loader.list_all():
        if s["name"] == name:
            target = s
            break

    if not target:
        return jsonify({"error": f"未找到技能: {name}"}), 404

    filepath = target["file"]
    backup_path = filepath + ".bak"

    if not os.path.exists(backup_path):
        return jsonify({"error": "无备份文件，无法恢复"}), 400

    # 文件操作保护（与 save 接口保持一致的异常处理标准）
    import shutil
    try:
        # 用备份覆盖当前文件
        shutil.copy2(backup_path, filepath)
        # 删除备份文件（已恢复，不再需要）
        os.remove(backup_path)
    except PermissionError:
        return jsonify({"error": f"文件被占用或权限不足: {os.path.basename(filepath)}"}), 500
    except OSError as e:
        return jsonify({"error": f"文件操作失败: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"恢复失败: {e}"}), 500

    # 清除缓存
    _invalidate_skill_cache(filepath)

    return jsonify({
        "success": True,
        "message": f"技能 {name} 已恢复到原始版本",
    })


# ==================== 对话 API ====================

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    ReAct Agent 多轮对话接口。

    请求体：
      {"message": "用户输入文本"}

    返回：
      {
        "answer": "最终回答",
        "trace": [推理步骤列表],
        "memory_size": 当前工作记忆条数
      }

    核心逻辑：
      1. 获取全局 Agent 实例（保持多轮对话上下文）
      2. 用 redirect_stdout 捕获 verbose 推理过程
      3. 调用 agent.chat() 获取最终回答
      4. 解析推理过程返回给前端展示
    """
    data = request.get_json() or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    agent = get_agent()

    # 用 StringIO 捕获 Agent verbose 模式的 print 输出（推理过程）
    stdout_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture):
            answer = agent.chat(message)
    except Exception as e:
        return jsonify({"error": f"Agent 执行出错: {str(e)}"}), 500

    # 解析推理过程
    raw_output = stdout_capture.getvalue()
    trace = parse_react_trace(raw_output)

    # 获取工作记忆状态
    memory_size = len(agent.memory.items)

    return jsonify({
        "answer": answer,
        "trace": trace,
        "memory_size": memory_size,
    })


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """
    ReAct Agent 流式对话接口（SSE Server-Sent Events）。

    请求体：
      {"message": "用户输入文本"}

    返回：
      SSE 事件流，每行格式为 "data: {JSON}\\n\\n"
      事件类型：
        - {"type": "trace", "step": {"type": "...", "text": "..."}}  推理步骤
        - {"type": "answer_chunk", "text": "..."}                    回答片段
        - {"type": "done", "memory_size": int}                       完成
        - {"type": "error", "message": "..."}                        错误
    """
    data = request.get_json() or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    agent = get_agent()

    def generate():
        """
        SSE 生成器：将 Agent 的流式事件转为 SSE 格式输出。

        每个事件用 "data: {json}\n\n" 格式发送，前端用 EventSource 或
        fetch + ReadableStream 解析。
        """
        try:
            for event in agent.chat_streaming(message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    # 使用 stream_with_context 确保请求上下文在生成器生命周期内可用
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            # 禁用缓存，确保实时推送
            "Cache-Control": "no-cache",
            # 保持连接不超时
            "Connection": "keep-alive",
            # CORS 支持（开发环境）
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/api/chat/clear", methods=["POST"])
def clear_chat():
    """
    清空工作记忆（开始新的对话）。

    Agent 的工作记忆是滑动窗口模式，清空后相当于重置对话上下文。
    声明性记忆不受影响（持久化在 memory.md 中）。
    """
    agent = get_agent()
    agent.memory.items.clear()
    agent.memory.summary = ""

    return jsonify({
        "success": True,
        "message": "工作记忆已清空",
        "memory_size": 0,
    })


@app.route("/api/chat/memory", methods=["GET"])
def get_chat_memory():
    """获取当前工作记忆状态（条数 + 摘要长度）"""
    agent = get_agent()
    return jsonify({
        "memory_size": len(agent.memory.items),
        "summary_length": len(agent.memory.summary),
        "window_size": agent.memory.window_size,
    })


# ==================== 启动 ====================

if __name__ == "__main__":
    print("=" * 50)
    print("  Harness Web 界面")
    print("  访问 http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
