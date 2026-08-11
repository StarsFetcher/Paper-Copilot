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
        从 PDF 二进制数据中提取全文文本及元数据。

        Args:
            file_data: PDF 文件的二进制内容
            file_name: 文件名（用于日志和元数据）

        Returns:
            (extracted_text, metadata) 元组
            - extracted_text: 提取的全文纯文本
            - metadata: 包含页数、文件名、内容哈希、PDF元数据等信息的字典
        """
        metadata = {
            "file_name": file_name,
            "page_count": 0,
            "content_hash": "",
            "extraction_method": "pymupdf",
            "pdf_metadata": {},
            "first_page_fonts": [],
        }

        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            metadata["page_count"] = len(doc)

            # --- 提取 PDF 内嵌元数据 ---
            pdf_meta = doc.metadata or {}
            metadata["pdf_metadata"] = {
                "title": pdf_meta.get("title", ""),
                "author": pdf_meta.get("author", ""),
                "subject": pdf_meta.get("subject", ""),
                "keywords": pdf_meta.get("keywords", ""),
                "creator": pdf_meta.get("creator", ""),
                "producer": pdf_meta.get("producer", ""),
            }

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

                # --- 在第一页收集字体信息（用于标题检测）---
                if page_num == 1:
                    page_fonts = []
                    for block in text_blocks:
                        block_text = block[4].strip()
                        # 获取 block 内文字的详细 span 信息
                        try:
                            # 用 "dict" 模式获取富文本信息
                            text_dict = page.get_text("dict", clip=(
                                block[0], block[1], block[2], block[3]
                            ))
                            for b2 in text_dict.get("blocks", []):
                                for line in b2.get("lines", []):
                                    for span in line.get("spans", []):
                                        page_fonts.append({
                                            "text": span.get("text", "").strip(),
                                            "size": span.get("size", 0),
                                            "font": span.get("font", ""),
                                            "bold": "Bold" in span.get("font", ""),
                                            "y": span.get("bbox", [0,0,0,0])[1],
                                        })
                        except Exception:
                            pass
                    metadata["first_page_fonts"] = page_fonts[:200]  # 限制数量

                # 按 (y0, x0) 排序：先从上到下，同行内从左到右
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
        对单个章节执行层级化结构感知切片。

        策略（逐级下钻）:
            1. 章节不超过 MAX_CHUNK → 整个作为 1 个块（保留完整论证）
            2. 超过 → 按子节标题切分
            3. 子节仍过长 → 按段落切分
            4. 段落仍过长 → 按句子切分（最后手段）
            5. 相邻短块合并，控制最终大小在 TARGET_SIZE 附近
        """
        if page_end is None:
            page_end = page_start

        target_size = getattr(settings, 'STRUCTURAL_CHUNK_TARGET', 1200)
        max_size = getattr(settings, 'STRUCTURAL_CHUNK_MAX', 2000)

        # 章节较短 → 完整保留
        if len(text) <= target_size:
            return [Document(page_content=text, metadata={
                **paper_metadata,
                "section": section_name,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": 0,
                "chunk_total": 1,
            })]

        # ── 步骤 1: 按子节标题切分 ──
        subsections = self._find_subsections(text)

        if not subsections:
            # 没有检测到子节 → 直接按段落切分
            subsections = [("", 0)]

        # ── 步骤 2: 每个子节内部按段落切分 ──
        atomic_blocks: List[Dict] = []  # {text, level, heading}

        for i, (sub_heading, sub_start) in enumerate(subsections):
            if i + 1 < len(subsections):
                sub_end = subsections[i + 1][1]
            else:
                sub_end = len(text)

            sub_text = text[sub_start:sub_end].strip()
            if not sub_text:
                continue

            # 将该子节按段落拆分为原子块
            paragraphs = self._split_paragraphs(sub_text)
            for para in paragraphs:
                if para.strip():
                    atomic_blocks.append({
                        "text": para.strip(),
                        "level": "subsection" if sub_heading else "paragraph",
                        "heading": sub_heading,
                    })

        if not atomic_blocks:
            # 回退：整个文本作为一个块
            return [Document(page_content=text[:max_size], metadata={
                **paper_metadata,
                "section": section_name,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": 0,
                "chunk_total": 1,
            })]

        # ── 步骤 3: 智能合并相邻块 ──
        chunks = self._merge_atomic_blocks(atomic_blocks, target_size, max_size)

        # ── 步骤 4: 为每个块添加结构化的上下文前缀 ──
        documents = []
        for i, chunk_text in enumerate(chunks):
            # 提取该块涉及的子节标题作为上下文
            context_prefix = self._build_chunk_context(
                chunk_text, atomic_blocks, section_name
            )

            final_text = context_prefix + "\n\n" + chunk_text if context_prefix else chunk_text

            meta = {
                **paper_metadata,
                "section": section_name,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": i,
                "chunk_total": len(chunks),
                "chunk_method": "structural",
            }
            documents.append(Document(page_content=final_text, metadata=meta))

        logger.debug(
            f"[{section_name}] 结构切片: {len(atomic_blocks)} 原子块 "
            f"→ {len(documents)} 文档块 (target={target_size})"
        )
        return documents

    # ─── 子节检测 ───

    # 匹配子节标题模式:
    #   "3.1 Network Architecture"  /  "3.1.1 Backbone"
    #   "A. Dataset Statistics"     /  "Training Protocol"
    #   "### 4.2 Evaluation"        /  "**Baseline Models**"
    SUBSECTION_PATTERN = re.compile(
        r"(?:^|\n)\s*"
        r"(?:"
        r"(?:#{1,4}\s*)"                         # Markdown heading
        r"|(?:\d+(?:\.\d+)*[\.\)]\s+)"            # 3.1. / 3.1)
        r"|(?:[A-Z]\.(?:\d+)?\s+)"                # A. / B.1
        r"|(?:\*\*[^*]+\*\*\s*$)"                 # **bold heading**
        r")"
        r".{2,80}"                                  # 标题文本
        r"(?:\n|$)",
        re.MULTILINE,
    )

    def _find_subsections(self, text: str) -> List[Tuple[str, int]]:
        """
        在章节文本中检测子节标题及其位置。

        返回: [(子节标题, 起始字符位置), ...]
        """
        matches = []
        for m in self.SUBSECTION_PATTERN.finditer(text):
            heading = m.group().strip()
            pos = m.start()
            # 跳过页码标记行
            if re.match(r'^\s*\[Page\s+\d+\]', heading):
                continue
            matches.append((heading, pos))

        # 去重：相邻匹配间距 < 30 字符的只保留第一个
        deduped = []
        for heading, pos in matches:
            if not deduped or (pos - deduped[-1][1]) >= 30:
                deduped.append((heading, pos))

        return deduped

    # ─── 段落切分 ───

    def _split_paragraphs(self, text: str) -> List[str]:
        """
        将文本按段落边界拆分，保留段落完整性。

        段落分隔符: 双换行、单换行后跟大写字母/数字（新段落开始）
        """
        # 先按双换行拆分（明确的段落边界）
        raw = re.split(r'\n\s*\n', text)
        paragraphs = []
        for block in raw:
            block = block.strip()
            if not block:
                continue
            # 尝试在单换行处进一步拆分（如果看起来像新段落）
            sub_paras = self._split_at_paragraph_starts(block)
            paragraphs.extend(sub_paras)
        return paragraphs

    def _split_at_paragraph_starts(self, text: str) -> List[str]:
        """在看起来是新段落开头的单换行处切分"""
        lines = text.split('\n')
        if len(lines) <= 1:
            return [text] if text.strip() else []

        result = []
        current = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                current.append(line)
                continue
            # 检测新段落起始标志
            is_new_para = bool(re.match(
                r'^(?:'
                r'(?:\d+[\.\)]\s)'                # 编号开头 "1. "
                r'|(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}[\.:]\s)'  # "Training Protocol:"
                r'|(?:\((?:i+|iv|v|vi+)\)\s)'    # (i) (ii) (iii)
                r'|(?:[•\-\*•]\s)'           # bullet points
                r')',
                stripped,
            ))
            if is_new_para and current:
                result.append('\n'.join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            result.append('\n'.join(current))

        return [r for r in result if r.strip()]

    # ─── 智能合并 ───

    def _merge_atomic_blocks(
        self,
        blocks: List[Dict],
        target_size: int,
        max_size: int,
    ) -> List[str]:
        """
        将原子块合并为最终文档块。

        规则:
            - 同一子节内的连续段落优先合并
            - 合并后大小尽量接近 target_size
            - 单个块不超过 max_size
            - 保持子节边界不跨块（新的子节标题行 = 新块起点）
        """
        if not blocks:
            return []

        merged = []
        current_parts = []
        current_len = 0
        current_heading = ""

        def flush():
            nonlocal current_parts, current_len, current_heading
            if current_parts:
                merged.append('\n\n'.join(current_parts))
                current_parts = []
                current_len = 0
                current_heading = ""

        for block in blocks:
            text = block["text"]
            heading = block.get("heading", "")
            t_len = len(text)

            # 子节标题变化 → 开始新块（保持子节边界完整）
            if heading and heading != current_heading and current_parts:
                flush()

            current_heading = heading or current_heading

            # 单段过长 → 按句子切分（最后手段）
            if t_len > max_size:
                flush()
                sub_parts = self._split_long_paragraph(text, target_size, max_size)
                for sp in sub_parts:
                    merged.append(sp)
                current_heading = ""
                continue

            # 加入后不超过 target_size → 继续累积
            join_len = current_len + t_len + (2 if current_parts else 0)
            if join_len <= target_size:
                current_parts.append(text)
                current_len = join_len
            # 加入后不超过 max_size 且当前块还很短 → 继续
            elif current_len < target_size * 0.5 and join_len <= max_size:
                current_parts.append(text)
                current_len = join_len
            # 否则 → flush 并开始新块
            else:
                flush()
                current_parts.append(text)
                current_len = t_len
                current_heading = heading

        flush()
        return merged

    def _split_long_paragraph(
        self,
        text: str,
        target_size: int,
        max_size: int,
    ) -> List[str]:
        """
        对超长段落按句子边界切分（保留句子完整性）。

        只在段落超过 max_size 时才使用，是最后的切分手段。
        切分后尝试将相邻短句合并到接近 target_size。
        """
        # 按句子分割（保留分隔符）
        sentences = re.split(r'(?<=[.!?。！？])\s+', text)
        if len(sentences) <= 1:
            # 无法按句子切分 → 只能硬切
            return [text[i:i+max_size] for i in range(0, len(text), max_size)]

        # 贪心合并句子
        chunks = []
        current = []
        current_len = 0
        for sent in sentences:
            s_len = len(sent)
            if current_len + s_len <= target_size:
                current.append(sent)
                current_len += s_len
            elif current_len + s_len <= max_size:
                current.append(sent)
                current_len += s_len
                # 达到目标大小附近 → flush
                if current_len >= target_size * 0.8:
                    chunks.append(' '.join(current))
                    current = []
                    current_len = 0
            else:
                if current:
                    chunks.append(' '.join(current))
                current = [sent]
                current_len = s_len

        if current:
            chunks.append(' '.join(current))

        return chunks

    # ─── 上下文前缀 ───

    def _build_chunk_context(
        self,
        chunk_text: str,
        all_blocks: List[Dict],
        section_name: str,
    ) -> str:
        """
        为文档块构建结构上下文前缀。

        包含: 当前所属的子节标题，帮助检索时理解该块的论证位置。
        只对非第一个子节、非开头的块添加上下文。
        """
        # 查找当前块属于哪个子节
        chunk_start = chunk_text[:60]
        current_heading = ""
        for block in all_blocks:
            if block["text"][:60] == chunk_start:
                current_heading = block.get("heading", "")
                break

        if not current_heading or current_heading == all_blocks[0].get("heading", ""):
            return ""  # 第一个子节不需要额外上下文

        return f"[{section_name} → {current_heading.strip()}]"

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
    # 论文元数据提取（多策略版）
    # ================================================================

    def extract_paper_metadata(
        self,
        text: str,
        file_name: str,
        extract_meta: Optional[Dict] = None,
    ) -> Dict:
        """
        从论文文本和 PDF 元数据中提取标题、作者、来源等信息。

        采用多策略级联:
            1. PyMuPDF PDF 内嵌元数据 (title, author)
            2. 字体大小启发式检测（首页最大字体 = 标题）
            3. 正则匹配作者/affiliation/email 模式
            4. arXiv ID / DOI 提取 + API 查询
            5. 基于 LLM 的智能提取（兜底）

        Args:
            text: 论文全文文本
            file_name: 原始文件名
            extract_meta: extract_text() 返回的元数据字典（含 pdf_metadata, first_page_fonts）

        Returns:
            包含提取元数据的字典
        """
        result = {
            "title": "",
            "authors": "",
            "file_name": file_name,
            "source": "",       # arxiv / doi / publisher
            "source_id": "",    # arxiv ID or DOI
            "year": "",
            "extraction_method": "heuristic",
        }

        extract_meta = extract_meta or {}

        # ─── 策略 1: PyMuPDF PDF 内嵌元数据 ───
        pdf_meta = extract_meta.get("pdf_metadata", {})
        if pdf_meta.get("title"):
            result["title"] = self._clean_title(pdf_meta["title"])
            result["extraction_method"] = "pdf_metadata"
        if pdf_meta.get("author"):
            result["authors"] = self._clean_authors(pdf_meta["author"])

        # ─── 策略 2: 字体大小启发式检测标题 ───
        if not result["title"]:
            font_title = self._detect_title_by_font_size(extract_meta)
            if font_title:
                result["title"] = font_title
                result["extraction_method"] = "font_size"

        # ─── 策略 3: 文本启发式 ───
        # 从文本首部提取作者行
        if not result["authors"] or result["authors"] == "Unknown":
            text_authors = self._extract_authors_from_preamble(text)
            if text_authors:
                result["authors"] = text_authors

        # 如果标题仍为空，从文本首部回退提取
        if not result["title"]:
            text_title = self._detect_title_from_text(text, file_name)
            if text_title:
                result["title"] = text_title
                result["extraction_method"] = "text_heuristic"

        # ─── 策略 4: arXiv ID / DOI 提取 ───
        arxiv_id, doi = self._extract_identifiers(text)
        if arxiv_id:
            result["source"] = "arxiv"
            result["source_id"] = arxiv_id
        if doi:
            if not result["source"]:
                result["source"] = "doi"
            result["source_id"] = result["source_id"] or doi

        # ─── 策略 5: 年份提取 ───
        result["year"] = self._extract_year(text)

        # ─── 兜底: 文件名清理 ───
        if not result["title"]:
            cleaned = file_name
            cleaned = re.sub(r'\.pdf$', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'[_-]', ' ', cleaned)
            cleaned = re.sub(r'\d{4}\s*', '', cleaned)  # 去掉年份
            cleaned = re.sub(r'arXiv\d+', '', cleaned)   # 去掉 arXiv ID
            cleaned = cleaned.strip()
            if len(cleaned) > 10:
                result["title"] = cleaned
                result["extraction_method"] = "filename"

        # ─── 最终兜底 ───
        if not result["title"]:
            result["title"] = file_name
        if not result["authors"]:
            result["authors"] = "Unknown"

        logger.info(
            f"元数据提取完成: title='{result['title'][:60]}...', "
            f"authors='{result['authors'][:40]}...', "
            f"method={result['extraction_method']}, "
            f"source={result['source']}"
        )
        return result

    # ─── 辅助方法 ───

    def _clean_title(self, title: str) -> str:
        """清理标题文本"""
        t = title.strip()
        # 去掉多余的换行和空白
        t = re.sub(r'\s+', ' ', t)
        # 截断过长的标题
        if len(t) > 300:
            t = t[:300]
        return t

    def _clean_authors(self, authors: str) -> str:
        """清理作者文本"""
        a = authors.strip()
        a = re.sub(r'\s+', ' ', a)
        # 截断过长的作者列表
        if len(a) > 500:
            a = a[:500]
        return a

    def _detect_title_by_font_size(self, extract_meta: Dict) -> str:
        """通过首页最大字体检测标题"""
        fonts = extract_meta.get("first_page_fonts", [])
        if not fonts:
            return ""

        # 找出现在页面顶部 30% 区域内的最大字体文本
        max_y = max((f.get("y", 0) for f in fonts), default=0)
        top_threshold = max_y * 0.3

        # 筛选顶部区域的大字体文本
        top_fonts = [f for f in fonts if f.get("y", 0) < top_threshold and f.get("text")]
        if not top_fonts:
            top_fonts = [f for f in fonts if f.get("text")]

        # 找最大字号
        max_size = max((f.get("size", 0) for f in top_fonts), default=0)
        if max_size < 12:
            return ""

        # 收集最大字号的文本片段（允许小一级的字体也在标题中）
        title_parts = []
        for f in top_fonts:
            if f["size"] >= max_size * 0.85:
                title_parts.append(f["text"])

        # 合并并清理
        title = " ".join(title_parts).strip()
        title = re.sub(r'\s+', ' ', title)

        if len(title) > 15:
            return title[:300]
        return ""

    def _detect_title_from_text(self, text: str, file_name: str) -> str:
        """从文本首部回退提取标题"""
        lines = text.split("\n")
        candidate_lines = []
        for line in lines[:80]:
            stripped = line.strip()
            if not stripped:
                if candidate_lines:
                    break
                continue
            # 跳过明显的非标题行
            if re.match(
                r"^(?:[Pp]age\s*\d+|\[\s*Page|arXiv:|DOI:|http|www\.|"
                r"\d+[\.\)]\s+|Published|Accepted|Received|Copyright|©|"
                r"Correspondence|Email:|E-mail:|Tel[:.]|Fax[:.]|"
                r"Submitted|Revised|Vol\.|Issue|pp\.|Proceedings)",
                stripped,
            ):
                continue
            candidate_lines.append(stripped)

        if candidate_lines:
            for line in candidate_lines:
                if len(line) > 20 and len(line) < 300:
                    return line
        return ""

    def _extract_authors_from_preamble(self, text: str) -> str:
        """从文本前部提取作者信息"""
        lines = text.split("\n")
        preamble_lines = lines[:min(120, len(lines))]

        author_candidates = []
        found_abstract = False

        for line in preamble_lines:
            stripped = line.strip()

            # 检测到 Abstract 就停止搜索作者
            if re.match(r'^(?:abstract|a b s t r a c t)\s*$', stripped, re.IGNORECASE):
                found_abstract = True
                break

            # 跳过明显的非作者行
            if re.match(
                r"^(?:[Pp]age\s*\d+|\[\s*Page|arXiv:|DOI:|http|www\.|"
                r"\d+[\.\)]\s+|Published|Accepted|Received|Copyright|©|"
                r"Correspondence|Email:|E-mail:|Tel[:.]|Fax[:.])\s*",
                stripped,
            ):
                continue

            # 匹配作者特征:
            # - 包含逗号分隔的多个名字
            # - 包含数字上标 (affiliation markers) 如 "1,2" "1,2,3"
            # - 包含特殊符号: †, ‡, *, ✉
            # - 包含 @ 的 email
            # - 长度适中 (20-500 字符)

            has_affiliation_markers = bool(re.search(r'[\d,\s]+(?:\*|†|‡|✉)', stripped))
            has_superscript_numbers = bool(re.search(r'\b\d{1,2}(?:,\d{1,2})*\b', stripped))
            has_emails = '@' in stripped
            has_multiple_names = stripped.count(',') >= 2 or ' and ' in stripped.lower()

            score = 0
            if has_affiliation_markers: score += 3
            if has_emails: score += 3
            if has_superscript_numbers and len(stripped) > 20: score += 2
            if has_multiple_names: score += 2
            if len(stripped) > 30 and len(stripped) < 600: score += 1
            if re.search(r'[A-Z][a-z]+\s+[A-Z][a-z]+', stripped): score += 1  # Capitalized names

            if score >= 3:
                author_candidates.append(stripped)

        if author_candidates:
            # 选择得分最高的
            return author_candidates[0][:500]

        return ""

    def _extract_identifiers(self, text: str) -> Tuple[str, str]:
        """提取 arXiv ID 和 DOI"""
        arxiv_id = ""
        doi = ""

        # arXiv ID 模式: arXiv:XXXX.XXXXX 或 arXiv:XXXX/XXXXXXX
        arxiv_match = re.search(
            r'(?:arXiv\s*[:#]\s*|arxiv\.org/abs/)(\d{4}\.\d{4,5}(?:v\d+)?)',
            text, re.IGNORECASE,
        )
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)
        else:
            # 老式 arXiv ID
            arxiv_match2 = re.search(
                r'(?:arXiv\s*[:#]\s*|arxiv\.org/abs/)([a-z-]+/\d{7}(?:v\d+)?)',
                text, re.IGNORECASE,
            )
            if arxiv_match2:
                arxiv_id = arxiv_match2.group(1)

        # DOI 模式: 10.XXXX/XXXXXXX
        doi_match = re.search(
            r'(?:doi\s*[:#]?\s*|doi\.org/)(10\.\d{4,}/[^\s]+)',
            text, re.IGNORECASE,
        )
        if doi_match:
            doi = re.sub(r'[;,.\)\}]+$', '', doi_match.group(1))
        else:
            # 更宽松的 DOI 提取
            doi_match2 = re.search(r'\b(10\.\d{4,}/[^\s]{5,})\b', text)
            if doi_match2:
                doi = re.sub(r'[;,.\)\}]+$', '', doi_match2.group(1))

        return arxiv_id, doi

    def _extract_year(self, text: str) -> str:
        """从文本提取发表年份"""
        # 在前几行中搜索年份
        head = "\n".join(text.split("\n")[:60])

        # 常见模式: (2024), Published: 2024, © 2024
        year_match = re.search(
            r'(?:©|Copyright|Published|Accepted|Received).*?(19\d{2}|20\d{2})',
            head, re.IGNORECASE,
        )
        if year_match:
            return year_match.group(1)

        # arXiv ID 中包含年份
        arxiv_match = re.search(r'arXiv\s*[:#]\s*(\d{4})', head, re.IGNORECASE)
        if arxiv_match:
            return arxiv_match.group(1)

        # 文件名的年份
        return ""
