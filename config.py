# -*- coding: utf-8 -*-
"""
集中配置模块
==============
从 .env 文件读取所有配置项（API Key、模型参数、路径等）。
整个项目的其他模块统一从此处导入配置，避免散落的硬编码。
"""
import os
from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
load_dotenv()


# ============ DeepSeek 大模型配置（对话推理）============
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ============ 千问向量模型配置（RAG 检索）============
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
QWEN_EMBEDDING_MODEL = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v3")
QWEN_EMBEDDING_DIM = int(os.getenv("QWEN_EMBEDDING_DIM", "1024"))

# ============ ReAct Agent 配置 ============
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "6"))   # 单轮最大推理循环次数
MEMORY_WINDOW = int(os.getenv("MEMORY_WINDOW", "8"))     # 工作记忆窗口大小
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))     # 生成温度
TOP_K = int(os.getenv("TOP_K", "3"))                     # RAG 检索返回数量

# ============ 路径配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VECTORSTORE_DIR = os.path.join(BASE_DIR, "vectorstore")
RAG_CORPUS_PATH = os.path.join(DATA_DIR, "rag_corpus.json")
FAISS_INDEX_PATH = os.path.join(VECTORSTORE_DIR, "qwen_index.faiss")
FAISS_META_PATH = os.path.join(VECTORSTORE_DIR, "qwen_meta.json")

# 古诗词语料库路径（poetry_search 工具使用）
POETRY_CORPUS_PATH = os.path.join(DATA_DIR, "poetry_corpus.json")

# 股票财务指标数据路径（stock_analysis 工具使用）
# 静态缓存：手工整理的 5 只股票 3 年数据
STOCK_METRICS_PATH = os.path.join(DATA_DIR, "stock_metrics.json")

# iFinD 实时数据缓存目录（stock_analysis 在线模式使用）
# 每只通过 iFinD 获取的股票会缓存为 {code}.json，避免重复调用 API
STOCK_CACHE_DIR = os.path.join(DATA_DIR, "stock_cache")

# ============ SubAgent 分发配置 ============
# 批量股票查询时的最大并发线程数
# 控制 SubAgent 的并行度，建议不超过 5，避免 API 限流
MAX_DISPATCH_WORKERS = int(os.getenv("MAX_DISPATCH_WORKERS", "3"))

# ============ 声明性记忆配置 ============
# 持久化存储用户兴趣爱好、习惯偏好等长期信息
# 手动触发更新：不会自动从对话中提取，需用户通过命令显式触发
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
DECLARATIVE_MEMORY_PATH = os.path.join(MEMORY_DIR, "memory.md")


def check_api_keys():
    """检查必需的 API Key 是否已配置，返回缺失列表。"""
    missing = []
    if not DEEPSEEK_API_KEY:
        missing.append("DEEPSEEK_API_KEY")
    if not QWEN_API_KEY:
        missing.append("QWEN_API_KEY")
    return missing
