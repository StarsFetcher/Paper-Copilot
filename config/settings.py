"""
应用配置模块
============
负责从环境变量中读取所有配置项，包括 LLM API 参数、向量数据库路径、
本地文件存储路径等核心配置。使用 python-dotenv 自动加载 .env 文件。

使用方式:
    from config.settings import settings
    print(settings.LLM_MODEL_NAME)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# 加载 .env 文件（优先级：当前目录 > 上级目录）
# ============================================================
# 先尝试从当前工作目录加载，再尝试从文件所在目录的上级加载
load_dotenv()


class Settings:
    """
    全局配置单例类

    所有配置项均通过环境变量读取，并提供合理的默认值。
    生产环境中请务必通过环境变量覆盖敏感信息（如 API_KEY）。
    """

    # ============================================================
    # 项目根目录
    # ============================================================
    PROJECT_ROOT: str = str(Path(__file__).resolve().parent.parent)

    # ============================================================
    # 本地文件存储配置
    # ============================================================
    PAPERS_DIR: str = os.getenv(
        "PAPERS_DIR",
        str(Path(PROJECT_ROOT) / "data" / "papers"),
    )
    """论文 PDF 文件本地存储目录"""

    BACKUPS_DIR: str = os.getenv(
        "BACKUPS_DIR",
        str(Path(PROJECT_ROOT) / "data" / "backups"),
    )
    """向量库备份本地存储目录"""

    # ============================================================
    # LLM / 大模型配置（兼容 OpenAI API 格式）
    # ============================================================
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    """LLM API 的基础 URL（可用于平替为其他兼容 OpenAI 格式的服务）"""

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    """LLM API 的认证密钥"""

    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gpt-4o")
    """聊天模型名称（如 gpt-4o, gpt-4-turbo, deepseek-chat 等）"""

    # ------------------------------------------------------------
    # Embedding 提供商标识: "openai" 或 "local"
    #   - "openai": 使用 OpenAI 兼容的 Embedding API（远程）
    #   - "local":  使用 HuggingFace 本地模型（无需联网，推荐 DeepSeek 用户）
    # ------------------------------------------------------------
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai")
    """Embedding 提供方（openai / local）"""

    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
    """Embedding 模型名称（openai 模式下为 API 模型名）"""

    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")
    """
    Embedding API 独立端点（仅在 EMBEDDING_PROVIDER=openai 时生效）。
    为空时自动使用 LLM_BASE_URL。
    用于 DeepSeek 等不提供 Embedding 的 LLM 提供商，
    可单独指向 SiliconFlow、阿里云百炼等 Embedding 服务。
    """

    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    """
    Embedding API 独立密钥（仅在 EMBEDDING_PROVIDER=openai 时生效）。
    为空时自动使用 LLM_API_KEY。
    """

    LOCAL_EMBEDDING_MODEL_NAME: str = os.getenv(
        "LOCAL_EMBEDDING_MODEL_NAME",
        "BAAI/bge-small-zh-v1.5",
    )
    """本地 Embedding 模型名称（HuggingFace model_id，仅在 EMBEDDING_PROVIDER=local 时生效）"""

    # ============================================================
    # 向量数据库配置 (Chroma)
    # ============================================================
    VECTOR_DB_PATH: str = os.getenv(
        "VECTOR_DB_PATH",
        str(Path(PROJECT_ROOT) / "data" / "vector_store"),
    )
    """Chroma 向量库本地持久化路径"""

    # ============================================================
    # PDF 文本切片配置
    # ============================================================
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    """每个文本块的字符数上限（用于 RecursiveTextSplitter 回退模式）"""

    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    """相邻文本块之间的重叠字符数，用于保持语义连贯性"""

    # 结构感知切片配置（主要策略）
    STRUCTURAL_CHUNK_TARGET: int = int(os.getenv("STRUCTURAL_CHUNK_TARGET", "1200"))
    """结构切片的理想块大小，合并时尽量接近此值"""

    STRUCTURAL_CHUNK_MAX: int = int(os.getenv("STRUCTURAL_CHUNK_MAX", "2000"))
    """结构切片的硬上限，任何块都不超过此值"""

    # ============================================================
    # 应用级配置
    # ============================================================
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    """全局日志级别"""

    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
    """PDF 文件上传的大小上限（MB）"""

    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    """网络操作（LLM API）的最大重试次数"""

    RETRY_DELAY: float = float(os.getenv("RETRY_DELAY", "1.0"))
    """重试间隔秒数"""

    # ============================================================
    # Agent 配置
    # ============================================================
    AGENT_MAX_ITERATIONS: int = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))
    """Agent 最大推理迭代次数，防止无限循环"""

    RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "5"))
    """检索工具返回的最相关文档数量"""

    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    """LLM 温度参数（0-2），越低越确定性，适合学术场景"""

    # ============================================================
    # Contradiction Detection 配置
    # ============================================================
    CONTRADICTION_RETRIEVAL_TOP_K: int = int(os.getenv(
        "CONTRADICTION_RETRIEVAL_TOP_K", "15",
    ))
    """矛盾检测专用检索量（需覆盖更多论文以进行跨论文对比）"""

    CONTRADICTION_TEMPERATURE: float = float(os.getenv(
        "CONTRADICTION_TEMPERATURE", "0.0",
    ))
    """矛盾检测 LLM 温度（0.0 = 最确定性判断）"""

    # ============================================================
    # LangGraph Custom Graph 配置
    # ============================================================
    GRAPH_MAX_SEARCH_ITERATIONS: int = int(os.getenv(
        "GRAPH_MAX_SEARCH_ITERATIONS", "3",
    ))
    """搜索-评估循环的最大迭代次数（防止无限循环）"""

    GRAPH_MAX_SEARCH_ANGLES: int = int(os.getenv(
        "GRAPH_MAX_SEARCH_ANGLES", "5",
    ))
    """单次规划步骤中允许的最大并行搜索角度数"""

    GRAPH_ENABLE_INTERRUPT: bool = os.getenv(
        "GRAPH_ENABLE_INTERRUPT", "False",
    ).lower() == "true"
    """
    是否启用 human-in-the-loop 中断。
    开启后，当搜索角度 >= GRAPH_INTERRUPT_ANGLE_THRESHOLD 时，
    图执行会暂停并等待用户确认搜索计划。

    注意：中断功能需要客户端支持 /api/chat/resume 端点，
    默认关闭以避免前端兼容性问题。
    """

    GRAPH_INTERRUPT_ANGLE_THRESHOLD: int = int(os.getenv(
        "GRAPH_INTERRUPT_ANGLE_THRESHOLD", "3",
    ))
    """触发 human_review 中断的最小搜索角度数"""

    GRAPH_ENABLE_CHECKPOINTING: bool = os.getenv(
        "GRAPH_ENABLE_CHECKPOINTING", "True",
    ).lower() == "true"
    """
    是否启用图状态持久化（检查点）。
    开启后支持多轮对话记忆、执行中断恢复。
    默认使用内存模式（InMemorySaver），无需额外配置。
    """

    GRAPH_CHECKPOINT_TYPE: str = os.getenv(
        "GRAPH_CHECKPOINT_TYPE", "memory",
    )
    """检查点类型: "memory" (会话级) 或 "sqlite" (磁盘持久化)"""

    GRAPH_CHECKPOINT_DB_PATH: str = os.getenv(
        "GRAPH_CHECKPOINT_DB_PATH",
        str(Path(PROJECT_ROOT) / "data" / "checkpoints" / "graph_state.db"),
    )
    """SqliteSaver 数据库路径（仅在 GRAPH_CHECKPOINT_TYPE=sqlite 时使用）"""

    # ============================================================
    # 论文发现 (arXiv API) 配置
    # ============================================================
    ARXIV_MAX_RESULTS: int = int(os.getenv("ARXIV_MAX_RESULTS", "10"))
    """arXiv 单次搜索最大返回结果数"""

    ARXIV_SEARCH_DAYS_BACK: int = int(os.getenv("ARXIV_SEARCH_DAYS_BACK", "90"))
    """arXiv 搜索默认回溯天数"""

    ARXIV_ENABLE_ITERATIVE_SEARCH: bool = os.getenv(
        "ARXIV_ENABLE_ITERATIVE_SEARCH", "True",
    ).lower() == "true"
    """是否启用迭代搜索（结果不足时换词重搜）"""

    # ============================================================
    # 论文元数据库配置
    # ============================================================
    PAPER_LIBRARY_DB_PATH: str = os.getenv(
        "PAPER_LIBRARY_DB_PATH",
        str(Path(PROJECT_ROOT) / "data" / "paper_library.db"),
    )
    """论文元数据库 SQLite 文件路径"""

    # ============================================================
    # 论文筛选配置
    # ============================================================
    SCREENING_QUALITY_THRESHOLD: float = float(os.getenv(
        "SCREENING_QUALITY_THRESHOLD", "5.0",
    ))
    """论文筛选的最低质量分数（0-10），低于此分数的论文被过滤"""

    # ============================================================
    # 深度分析配置
    # ============================================================
    DEEP_ANALYSIS_TEMPERATURE: float = float(os.getenv(
        "DEEP_ANALYSIS_TEMPERATURE", "0.1",
    ))
    """深度论文分析 LLM 温度（低温度确保提取一致性）"""


# ============================================================
# 全局单例实例
# ============================================================
settings = Settings()
