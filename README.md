# Harness ReAct Agent

基于 **ReAct（Reasoning + Acting）** 模式的多轮对话 Agent 框架，集成 RAG 向量检索、古诗词查找、天气查询、股票分析（财报 + K线行情）等技能，支持 LLM 语义路由、工作记忆、渐进式技能加载、**SubAgent 并行分发**与 **Web 可视化控制台**。

## 核心特性

| 特性 | 说明 |
|------|------|
| ReAct 推理循环 | Thought → Action → Observation → Final Answer |
| LLM 语义技能路由 | 优先用 LLM 语义判断激活技能，失败时回退关键词匹配 |
| SubAgent 并行分发 | 多只股票查询自动拆分为子任务，ThreadPoolExecutor 并行执行 |
| Web 可视化控制台 | Flask 后端 + 现代玻璃拟态前端，SSE 流式打字机效果 |
| 推理过程可视化 | ReAct 每一步推理实时折叠展示，不遮挡对话内容 |
| 分发流程图动画 | SubAgent 分发过程动态流程图：Main Agent → Dispatcher → SubAgents → 聚合 |
| 多轮对话 | 工作记忆维持上下文，支持连续追问 |
| RAG 检索 | 千问向量模型 + FAISS 向量检索 |
| 古诗词查找 | 基于标签匹配的语义检索，85 首古诗词语料库 |
| 天气查询 | Open-Meteo 免费 API，无需 Key |
| 股票财报分析 | 近 3 年财务数据，支持自定义时间区间，iFinD + 东方财富双数据源 |
| 股票行情查询 | 多时间粒度 K 线（分钟/日/周/月），腾讯 + 新浪多源回退 |
| 工作记忆 | 滑动窗口 + 自动摘要，长对话不丢上下文 |
| 声明性记忆 | 持久化用户偏好（兴趣/习惯/背景），手动触发更新，注入对话上下文 |
| 渐进式 Skill | Markdown 工作流驱动，每种技能一个 .md 文件，新增技能零代码改动 |
| 技能优化器 | LLM 驱动的工作流优化，前后指标对比，一键保存（原始备份 .bak） |

## 目录结构

```
harness_skill_13/
├── main.py                     # CLI 入口：交互式多轮对话
├── config.py                   # 集中配置（读取 .env，含 MAX_DISPATCH_WORKERS）
├── .env                        # API Key 配置（需自行创建）
├── requirements.txt            # Python 依赖
│
├── core/                       # 核心引擎层
│   ├── agent.py                #   ReAct Agent 主循环（含 LLM 语义路由 + 流式推理）
│   ├── sub_agent.py            #   子 Agent（direct 模式直接调工具 / react 模式预留）
│   ├── dispatcher.py           #   任务分发管理器（ThreadPoolExecutor 并行 + 事件回调）
│   ├── memory.py               #   工作记忆（滑动窗口 + 摘要）
│   ├── declarative_memory.py   #   声明性记忆（持久化用户偏好，手动触发更新）
│   ├── skill_optimizer.py      #   技能优化器（LLM 驱动，前后对比）
│   └── prompts.py              #   ReAct 提示词 + 技能路由模板 + 记忆提示词
│
├── llm/                        # 大模型客户端层
│   ├── deepseek_client.py      #   DeepSeek 对话（懒加载）
│   └── qwen_embedding.py       #   千问向量模型（懒加载）
│
├── tools/                      # 工具层
│   ├── base.py                 #   工具基类 + 注册表
│   ├── rag_search.py           #   RAG 向量检索（千问 + FAISS）
│   ├── weather.py              #   城市天气查询（Open-Meteo）
│   ├── poetry_search.py        #   古诗词语义检索
│   ├── stock_analysis.py       #   股票财报分析（基本面）
│   ├── stock_quote_tool.py     #   股票 K 线行情分析（技术面）
│   ├── stock_batch_query.py    #   批量股票查询（SubAgent 并行分发入口）
│   ├── flashcard.py            #   单词闪卡（测验/浏览/复习/详情）
│   ├── em_quote_fetcher.py     #   多源 K 线数据获取（腾讯/新浪/东方财富）
│   ├── em_data_fetcher.py      #   东方财富财报数据获取
│   └── ifind_adapter.py        #   iFinD 数据适配器
│
├── skills/                     # 技能层（Markdown 工作流驱动）
│   ├── loader.py               #   渐进式加载器
│   ├── finance_qa.md           #   金融研报问答
│   ├── weather_query.md        #   天气查询
│   ├── poetry_search.md        #   古诗词查找
│   ├── stock_prediction.md     #   股票分析（财报 + 行情 + 批量查询）
│   ├── flashcard.md            #   单词闪卡（测验/浏览/复习）
│   └── *.md.bak                #   技能优化前的原始备份（优化保存时自动生成）
│
├── web/                        # Web 可视化控制台
│   ├── server.py               #   Flask 后端（REST API + SSE 流式对话）
│   ├── templates/
│   │   └── index.html          #   前端页面（三段式布局）
│   └── static/
│       ├── css/cyberpunk.css   #   玻璃拟态样式（蓝紫渐变主色调）
│       └── js/app.js           #   前端逻辑（SSE 解析 + 流程图动画 + 面板管理）
│
├── memory/                     # 声明性记忆目录
│   └── memory.md               #   用户档案（兴趣/习惯/背景，手动触发更新）
│
├── optimization_reports/       # 技能优化报告（自动生成）
│   ├── *_comparison.json       #   优化前后指标对比数据
│   ├── *_optimization_report.html  # 可视化对比报告
│   ├── *_optimized.md          #   优化后的技能正文
│   └── *_original.md           #   优化前的技能正文
│
├── data/                       # 数据目录
│   ├── rag_corpus.json         #   RAG 语料库（金融研报）
│   ├── poetry_corpus.json      #   古诗词语料库
│   ├── flashcard_words.json    #   单词闪卡词库
│   ├── stock_metrics.json      #   股票财务指标（静态缓存）
│   ├── stock_cache/            #   iFinD/东方财富实时数据缓存
│   └── *_semantic.json         #   股票年报语义数据
│
└── vectorstore/                # FAISS 索引缓存（首次运行自动生成）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

在项目根目录创建 `.env` 文件，填入你的真实 Key：

```
DEEPSEEK_API_KEY=sk-你的deepseek-key
QWEN_API_KEY=sk-你的千问-key
```

其他配置项均有默认值，按需添加（参见下方 [配置项](#配置项) 表格）。

- DeepSeek Key 获取：https://platform.deepseek.com/
- 千问 Key 获取：https://dashscope.console.aliyun.com/

### 3. 运行

#### Web 控制台（推荐）

```bash
python web/server.py
```

浏览器访问 `http://localhost:5000`，即可使用可视化界面：
- 流式打字机效果逐字显示回复
- ReAct 推理过程可折叠展示
- SubAgent 分发流程图实时动画
- 声明性记忆与技能优化可视化管理

#### CLI 命令行

```bash
python main.py
```

### 4. 对话示例

```
🧑 你: 帮我找一首描写思乡的古诗
🤖 助手: 为您找到李白的《静夜思》："床前明月光，疑是地上霜..."

🧑 你: 贵州茅台近3年财务数据怎么样？
🤖 助手: 贵州茅台（600519.SH）近3年财报分析...
        2023-2025年营收从1505亿增长至...
        ROE保持在30%以上，盈利能力强...
        综合评分：85分（强烈推荐）

🧑 你: 帮我同时分析贵州茅台、五粮液、中国平安的财务数据
🤖 助手: 检测到3只股票，启动并行分发...
        SubAgent 1: 贵州茅台 ✓ (1.2s)
        SubAgent 2: 五粮液 ✓ (1.5s)
        SubAgent 3: 中国平安 ✓ (1.8s)
        总耗时: 1.8s（串行需 4.5s）
        [聚合报告] ...

🧑 你: 北京今天天气怎么样？
🤖 助手: 北京今天大毛毛雨，温度35.3°C...
```

## 技能一览

| 技能 | 触发示例 | 使用工具 | 数据源 |
|------|---------|---------|--------|
| 金融研报问答 | "南方航空2022年净利润是多少？" | `rag_search` | 本地 RAG 语料库 |
| 天气查询 | "北京今天天气怎么样？" | `weather` | Open-Meteo 免费 API |
| 古诗词查找 | "帮我找一首描写思乡的诗" | `poetry_search` | 本地古诗词语料库 |
| 股票财报分析 | "贵州茅台近3年财务数据" | `stock_analysis` | 本地缓存 → iFinD → 东方财富 |
| 股票行情查询 | "铜陵有色最近一个月的日K线" | `stock_quote` | 腾讯 → 新浪 → 东方财富 |
| 批量股票查询 | "同时分析茅台、五粮液、平安" | `stock_batch_analysis` | SubAgent 并行分发 |
| 单词闪卡 | "帮我背单词" / "随机考考我" | `flashcard` | 本地词库（12 个高级词汇） |

## 架构详解

### 整体架构

```
┌──────────────────────────────────────────────────────┐
│                    用户输入                            │
├──────────────────────────────────────────────────────┤
│  Web 前端 (index.html)          CLI (main.py)         │
│    ├─ SSE 流式接收                ├─ input() 阻塞等待  │
│    ├─ 推理过程可视化              └─ print() 输出      │
│    └─ 分发流程图动画                                  │
├──────────────────────────────────────────────────────┤
│  Flask 后端 (server.py)          直接调用              │
│    ├─ /api/chat (非流式)         agent.chat()         │
│    └─ /api/chat/stream (SSE)    agent.chat_streaming()│
├──────────────────────────────────────────────────────┤
│  ReactAgent (core/agent.py)                           │
│    ├─ Skill 路由 (LLM 语义 + 关键词回退)               │
│    ├─ ReAct 循环 (Thought→Action→Observation→Final)   │
│    ├─ 工作记忆 (滑动窗口 + 摘要)                       │
│    └─ 声明性记忆 (注入系统提示词)                      │
├──────────────────────────┬───────────────────────────┤
│  单只股票查询              │  多只股票查询              │
│  stock_analysis           │  stock_batch_analysis     │
│  stock_quote              │    └─ DispatchManager     │
│                           │         ├─ SubAgent 1     │
│                           │         ├─ SubAgent 2     │
│                           │         └─ SubAgent N     │
│                           │         (ThreadPool 并行)  │
├──────────────────────────┴───────────────────────────┤
│  工具层 (tools/)                                      │
│    rag_search | weather | poetry_search               │
│    stock_analysis | stock_quote | flashcard           │
├──────────────────────────────────────────────────────┤
│  数据层                                               │
│    FAISS 索引 | 本地语料库 | iFinD | 东方财富 | 腾讯   │
└──────────────────────────────────────────────────────┘
```

### ReAct 循环

```
用户输入 → [Skill 路由] → [构建提示词] → DeepSeek 推理
     ↑                                      ↓
     │                              ┌── Final Answer → 返回用户
     │                              │
     │                              └── Action → 执行工具 → Observation
     │                                                ↓
     └────────────────────────────────── [追加到草稿本] → 再次推理
```

Agent 每轮最多循环 `MAX_ITERATIONS` 次（默认 6 次），防止无限循环。

**流式模式**（Web 控制台）：Agent 通过 `chat_streaming()` 方法逐步 yield 推理事件，前端通过 SSE 实时接收：
- `trace` 事件：每一步 Thought/Action/Observation 实时推送，驱动推理面板逐步展开
- `dispatch` 事件：SubAgent 分发开始/完成实时推送，驱动分发流程图节点逐个激活
- `answer_chunk` 事件：最终回答逐字推送（打字机效果，带闪烁光标）
- `done` 事件：回答完成（含工作记忆条数）
- `error` 事件：执行异常（含错误信息）

### SubAgent 并行分发架构

当用户同时查询多只股票时，主 Agent 自动调用 `stock_batch_analysis` 工具，触发并行分发：

```
主 Agent (ReactAgent)
  │  ReAct 决策：检测到多只股票 → Action: stock_batch_analysis
  ▼
StockBatchQueryTool.run()
  │  将股票列表拆分为子任务
  ▼
DispatchManager.dispatch()
  │  ThreadPoolExecutor 并行提交
  ├─→ SubAgent 1 (贵州茅台)  ──→ StockAnalysisTool.run()  ──→ 结果1
  ├─→ SubAgent 2 (五粮液)    ──→ StockAnalysisTool.run()  ──→ 结果2
  └─→ SubAgent 3 (中国平安)  ──→ StockAnalysisTool.run()  ──→ 结果3
  │  并行执行（max_workers=3）
  ▼
聚合结果 → 返回 Observation 给主 Agent
```

**核心组件：**

| 组件 | 文件 | 职责 |
|------|------|------|
| SubAgent | `core/sub_agent.py` | 轻量级子 Agent，执行单只股票查询 |
| DispatchManager | `core/dispatcher.py` | 任务分发管理器，并行执行 + 结果聚合 |
| StockBatchQueryTool | `tools/stock_batch_query.py` | 批量查询入口工具，拆分任务 + 触发分发 |

**SubAgent 工作模式：**

| 模式 | 说明 | LLM 调用 | 状态 |
|------|------|---------|------|
| `direct`（默认） | 直接调用工具，主 Agent 已决策好查什么 | 零 LLM 成本 | 已实现 |
| `react`（预留） | 迷你 ReAct 循环，自主决策工具和参数 | 每只股票独立推理 | 接口预留 |

**并行加速效果：**
- 串行查 5 只股票：5 × T 秒
- 并行查 5 只（max_workers=3）：约 2 × T 秒
- 并行查 5 只（max_workers=5）：约 1 × T 秒

并发数通过 `MAX_DISPATCH_WORKERS` 配置（默认 3，建议不超过 5）。

**事件回调机制：**

DispatchManager 支持 `event_callback` 回调，在 SubAgent 开始/完成时发射事件。Web 模式下，事件通过线程安全队列传递给 SSE 生成器，实时推送到前端，驱动分发流程图动画：

```
DispatchManager → event_callback → queue → SSE 生成器 → 前端流程图动画
```

事件类型：
- `dispatch_start`：分发开始（含任务总数、股票列表、并发数）
- `start`：单个 SubAgent 开始执行
- `complete`：单个 SubAgent 完成（含状态、耗时）
- `all_done`：全部分发完成（含总耗时）

### Skill 路由机制（LLM 语义判断 + 关键词回退）

```
用户输入
    ↓
┌── LLM 语义路由（优先）
│   将用户输入 + 所有技能描述交给 LLM 判断
│   能理解同义词、迂回表达（如"月亮下一个人想家"→ poetry_search）
│   ↓
│   成功？→ 激活对应技能
│   ↓
└── 失败 → 关键词字符串匹配（回退）
           用户输入包含技能 keywords 中的词 → 激活
           ↓
           无匹配 → 纯对话模式（无工具）
```

### 工作记忆

```
对话消息持续写入 → 超过窗口大小(8条) → 旧消息压缩为摘要
                                          ↓
                              新对话提示词 = 摘要 + 近期对话 + 当前问题
```

- **近期对话**：保留最近 N 条完整内容
- **摘要**：旧消息由 DeepSeek 压缩为 200 字以内的摘要
- **不丢上下文**：即使对话很长，关键信息仍保留在摘要中

### 声明性记忆（手动触发更新）

记录用户的兴趣爱好、习惯偏好、背景信息等**长期有效**的个人信息，持久化到 `memory/memory.md` 文件，重启不丢失。与工作记忆互补：

| 维度 | 工作记忆 | 声明性记忆 |
|------|---------|-----------|
| 存储内容 | 对话上下文（近期问答） | 用户档案（兴趣/习惯/背景） |
| 生命周期 | 短期（重启丢失） | 长期（持久化到文件） |
| 更新方式 | 自动（每轮对话自动写入） | **手动触发**（用户显式命令） |
| 注入位置 | ReAct 用户消息 | 系统提示词（用户档案段） |

**更新方式（均为手动触发）：**

```
/remember 我喜欢看科幻电影          → LLM 自动分类后添加
/remember 兴趣爱好 | 喜欢摄影        → 指定分类添加
/forget 科幻                         → 删除包含关键词的条目
/refresh_memory                      → 从近期对话中提取偏好并更新
/profile                             → 查看当前用户档案
```

`/refresh_memory` 的工作流程：

```
工作记忆（近期对话）→ LLM 提取用户偏好 → 去重合并 → 写入 memory.md
```

每次对话时，声明性记忆会自动注入系统提示词，让 Agent 回答时自然参考用户偏好。

### 渐进式 Skill 加载（Markdown 工作流驱动）

每个技能对应一个 `.md` 工作流文件，声明式定义技能的元数据和工作流程：

```
阶段1 发现    扫描 skills/*.md 文件，解析 frontmatter 元数据（纯文本 IO，零模块导入）
     ↓
阶段2 路由    LLM 语义判断（或关键词匹配）→ 选定技能
     ↓
阶段3 激活    读取匹配技能的工作流正文，注入 ReAct 系统提示词
     ↓
     激活工具 + 注入工作流 → 进入 ReAct 循环
```

MD 工作流文件格式：

```markdown
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

## 回答规范
- 规范一
- 规范二
```

- `frontmatter`（`---` 之间）：机器可读的元数据，供路由和激活工具
- `正文`：工作流描述，直接注入 ReAct 系统提示词，指导 Agent 如何使用工具

未匹配到技能时，Agent 进入纯对话模式（无工具，直接用 DeepSeek 回答）。

### 工具说明

| 工具 | 名称 | 用途 | 依赖 |
|------|------|------|------|
| RAG 检索 | `rag_search` | 搜索金融研报知识库 | 千问向量模型 + FAISS |
| 天气查询 | `weather` | 查询城市实时天气 | Open-Meteo（免费，无需 Key） |
| 古诗词查找 | `poetry_search` | 根据描述检索古诗词 | 本地语料库 + 标签匹配 |
| 股票财报分析 | `stock_analysis` | 财务数据分析与建议 | iFinD / 东方财富 API |
| 股票行情查询 | `stock_quote` | K 线走势分析 | 腾讯 / 新浪 API |
| 批量股票查询 | `stock_batch_analysis` | 多只股票并行查询 | SubAgent + DispatchManager |
| 单词闪卡 | `flashcard` | 单词测验/浏览/复习 | 本地词库 |

## Web 可视化控制台

### 界面布局

采用三段式 flex 布局，推理过程和分发面板独立于消息流，不遮挡对话内容：

```
┌─────────────────────────────────────────┐
│ 顶部导航栏（品牌 · 在线状态 · 时钟）       │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 对话终端卡片                          │ │
│ │ ├─ 卡片头部（标题 · 流式开关 · 清空） │ │
│ │ ├─ 消息区（独立滚动，仅含对话消息）    │ │
│ │ ├─ 信息面板区（可折叠，不挤压消息）    │ │
│ │ │  ├─ ▸ ReAct 推理过程（折叠/展开）   │ │
│ │ │  └─ ▸ SubAgent 分发流程（折叠/展开）│ │
│ │ └─ 输入区（始终固定底部）             │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ 声明性记忆模块（可折叠）              │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ 技能矩阵模块（可折叠）                │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### 核心交互

| 功能 | 说明 |
|------|------|
| 流式打字机 | SSE 逐字接收回复，实时显示闪烁光标 |
| 推理过程折叠 | ReAct 每步推理（Thought/Action/Observation）可折叠展示，带颜色标签 |
| 分发流程图 | SubAgent 分发过程动态流程图：Main Agent → DispatchManager → SubAgents → 聚合结果，节点逐个激活 |
| 三段式布局 | 消息区（独立滚动）、信息面板区（可折叠不遮挡消息）、输入区（固定底部）各自独立 |
| 示例问题点击 | 欢迎页示例气泡点击即发送 |
| 消息复制 | 悬停消息显示复制按钮，一键复制 |
| 声明性记忆管理 | 可视化添加/删除/提取偏好，memory.md 实时预览 |
| 技能优化 | 就地展示优化前后对比报告，指标表格 + 正文对比，支持保存/恢复 |
| 响应式布局 | 适配桌面/平板/手机三种屏幕尺寸（768px / 480px 断点） |

### API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/memory` | 获取声明性记忆内容 |
| POST | `/api/memory/remember` | 添加记忆（LLM 自动分类） |
| POST | `/api/memory/forget` | 删除记忆（关键词匹配） |
| POST | `/api/memory/refresh` | 从对话提取偏好 |
| GET | `/api/skills` | 获取所有技能列表 |
| GET | `/api/skill/<name>/body` | 获取技能正文 |
| POST | `/api/skill/<name>/optimize` | 优化技能（LLM 驱动） |
| POST | `/api/skill/<name>/save` | 保存优化结果（自动备份原始为 .bak） |
| GET | `/api/skill/<name>/backup` | 获取优化前备份的原始版本 |
| POST | `/api/skill/<name>/restore` | 从 .bak 恢复到原始版本 |
| POST | `/api/chat` | 对话接口（非流式） |
| POST | `/api/chat/stream` | 对话接口（SSE 流式） |
| POST | `/api/chat/clear` | 清空工作记忆 |
| GET | `/api/chat/memory` | 获取工作记忆状态 |

## 股票分析功能详解

### 财报分析（stock_analysis）

支持基本面分析，基于年报数据评估成长性、盈利能力和财务安全：

**数据获取策略（三级回退）：**
1. **本地缓存**：已缓存的股票直接读取（毫秒级）
2. **iFinD 实时获取**：通过 iFinD 接口获取真实财务数据
3. **东方财富 API**：免费公开接口，无需 API Key

**时间区间处理：**
- 未指定时间 → 自动取最近 3 个已披露年报
- 指定时间区间（如"2020-2022年"）→ 实时调接口获取指定区间数据

### K 线行情查询（stock_quote）

支持技术面分析，基于 K 线数据计算走势趋势和技术指标：

**多时间粒度：**

| 粒度 | period 参数 | 数据源 | 默认范围 |
|------|------------|--------|---------|
| 5分钟 | `5min` | 新浪财经 | 最近 5 个交易日 |
| 15分钟 | `15min` | 新浪财经 | 最近 5 个交易日 |
| 30分钟 | `30min` | 新浪财经 | 最近 5 个交易日 |
| 60分钟 | `60min` | 新浪财经 | 最近 5 个交易日 |
| 日线 | `daily` | 腾讯财经 | 最近 30 天 |
| 周线 | `weekly` | 腾讯财经 | 最近 1 年 |
| 月线 | `monthly` | 腾讯财经 | 最近 2 年 |

**支持品种：** A 股股票、ETF 基金（如 516920 芯片ETF汇添富）、科创板

**技术指标：** MA 均线（5/10/20/60）、RSI(14)、波动率、成交量分析、支撑位/压力位

### 批量查询（stock_batch_analysis）

当用户同时查询 2 只及以上股票时自动触发：

```
用户: "帮我同时分析贵州茅台、五粮液、中国平安的财务数据"
  ↓
主 Agent ReAct 决策 → Action: stock_batch_analysis
  ↓
StockBatchQueryTool → DispatchManager → 3 个 SubAgent 并行
  ↓
聚合报告返回 → 主 Agent 生成最终回答
```

**输入格式：**
```json
{"stocks": ["贵州茅台", "五粮液", "中国平安"], "analysis_type": "financial"}
{"stocks": ["茅台", "五粮液"], "analysis_type": "quote", "period": "daily"}
```

### 数据源说明

| 数据源 | 用途 | 优势 |
|--------|------|------|
| 腾讯财经 API | 日/周/月 K 线 | 格式规范，支持日期范围 |
| 新浪财经 API | 分钟级 K 线 | 分钟数据支持好 |
| 东方财富 API | 股票搜索 + 实时行情 | 搜索准确，覆盖全品种 |
| iFinD 接口 | 财报数据 | 数据权威，需 API Key |

## 配置项

在 `.env` 文件中配置（均有默认值）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_API_KEY` | （空） | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek 接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 使用的模型 |
| `QWEN_API_KEY` | （空） | 千问 API Key |
| `QWEN_EMBEDDING_MODEL` | `text-embedding-v3` | 向量模型 |
| `MAX_ITERATIONS` | `6` | 单轮最大推理循环次数 |
| `MEMORY_WINDOW` | `8` | 工作记忆窗口大小 |
| `TEMPERATURE` | `0.7` | 生成温度 |
| `TOP_K` | `3` | RAG 检索返回数量 |
| `MAX_DISPATCH_WORKERS` | `3` | SubAgent 最大并发数 |

## 交互命令（CLI 模式）

| 命令 | 功能 |
|------|------|
| `/help` | 查看帮助 |
| `/skills` | 查看已注册技能 |
| `/memory` | 查看工作记忆状态 |
| `/clear` | 清空工作记忆 |
| `/profile` | 查看声明性记忆（用户档案） |
| `/remember <内容>` | 添加一条记忆（LLM 自动分类） |
| `/remember <分类> \| <内容>` | 指定分类添加记忆 |
| `/forget <关键词>` | 删除包含关键词的记忆条目 |
| `/refresh_memory` | 从近期对话提取偏好并更新记忆 |
| `/optimize_skill <名称> [目标]` | 手动触发技能优化，展示前后对比 |
| `/quit` | 退出 |

`/optimize_skill` 的优化目标可选：`token`（压缩 token）、`speed`（提升效率）、`both`（兼顾）。

## 扩展指南

### 新增工具

1. 在 `tools/` 下创建 `my_tool.py`，继承 `BaseTool`
2. 在 `tools/__init__.py` 中注册导入
3. 在 `main.py` 的 `create_agent()` 中注册工具实例
4. 在 `web/server.py` 的 `get_agent()` 中同步注册（Web 模式）

### 新增技能（只需一个 MD 文件）

在 `skills/` 目录下新建 `my_skill.md`，按上述格式填写 frontmatter 和工作流正文即可，**无需修改任何 Python 代码**。

### 技能优化（手动触发）

使用 `/optimize_skill` 命令或 Web 界面的"优化技能"按钮，对任意技能的工作流正文进行 LLM 驱动的优化：

```
/optimize_skill flashcard token   # 压缩 token 消耗
/optimize_skill flashcard speed   # 提升执行效率
/optimize_skill flashcard both    # 两者兼顾
```

优化流程：
1. 读取技能 .md 文件，计算优化前指标（字符数、token 数、规则数等）
2. 调用 LLM 优化正文（保留语义，压缩冗余）
3. 展示前后对比报告和 LLM 优化说明
4. 用户确认后保存（原始文件备份为 .md.bak，对比报告存入 `optimization_reports/`）

> 优化器位于 `core/skill_optimizer.py`，只优化正文不动 frontmatter。
> Web 界面支持「保存优化版本」和「从备份恢复原始版本」双向操作。

### 更换 RAG 语料

替换 `data/rag_corpus.json`，删除 `vectorstore/` 下的缓存文件，首次查询时自动重建索引。

> 索引通过语料哈希自动校验：语料未变更时直接用缓存，更新语料后自动重建。

## 测试与验证

项目暂无独立测试脚本，可通过以下方式验证功能：

```bash
# 1. 启动 Web 控制台，在浏览器中交互测试各功能
python web/server.py
#    访问 http://localhost:5000
#    测试项：
#      · 输入"帮我找一首描写思乡的古诗"  → 古诗词查找
#      · 输入"北京今天天气怎么样"        → 天气查询
#      · 输入"贵州茅台近3年财务数据"      → 股票财报分析
#      · 输入"帮我同时分析茅台、五粮液"   → SubAgent 并行分发
#      · 点击技能矩阵 → 优化 → 保存/恢复  → 技能优化器
#      · 声明性记忆 → REMEMBER/FORGET     → 声明性记忆

# 2. CLI 模式验证
python main.py
#    输入 /help  查看所有命令
#    输入 /skills 查看技能列表
#    输入 /memory 查看工作记忆状态
```

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM | DeepSeek（对话推理）+ 千问（向量嵌入） |
| 向量检索 | FAISS + numpy |
| Web 后端 | Flask（REST API + SSE 流式） |
| Web 前端 | 原生 HTML/CSS/JS（玻璃拟态风格） |
| 并发 | ThreadPoolExecutor（SubAgent 并行分发） |
| HTTP | requests（多源数据获取） |
| 配置 | python-dotenv（.env 环境变量） |
