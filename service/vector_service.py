"""
向量数据库服务模块
===================
封装基于 Chroma + LangChain OpenAIEmbeddings 的向量存储与检索操作。

核心职责:
    1. 初始化 Embedding 模型和 Chroma 向量库
    2. 将切分后的文档块向量化并写入 Chroma
    3. 将 Chroma 数据持久化到本地磁盘（自动）
    4. 从本地磁盘（或 MinIO 恢复后）加载 Chroma 数据库
    5. 执行语义相似度检索

持久化策略:
    - Chroma 使用 PersistentClient，每次写入自动持久化到 SQLite
    - 由调用方（app.py）在写入完成后触发 MinIO 备份
    - 启动时从本地磁盘加载，若本地为空则尝试从 MinIO 恢复
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class _DirectEmbeddings(Embeddings):
    """
    轻量级 Embedding 适配器 — 使用 openai 原生 SDK 直连 API。

    为什么不用 langchain_openai.OpenAIEmbeddings？
      该库内部在 _tokenize() 中会尝试加载 tiktoken（需访问 Azure blob）
      或 HuggingFace AutoTokenizer（需访问 hf-mirror.com），这两个域名
      在国内网络环境下均可能 SSL 超时/被墙，导致整个向量库初始化失败。

    本适配器绕过所有本地 tokenizer 逻辑，直接调用远程 Embedding API，
    不依赖 tiktoken 或 transformers。
    """

    def __init__(self, model: str, base_url: str, api_key: str):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文档（langchain Embeddings 接口）"""
        if not texts:
            return []
        # 分批处理，避免单次请求过大
        batch_size = 32
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = self._client.embeddings.create(
                model=self.model,
                input=batch,
            )
            all_embeddings.extend(
                [item.embedding for item in resp.data]
            )
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """嵌入单条查询文本（langchain Embeddings 接口）"""
        resp = self._client.embeddings.create(
            model=self.model,
            input=[text],
        )
        return resp.data[0].embedding

    def __call__(self, text: str) -> list[float]:
        """使对象可被当作函数调用（兼容旧版向量库内部调用方式）"""
        return self.embed_query(text)


class VectorService:
    """
    向量数据库服务

    封装 Chroma 向量存储的全部操作，提供:
        - 文档添加（自动持久化）
        - 相似度搜索
        - 本地加载
        - 清空重建
    """

    # Chroma collection 名称（单个 collection 存储所有论文文档）
    COLLECTION_NAME = "paper_copilot"

    def __init__(self):
        """
        初始化向量服务。

        注意: 实际的 Chroma 实例在 load_or_create() 调用后才可用。
        这是因为 Embedding 模型可能在应用启动早期尚未完全就绪。
        """
        self._embeddings = None  # OpenAIEmbeddings 或 HuggingFaceEmbeddings
        self._client: Optional[chromadb.PersistentClient] = None
        self._vector_store: Optional[Chroma] = None
        self._store_path: Path = Path(settings.VECTOR_DB_PATH)
        self._initialized: bool = False

    # =================================================================
    # 初始化与生命周期
    # =================================================================

    @property
    def embeddings(self):
        """
        懒加载 Embedding 模型实例。

        支持两种模式（通过 EMBEDDING_PROVIDER 环境变量切换）:
          - "openai": 使用 OpenAI 兼容的远程 Embedding API
          - "local":  使用 HuggingFace 本地模型（无需联网，中文友好）
        """
        if self._embeddings is not None:
            return self._embeddings

        provider = settings.EMBEDDING_PROVIDER.lower()

        if provider == "local":
            # ========================================================
            # 本地 HuggingFace Embedding 模型
            # 首次运行会自动下载模型到本地缓存（~400MB）
            # 模型: BAAI/bge-small-zh-v1.5 — 轻量、中文友好、免费
            # ========================================================
            from langchain_huggingface import HuggingFaceEmbeddings

            model_name = settings.LOCAL_EMBEDDING_MODEL_NAME
            logger.info(
                f"正在加载本地 Embedding 模型: {model_name}"
            )
            logger.info(
                "首次运行将自动下载模型（~400MB），请耐心等待..."
            )

            self._embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={
                    "normalize_embeddings": True,  # 归一化，提升检索精度
                },
            )
            logger.info(f"本地 Embedding 模型加载完成 ✓: {model_name}")

        else:
            # ========================================================
            # OpenAI 兼容的远程 Embedding API（默认）
            # 使用原生 openai 库直连，避免 langchain_openai 内部
            # 加载 tiktoken（需访问 Azure blob）或 HuggingFace tokenizer
            # 导致的 SSL 连接问题
            # ========================================================
            logger.info(
                f"正在初始化远程 Embedding 模型: {settings.EMBEDDING_MODEL_NAME}"
            )
            embed_base_url = settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL
            embed_api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
            self._embeddings = _DirectEmbeddings(
                model=settings.EMBEDDING_MODEL_NAME,
                base_url=embed_base_url,
                api_key=embed_api_key,
            )
            logger.info(f"远程 Embedding 初始化完成 ✓ (endpoint={embed_base_url})")

        return self._embeddings

    @property
    def vector_store(self) -> Chroma:
        """获取当前向量库实例（必须已初始化）"""
        if self._vector_store is None:
            raise RuntimeError(
                "向量库尚未初始化，请先调用 load_or_create() 方法。"
            )
        return self._vector_store

    @property
    def is_initialized(self) -> bool:
        """检查向量库是否已初始化"""
        return self._initialized and self._vector_store is not None

    def load_or_create(self) -> bool:
        """
        加载已有的 Chroma 向量库，若不存在则创建空的向量库。

        这是应用启动时必须调用的初始化入口。

        加载逻辑:
            1. 创建 PersistentClient 指向 VECTOR_DB_PATH
            2. 尝试获取已存在的 collection
            3. 若不存在，创建新的空 collection（Chroma 原生支持空 collection）

        Returns:
            True 表示成功加载已有数据，False 表示创建了新的空库
        """
        try:
            self._store_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self._store_path)
            )

            # 检查是否已有 collection（即是否有已有数据）
            existing_collections = self._client.list_collections()
            collection_exists = any(
                c.name == self.COLLECTION_NAME for c in existing_collections
            )

            self._vector_store = Chroma(
                client=self._client,
                collection_name=self.COLLECTION_NAME,
                embedding_function=self.embeddings,
            )
            self._initialized = True

            if collection_exists:
                doc_count = self._get_document_count()
                logger.info(
                    f"Chroma 向量库加载成功 ✓: {doc_count} 个文档块, "
                    f"路径={self._store_path}"
                )
                return True
            else:
                logger.info(
                    f"Chroma 向量库创建成功 ✓（空库）, 路径={self._store_path}"
                )
                return False

        except Exception as e:
            logger.error(f"Chroma 向量库加载失败: {e}", exc_info=True)
            logger.warning("将删除损坏的数据目录并重新创建空白向量库")
            shutil.rmtree(str(self._store_path), ignore_errors=True)
            return self._create_empty_store()

    def _create_empty_store(self) -> bool:
        """
        创建一个空的 Chroma 向量库。

        Chroma 原生支持空 collection，无需占位文档。
        """
        try:
            logger.info("正在初始化空白 Chroma 向量库...")
            self._store_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self._store_path)
            )
            self._vector_store = Chroma(
                client=self._client,
                collection_name=self.COLLECTION_NAME,
                embedding_function=self.embeddings,
            )
            self._initialized = True
            logger.info(f"空白 Chroma 向量库创建成功 ✓，路径={self._store_path}")
            return False
        except Exception as e:
            logger.error(f"空白向量库创建失败: {e}")
            logger.warning(
                "向量库初始化失败，应用将以降级模式运行。"
                "请检查 LLM_API_KEY 和 LLM_BASE_URL 配置是否正确。"
            )
            # 不抛出异常，允许应用在降级模式下继续运行
            self._vector_store = None
            self._initialized = False
            return False

    # =================================================================
    # 文档写入
    # =================================================================

    def add_documents(self, documents: List[Document]) -> int:
        """
        将一组文档块添加到向量库中。

        Args:
            documents: LangChain Document 对象列表

        Returns:
            成功添加的文档数量

        持久化保证:
            Chroma PersistentClient 在每次写入后自动持久化到 SQLite，
            无需手动调用 save。
        """
        if not documents:
            logger.warning("传入空文档列表，跳过添加")
            return 0

        if not self.is_initialized:
            raise RuntimeError("向量库未初始化，无法添加文档")

        try:
            # 批量添加文档（Chroma 自动持久化）
            logger.info(f"正在向向量库添加 {len(documents)} 个文档块...")
            self._vector_store.add_documents(documents)

            total_docs = self._get_document_count()
            logger.info(
                f"文档添加成功 ✓: 本次新增 {len(documents)} 个, "
                f"向量库总计 {total_docs} 个文档块"
            )
            return len(documents)

        except Exception as e:
            logger.error(f"添加文档到向量库失败: {e}", exc_info=True)
            raise RuntimeError(f"向量库写入失败: {e}")

    # =================================================================
    # 文档检索
    # =================================================================

    def similarity_search(
        self,
        query: str,
        k: int = None,
        filter_section: Optional[str] = None,
    ) -> List[Document]:
        """
        执行语义相似度检索。

        Args:
            query: 自然语言查询字符串
            k: 返回的最相关文档数量（默认使用配置值）
            filter_section: 可选的章节过滤（如只搜索 "Methodology" 章节）

        Returns:
            按相关度降序排列的 Document 列表
        """
        if k is None:
            k = settings.RETRIEVAL_TOP_K

        if not self.is_initialized:
            logger.warning("向量库未初始化，返回空检索结果")
            return []

        try:
            # 如果指定了章节过滤，使用带过滤的搜索
            if filter_section:
                results = self._vector_store.similarity_search(
                    query,
                    k=k,
                    filter={"section": filter_section},
                )
            else:
                results = self._vector_store.similarity_search(query, k=k)

            logger.debug(
                f"检索完成: query='{query[:80]}...', "
                f"top_k={k}, results={len(results)}"
            )
            return results

        except Exception as e:
            logger.error(f"向量检索失败: {e}", exc_info=True)
            return []

    def similarity_search_with_score(
        self,
        query: str,
        k: int = None,
    ) -> List[Tuple[Document, float]]:
        """
        带相似度分数的语义检索。

        Args:
            query: 自然语言查询字符串
            k: 返回的最相关文档数量

        Returns:
            List of (Document, score): 分数越低表示越相关（L2 距离）
        """
        if k is None:
            k = settings.RETRIEVAL_TOP_K

        if not self.is_initialized:
            return []

        try:
            results = self._vector_store.similarity_search_with_score(
                query, k=k
            )
            return results
        except Exception as e:
            logger.error(f"带分数的向量检索失败: {e}", exc_info=True)
            return []

    # =================================================================
    # 持久化操作
    # =================================================================

    def save_local(self) -> bool:
        """
        公开的本地保存方法（供外部兼容调用）。

        Chroma PersistentClient 在每次写入时自动持久化到 SQLite，
        此方法保留仅为兼容旧调用方，实际为 no-op。
        """
        if not self.is_initialized:
            logger.warning("向量库未初始化，跳过本地保存")
            return False
        # Chroma 自动持久化，无需手动保存
        logger.debug("Chroma 自动持久化中，无需手动 save_local")
        return True

    def _get_document_count(self) -> int:
        """
        获取向量库中的文档数量。

        Chroma 原生支持 count()，直接返回 collection 中的文档数。
        """
        try:
            return self._vector_store._collection.count()
        except Exception:
            return -1  # 无法确定

    def get_stats(self) -> dict:
        """
        获取向量库的统计信息。

        Returns:
            包含文档数量、存储路径等信息的字典
        """
        return {
            "initialized": self.is_initialized,
            "store_path": str(self._store_path),
            "document_count": self._get_document_count() if self.is_initialized else 0,
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
        }

    # =================================================================
    # 清理操作
    # =================================================================

    def delete_by_title(self, paper_title: str) -> int:
        """
        删除向量库中属于指定论文的所有文档块。

        使用 Chroma 原生的 metadata 过滤 + 批量删除，
        无需全量重建索引。

        Args:
            paper_title: 论文标题（匹配 metadata["title"]）

        Returns:
            移除的文档块数量
        """
        if not self.is_initialized:
            logger.warning("向量库未初始化，无法删除论文向量")
            return 0

        try:
            # 通过 metadata 过滤查找匹配的文档
            result = self._vector_store.get(where={"title": paper_title})
            ids = result["ids"]
            if not ids:
                logger.info(f"向量库中未找到论文 '{paper_title}' 的文档块，跳过")
                return 0

            self._vector_store.delete(ids=ids)
            logger.info(
                f"Chroma 删除完成: '{paper_title}', 移除 {len(ids)} 个文档块"
            )
            return len(ids)

        except Exception as e:
            logger.error(f"从向量库删除论文失败: {e}", exc_info=True)
            raise RuntimeError(f"向量库删除失败: {e}")

    def reset(self) -> bool:
        """
        清空向量库并重新初始化。

        警告: 此操作不可逆，将删除所有已索引的论文数据。
        """
        try:
            logger.warning("正在重置向量库...")
            if self._client is not None:
                try:
                    self._client.delete_collection(self.COLLECTION_NAME)
                except Exception:
                    pass  # collection 可能不存在
            self._vector_store = None
            self._initialized = False
            if self._store_path.exists():
                shutil.rmtree(str(self._store_path))
                logger.info(f"已删除本地向量库目录: {self._store_path}")
            self._create_empty_store()
            logger.info("向量库重置完成 ✓")
            return True
        except Exception as e:
            logger.error(f"向量库重置失败: {e}", exc_info=True)
            return False


# ================================================================
# 全局单例（模块级）
# ================================================================
# 使用模块级变量维护全局唯一的 VectorService 实例，
# 确保所有 API 路由共享同一个向量库。

_vector_service_instance: Optional[VectorService] = None


def get_vector_service() -> VectorService:
    """
    获取全局唯一的 VectorService 实例。

    首次调用时创建实例，后续调用返回同一个实例。
    可用于 LangChain Tool 函数中获取向量服务。

    Returns:
        VectorService 单例实例
    """
    global _vector_service_instance
    if _vector_service_instance is None:
        _vector_service_instance = VectorService()
    return _vector_service_instance
