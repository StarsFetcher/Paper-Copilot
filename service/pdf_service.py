"""
PDF 解析与语义切片服务模块
===========================
负责对学术论文 PDF 进行高保真文本提取，并基于学术论文章节结构执行
语义感知的智能切片（Semantic Chunking）。

核心能力:
    1. 使用 PyMuPDF (fitz) 提取文本，处理双栏排版
    2. 识别学术论文的标准章节标题（Abstract, Methodology 等）
    3. 以章节边界为"硬边界"进行文本切片，保证上下文完整性
    4. 对超长章节使用 RecursiveCharacterTextSplitter 进行二次切分
"""

import re
import hashlib
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import fitz  # PyMuPDF

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ======================================================================
# 学术论文章节标题匹配模式
# ======================================================================
# 每个条目为 (规范章节名, [正则模式列表])
# 正则模式按优先级排列，匹配时忽略大小写
# 使用 \n 前缀确保匹配的是行首标题，避免正文中的词汇误匹配
# ======================================================================

ACADEMIC_SECTION_PATTERNS: List[Tuple[str, List[str]]] = [
    (
        "Abstract",
        [
            r"(?:^|\n)\s*abstract\s*\n",
            r"(?:^|\n)\s*abstract\s*[-–—]",
        ],
    ),
    (
        "Introduction",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?introduction\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?intro\s*\n",
        ],
    ),
    (
        "Related Work",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?related\s+work\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?literature\s+review\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?related\s+literature\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?previous\s+work\s*\n",
        ],
    ),
    (
        "Background",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?background\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?preliminar(?:y|ies)\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?problem\s+formulation\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?problem\s+statement\s*\n",
        ],
    ),
    (
        "Methodology",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?method(?:ology|s)?\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?approach\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?proposed\s+method\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?(?:our\s+)?framework\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?(?:our\s+)?model\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?architecture\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?algorithm\s*\n",
        ],
    ),
    (
        "Experiments",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?experiments?(?:\s+setup)?\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?evaluation\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?experimental\s+(?:setup|results|evaluation)\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?empirical\s+(?:study|evaluation)\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?implementation\s+details\s*\n",
        ],
    ),
    (
        "Results",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?results?(?:\s+and\s+(?:analysis|discussion))?\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?experimental\s+results\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?quantitative\s+(?:results|analysis)\s*\n",
        ],
    ),
    (
        "Discussion",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?discussion\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?analysis\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?qualitative\s+(?:analysis|results)\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?case\s+study\s*\n",
        ],
    ),
    (
        "Conclusion",
        [
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?conclusion\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?concluding\s+remarks\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?summary\s*\n",
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)?future\s+work\s*\n",
        ],
    ),
    (
        "References",
        [
            r"(?:^|\n)\s*references?\s*\n",
            r"(?:^|\n)\s*bibliography\s*\n",
        ],
    ),
]

# ======================================================================
# 编译正则模式（预编译以提升性能）
# ======================================================================
COMPILED_SECTIONS: List[Tuple[str, List[re.Pattern]]] = [
    (name, [re.compile(pat, re.IGNORECASE | re.MULTILINE) for pat in patterns])
    for name, patterns in ACADEMIC_SECTION_PATTERNS
]


# ======================================================================
# PDF 解析服务
# ======================================================================

class PDFService:
    """
    学术论文 PDF 解析与语义切片服务

    使用 PyMuPDF (fitz) 作为解析引擎，对双栏排版有较好的处理能力。
    文本提取采用 block 级排序策略，确保双栏场景下的阅读顺序正确。
    """

    def __init__(self):
        """初始化文本分割器"""
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=[
                "\n\n",     # 段落边界（最高优先级）
                "\n",       # 行边界
                ". ",       # 句子边界
                "。",       # 中文句子边界
                " ",        # 单词边界
                "",         # 字符边界（最低优先级）
            ],
            length_function=len,
            is_separator_regex=False,
        )
        logger.info(
            f"PDFService 初始化完成 (chunk_size={settings.CHUNK_SIZE}, "
            f"chunk_overlap={settings.CHUNK_OVERLAP})"
        )

    # ================================================================
    # PDF 文本提取
    # ================================================================

    def extract_text(self, file_data: bytes, file_name: str = "unknown.pdf") -> Tuple[str, Dict]:
        """
        从 PDF 二进制数据中提取全文文本。

        Args:
            file_data: PDF 文件的二进制内容
            file_name: 文件名（用于日志和元数据）

        Returns:
            (extracted_text, metadata) 元组
            - extracted_text: 提取的全文纯文本
            - metadata: 包含页数、文件名、内容哈希等信息的字典

        双栏处理策略:
            使用 fitz 的 block 模式提取文本，按 (y0, x0) 排序 block，
            使得同一水平位置的文本保留在一起（双栏→单栏的重排）。
        """
        metadata = {
            "file_name": file_name,
            "page_count": 0,
            "content_hash": "",
            "extraction_method": "pymupdf",
        }

        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            metadata["page_count"] = len(doc)

            all_pages_text: List[str] = []

            for page_num, page in enumerate(doc, start=1):
                # ----------------------------------------------------------
                # 使用 "blocks" 模式提取，获得按位置组织的文本块
                # 每个 block 包含: (x0, y0, x1, y1, text, block_no, block_type)
                # ----------------------------------------------------------
                blocks = page.get_text("blocks")

                # 过滤掉图片类型的 block
                text_blocks = [
                    b for b in blocks
                    if b[6] == 0 and b[4].strip()  # type=0 为文本块且非空
                ]

                # 按 (y0, x0) 排序：先从上到下，同行内从左到右
                # 使用一个容忍度将同一行的 block 归到一起
                text_blocks.sort(key=lambda b: (b[1] // 20) * 100000 + b[0])

                page_text_parts = []
                for block in text_blocks:
                    block_text = block[4].strip()
                    if block_text:
                        page_text_parts.append(block_text)

                page_text = "\n".join(page_text_parts)

                # 添加页码标记（有助于后续引用溯源）
                page_header = f"\n[Page {page_num}]\n"
                all_pages_text.append(page_header + page_text)

            doc.close()

            full_text = "\n".join(all_pages_text)

            # 计算内容哈希（用于去重判定）
            metadata["content_hash"] = hashlib.md5(full_text.encode("utf-8")).hexdigest()

            logger.info(
                f"PDF 文本提取完成: file={file_name}, "
                f"pages={metadata['page_count']}, "
                f"chars={len(full_text)}"
            )
            return full_text, metadata

        except Exception as e:
            logger.error(f"PDF 文本提取失败: file={file_name}, error={e}", exc_info=True)
            raise ValueError(f"无法解析 PDF 文件 '{file_name}': {e}")

    # ================================================================
    # 语义切片
    # ================================================================

    def semantic_chunk(
        self,
        text: str,
        paper_metadata: Dict,
    ) -> List[Document]:
        """
        对论文全文执行基于学术章节结构的语义切片。

        算法步骤:
            1. 扫描全文，匹配所有学术章节标题的位置
            2. 以章节边界为"硬分割点"将全文切分为多个节
            3. 对标题之前的"前言文本"（如作者信息）特殊处理
            4. 每个节内，若文本超过 chunk_size，使用递归分割器二次切分
            5. 跳过 References 章节（通常不需要向量化）
            6. 为每个 Document 注入丰富的元数据

        Args:
            text: 完整论文文本
            paper_metadata: 论文元数据（标题、文件名等）

        Returns:
            List[langchain_core.documents.Document]: 切片后的文档列表
        """
        # ----------------------------------------------------------
        # 步骤 1: 定位所有章节边界
        # ----------------------------------------------------------
        section_boundaries = self._find_section_boundaries(text)

        if not section_boundaries:
            # 如果没有匹配到任何章节标题，将全文作为一个整体处理
            logger.warning(
                f"未检测到标准学术章节标题，将对全文执行通用切片: "
                f"{paper_metadata.get('file_name', 'unknown')}"
            )
            return self._split_section(
                text=text,
                section_name="Full Text",
                paper_metadata=paper_metadata,
                page_start=1,
            )

        logger.info(
            f"检测到 {len(section_boundaries)} 个章节边界: "
            f"{[s[0] for s in section_boundaries]}"
        )

        # ----------------------------------------------------------
        # 步骤 2: 按章节边界切分文本
        # ----------------------------------------------------------
        documents: List[Document] = []

        # 处理第一章之前的前言文本（作者信息、通讯地址等）
        first_boundary_pos = section_boundaries[0][1]
        preamble_text = text[:first_boundary_pos].strip()
        if preamble_text and len(preamble_text) > 100:
            # 只有当前言足够长时才保留
            preamble_docs = self._split_section(
                text=preamble_text,
                section_name="Preamble",
                paper_metadata=paper_metadata,
                page_start=1,
            )
            documents.extend(preamble_docs)

        # 处理每个章节
        for i, (section_name, start_pos) in enumerate(section_boundaries):
            # 计算当前章节的结束位置
            if i + 1 < len(section_boundaries):
                end_pos = section_boundaries[i + 1][1]
            else:
                end_pos = len(text)

            section_text = text[start_pos:end_pos].strip()

            # 跳过 References 章节（通常不需要检索参考文献内容）
            if section_name.lower() in ("references", "bibliography"):
                logger.debug(f"跳过 References 章节（不参与向量化）")
                continue

            if not section_text or len(section_text) < 20:
                logger.debug(f"跳过空章节或过短章节: {section_name}")
                continue

            # 估算章节起止页码（基于 [Page N] 标记）
            page_start = self._estimate_page(text[:start_pos])
            page_end = self._estimate_page(text[:end_pos])

            # 对章节文本执行二次切片
            section_docs = self._split_section(
                text=section_text,
                section_name=section_name,
                paper_metadata=paper_metadata,
                page_start=page_start,
                page_end=page_end,
            )
            documents.extend(section_docs)

        logger.info(
            f"语义切片完成: 共生成 {len(documents)} 个文档块 "
            f"({len(section_boundaries)} 个章节)"
        )
        return documents

    # ================================================================
    # 内部辅助方法
    # ================================================================

    def _find_section_boundaries(self, text: str) -> List[Tuple[str, int]]:
        """
        在文本中定位所有学术章节标题及其起始位置。

        匹配策略:
            - 遍历所有预定义的章节模式
            - 对每个匹配，记录 (规范章节名, 字符偏移量)
            - 按偏移量排序，去重（同一位置只保留一个匹配）

        Returns:
            List of (章节名称, 起始字符位置)，按位置升序排列
        """
        boundaries: List[Tuple[str, int]] = []

        for section_name, patterns in COMPILED_SECTIONS:
            for pattern in patterns:
                for match in pattern.finditer(text):
                    pos = match.start()
                    boundaries.append((section_name, pos))
                    break  # 每个章节名只匹配第一个模式（优先级）

        # 按位置排序
        boundaries.sort(key=lambda x: x[1])

        # 去重：如果两个章节边界太近（<50 字符），只保留第一个
        deduplicated: List[Tuple[str, int]] = []
        for name, pos in boundaries:
            if not deduplicated or (pos - deduplicated[-1][1]) >= 50:
                deduplicated.append((name, pos))

        return deduplicated

    def _split_section(
        self,
        text: str,
        section_name: str,
        paper_metadata: Dict,
        page_start: int = 1,
        page_end: Optional[int] = None,
    ) -> List[Document]:
        """
        对单个章节的文本执行递归字符切片。

        如果章节文本长度未超过 chunk_size，则不进行额外切分，
        直接将整个章节作为一个文档块返回。

        Args:
            text: 章节的完整文本
            section_name: 章节名称（如 "Methodology"）
            paper_metadata: 论文级别的元数据
            page_start: 章节起始页码
            page_end: 章节结束页码（可选）

        Returns:
            List[Document]: 切片后的文档列表
        """
        if page_end is None:
            page_end = page_start

        # 对短章节不做切分
        if len(text) <= settings.CHUNK_SIZE:
            meta = {
                **paper_metadata,
                "section": section_name,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": 0,
            }
            return [Document(page_content=text, metadata=meta)]

        # 对长章节执行递归切分
        chunks = self.text_splitter.split_text(text)

        documents = []
        for i, chunk in enumerate(chunks):
            # 丰富元数据
            meta = {
                **paper_metadata,
                "section": section_name,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": i,
                "chunk_total": len(chunks),
            }
            documents.append(Document(page_content=chunk, metadata=meta))

        return documents

    def _estimate_page(self, text: str) -> int:
        """
        通过文本中的 [Page N] 标记估算当前页码。

        这是一个近似方法，用于在切片元数据中提供大致的页面引用。

        Args:
            text: 当前位置之前的全部文本

        Returns:
            估算的页码（从 1 开始）
        """
        # 找到所有 [Page N] 标记
        matches = re.findall(r"\[Page\s+(\d+)\]", text)
        if matches:
            return int(matches[-1])
        return 1

    # ================================================================
    # 论文元数据提取（基础版）
    # ================================================================

    def extract_paper_metadata(self, text: str, file_name: str) -> Dict:
        """
        从论文文本中尝试提取基本元数据（标题、作者等）。

        当前版本使用基于规则的简单提取，后续可升级为 NLP 模型。

        Args:
            text: 论文全文文本
            file_name: 原始文件名

        Returns:
            包含提取元数据的字典
        """
        metadata = {
            "title": file_name,
            "authors": "Unknown",
            "file_name": file_name,
        }

        # 尝试从 Abstract 前的文本中提取标题（通常是前几行）
        # 找第一个实质性的非空行作为候选标题
        lines = text.split("\n")
        candidate_lines = []
        for line in lines[:50]:  # 只在前 50 行中寻找
            stripped = line.strip()
            if not stripped:
                if candidate_lines:
                    break  # 连续空行，标题块结束
                continue
            if re.match(r"^(?:[Pp]age\s*\d+|\[\s*Page|arXiv|DOI|http)", stripped):
                continue  # 跳过页码、URL 等
            candidate_lines.append(stripped)

        if candidate_lines:
            # 使用第一个足够长的行作为论文标题
            for line in candidate_lines:
                if len(line) > 20:
                    metadata["title"] = line[:200]  # 截断过长的标题
                    break

        return metadata
