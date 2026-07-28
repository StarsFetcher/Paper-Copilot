"""
学术文献结构化整理服务模块
===========================
负责根据用户指定的主题或论文名称，检索相关论文内容并生成
遵循标准学术结构的总结报告。

核心流程:
    1. 在向量库中检索与主题相关的论文片段
    2. 对检索结果进行聚合与去重（按论文标题分组）
    3. 使用 LLM 结合标准化模板生成六段式总结报告
    4. 遵循"背景-方法-实验-贡献-局限-展望"的逻辑递进

设计原则:
    - 模板用于指导**结构逻辑**而非字面替换
    - 允许 Agent 根据内容完整性灵活调整篇幅
    - 信息不足处诚实地标注而非编造
"""

from typing import Any, Dict, List

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config.settings import settings
from prompts.templates import (
    SUMMARIZE_SYSTEM_PROMPT,
    SUMMARIZE_USER_TEMPLATE,
)
from service.vector_service import get_vector_service
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SummarizeService:
    """
    文献结构化整理服务

    负责从向量库中检索论文并生成标准化学术总结报告。
    """

    def __init__(self):
        """初始化总结服务"""
        self._llm: ChatOpenAI = None
        logger.info("SummarizeService 实例已创建")

    # =================================================================
    # LLM 懒加载
    # =================================================================

    @property
    def llm(self) -> ChatOpenAI:
        """懒加载 ChatOpenAI 实例"""
        if self._llm is None:
            logger.info(f"正在初始化 Summarize LLM: {settings.LLM_MODEL_NAME}")
            self._llm = ChatOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL_NAME,
                temperature=0.3,  # 稍高温度以生成流畅的综述文本
                max_retries=settings.MAX_RETRIES,
            )
        return self._llm

    # =================================================================
    # 核心方法
    # =================================================================

    def summarize(self, topic: str) -> Dict[str, Any]:
        """
        根据指定主题生成学术总结报告。

        完整流程:
            1. 检索: 在向量库中搜索与主题相关的论文片段
            2. 聚合: 按论文标题对检索结果进行分组与去重
            3. 组装: 将检索内容填入总结 Prompt 模板
            4. 生成: 调用 LLM 生成六段式结构化总结

        Args:
            topic: 用户指定的文献主题或论文名称

        Returns:
            {
                "topic": str,           # 查询主题
                "summary": str,         # 生成的总结报告（Markdown 格式）
                "paper_count": int,     # 涉及的论文数量
                "sources": [...]        # 引用的论文来源列表
            }
        """
        if not topic or not topic.strip():
            return {
                "topic": topic,
                "summary": "请提供有效的文献主题或论文名称。",
                "paper_count": 0,
                "sources": [],
            }

        logger.info(f"收到总结请求: topic='{topic}'")

        try:
            # ----------------------------------------------------------
            # 步骤 1: 检索相关论文片段
            # ----------------------------------------------------------
            vector_service = get_vector_service()
            if not vector_service.is_initialized:
                return {
                    "topic": topic,
                    "summary": "知识库尚未初始化，无法生成总结。请先上传 PDF 论文文件。",
                    "paper_count": 0,
                    "sources": [],
                }

            # 增加检索数量以覆盖更多相关内容
            documents = vector_service.similarity_search(
                query=topic,
                k=settings.RETRIEVAL_TOP_K * 2,  # 检索更多文档以便覆盖全面
            )

            if not documents:
                return {
                    "topic": topic,
                    "summary": (
                        f"在知识库中未找到与「{topic}」相关的论文内容。\n\n"
                        "建议:\n"
                        "1. 检查主题名称的拼写\n"
                        "2. 尝试更宽泛的关键词\n"
                        "3. 上传更多相关领域的论文 PDF"
                    ),
                    "paper_count": 0,
                    "sources": [],
                }

            logger.info(f"检索到 {len(documents)} 个相关片段")

            # ----------------------------------------------------------
            # 步骤 2: 聚合与去重
            # ----------------------------------------------------------
            aggregated = self._aggregate_by_paper(documents)
            logger.info(
                f"聚合后共 {len(aggregated)} 篇论文: "
                f"{list(aggregated.keys())}"
            )

            # ----------------------------------------------------------
            # 步骤 3: 构建上下文文本
            # ----------------------------------------------------------
            context_text = self._build_context(aggregated)

            # ----------------------------------------------------------
            # 步骤 4: 调用 LLM 生成总结
            # ----------------------------------------------------------
            summary = self._generate_summary(
                topic=topic,
                context=context_text,
            )

            # 构建来源列表
            sources = self._build_source_list(aggregated)

            logger.info(
                f"总结生成完成: topic='{topic}', "
                f"papers={len(aggregated)}, "
                f"summary_length={len(summary)}"
            )

            return {
                "topic": topic,
                "summary": summary,
                "paper_count": len(aggregated),
                "sources": sources,
            }

        except Exception as e:
            logger.error(f"总结生成失败: {e}", exc_info=True)
            return {
                "topic": topic,
                "summary": f"生成总结时发生错误: {str(e)}",
                "paper_count": 0,
                "sources": [],
            }

    # =================================================================
    # 内部方法
    # =================================================================

    def _aggregate_by_paper(
        self,
        documents: List[Document],
    ) -> Dict[str, List[Document]]:
        """
        按论文标题对检索结果进行聚合分组。

        同一篇论文的不同章节片段会被归入同一个列表，
        后续按章节顺序排列以保持阅读连贯性。

        Args:
            documents: 检索返回的文档列表

        Returns:
            {论文标题: [文档列表]} 的字典
        """
        aggregated: Dict[str, List[Document]] = {}

        for doc in documents:
            meta = doc.metadata
            # 使用 title 作为主键，fallback 到 file_name
            paper_key = meta.get("title", meta.get("file_name", "未知论文"))

            if paper_key not in aggregated:
                aggregated[paper_key] = []
            aggregated[paper_key].append(doc)

        # 对每篇论文的片段按章节逻辑顺序排列
        section_order = {
            "Abstract": 0,
            "Introduction": 1,
            "Background": 2,
            "Related Work": 3,
            "Methodology": 4,
            "Experiments": 5,
            "Results": 6,
            "Discussion": 7,
            "Conclusion": 8,
        }

        for paper_key in aggregated:
            aggregated[paper_key].sort(
                key=lambda d: section_order.get(
                    d.metadata.get("section", "ZZZ"), 99
                )
            )

        return aggregated

    def _build_context(self, aggregated: Dict[str, List[Document]]) -> str:
        """
        将聚合后的论文内容构建为 Prompt 可用的上下文字符串。

        每篇论文的内容按章节顺序拼接，论文之间用分隔符隔开。

        Args:
            aggregated: 按论文聚合后的文档分组

        Returns:
            格式化的上下文字符串
        """
        parts = []

        for i, (paper_title, docs) in enumerate(aggregated.items(), start=1):
            parts.append(f"\n{'='*70}")
            parts.append(f"论文 {i}: {paper_title}")
            parts.append(f"{'='*70}")

            # 收集这篇论文涉及的所有章节
            sections_seen = set()
            for doc in docs:
                section = doc.metadata.get("section", "其他")
                if section not in sections_seen:
                    sections_seen.add(section)
                    parts.append(f"\n### {section}")
                # 添加文档内容（限制长度避免 Prompt 过长）
                content = doc.page_content.strip()
                if len(content) > 1500:
                    content = content[:1500] + "...(内容已截断)"
                parts.append(content)

            parts.append("")  # 空行分隔

        return "\n".join(parts)

    def _generate_summary(self, topic: str, context: str) -> str:
        """
        使用 LLM 生成结构化学术总结。

        Args:
            topic: 用户指定的主题
            context: 检索到的论文上下文字符串

        Returns:
            Markdown 格式的总结报告
        """
        # 构建用户 Prompt
        user_prompt = SUMMARIZE_USER_TEMPLATE.format(
            topic=topic,
            context=context,
        )

        # 使用 ChatPromptTemplate 构建完整对话
        prompt = ChatPromptTemplate.from_messages([
            ("system", SUMMARIZE_SYSTEM_PROMPT),
            ("human", user_prompt),
        ])

        # 调用 LLM
        messages = prompt.format_messages()
        response = self.llm.invoke(messages)

        return response.content

    def _build_source_list(self, aggregated: Dict[str, List[Document]]) -> List[Dict]:
        """
        构建结构化的论文来源列表。

        Args:
            aggregated: 按论文聚合后的文档分组

        Returns:
            来源信息列表
        """
        sources = []
        for paper_title, docs in aggregated.items():
            # 收集该论文涉及的所有章节
            sections = list(set(
                doc.metadata.get("section", "未知")
                for doc in docs
            ))
            page_range = set()
            for doc in docs:
                ps = doc.metadata.get("page_start")
                pe = doc.metadata.get("page_end")
                if ps:
                    page_range.add(str(ps))

            sources.append({
                "title": paper_title,
                "sections": sorted(sections),
                "pages": sorted(page_range, key=int) if page_range else [],
                "chunk_count": len(docs),
            })

        return sources

    # =================================================================
    # 论文对比分析
    # =================================================================

    def compare(
        self,
        paper_ids: List[str],
        aspect: str = "methods",
    ) -> Dict[str, Any]:
        """
        Generate a comparison report for multiple papers.

        Args:
            paper_ids: List of paper IDs from the paper library
            aspect:    Comparison aspect — "methods", "experiments",
                       "contributions", "limitations", or "overall"

        Returns:
            {
                "aspect": str,
                "paper_count": int,
                "comparison_table": str (Markdown),
                "analysis": str (Markdown),
                "papers": [...]  # Source papers
            }
        """
        from service.paper_library import get_paper_library

        if not paper_ids or len(paper_ids) < 2:
            return {
                "aspect": aspect,
                "paper_count": len(paper_ids),
                "comparison_table": "需要至少 2 篇论文才能生成对比报告.",
                "analysis": "",
                "papers": [],
            }

        logger.info(
            f"Generating comparison: {len(paper_ids)} papers, aspect='{aspect}'"
        )

        # Retrieve paper analyses from library
        library = get_paper_library()
        paper_data = []
        for pid in paper_ids:
            paper = library.get_paper(pid)
            if paper:
                paper_data.append(paper)

        if len(paper_data) < 2:
            return {
                "aspect": aspect,
                "paper_count": len(paper_data),
                "comparison_table": (
                    f"仅找到 {len(paper_data)} 篇论文的分析数据，"
                    "需要至少 2 篇"
                ),
                "analysis": "",
                "papers": paper_data,
            }

        # Build analysis summaries
        analyses_text = self._build_comparison_context(paper_data, aspect)

        # Generate comparison
        from prompts.templates import COMPARISON_PROMPT

        prompt = COMPARISON_PROMPT.format(
            aspect=aspect,
            analyses=analyses_text,
        )

        messages = ChatPromptTemplate.from_messages([
            ("human", prompt),
        ]).format_messages()

        response = self._get_comparison_llm().invoke(messages)

        # Build comparison table from analysis data
        comparison_table = self._build_comparison_table(paper_data, aspect)

        logger.info(
            f"Comparison complete: {len(paper_data)} papers, "
            f"aspect='{aspect}'"
        )

        return {
            "aspect": aspect,
            "paper_count": len(paper_data),
            "comparison_table": comparison_table,
            "analysis": response.content,
            "papers": [
                {
                    "paper_id": p.get("paper_id", ""),
                    "title": p.get("title", ""),
                }
                for p in paper_data
            ],
        }

    def _build_comparison_context(
        self, papers: List[Dict], aspect: str,
    ) -> str:
        """Build analysis context for comparison prompt."""
        parts = []
        for i, paper in enumerate(papers, 1):
            title = paper.get("title", "未知")
            analysis = paper.get("analysis_json", {})

            if isinstance(analysis, str):
                try:
                    import json
                    analysis = json.loads(analysis)
                except json.JSONDecodeError:
                    analysis = {}

            parts.append(f"\n### 论文 {i}: {title}")

            if aspect in ("methods", "overall"):
                parts.append(f"**方法**: {analysis.get('methods', '未提及')}")
            if aspect in ("experiments", "overall"):
                parts.append(f"**实验**: {analysis.get('experiments', '未提及')}")
            if aspect in ("contributions", "overall"):
                contribs = analysis.get("contributions", [])
                if isinstance(contribs, list):
                    parts.append(f"**贡献**: {'; '.join(contribs)}")
            if aspect in ("limitations", "overall"):
                parts.append(f"**局限**: {analysis.get('limitations', '未提及')}")

        return "\n".join(parts)

    def _build_comparison_table(
        self, papers: List[Dict], aspect: str,
    ) -> str:
        """Build a Markdown comparison table."""
        if not papers:
            return ""

        headers = ["论文"]
        if aspect in ("methods", "overall"):
            headers.append("核心方法")
        if aspect in ("experiments", "overall"):
            headers.append("数据集")
            headers.append("关键指标")
        if aspect in ("contributions", "overall"):
            headers.append("主要贡献")

        rows = []
        for paper in papers:
            analysis = paper.get("analysis_json", {})
            if isinstance(analysis, str):
                try:
                    import json
                    analysis = json.loads(analysis)
                except json.JSONDecodeError:
                    analysis = {}

            title = paper.get("title", "未知")[:40]
            row = [title]

            if aspect in ("methods", "overall"):
                methods = analysis.get("methods", "未提及")
                if len(methods) > 60:
                    methods = methods[:60] + "..."
                row.append(methods)

            if aspect in ("experiments", "overall"):
                row.append("未提及")
                row.append("未提及")

            if aspect in ("contributions", "overall"):
                contribs = analysis.get("contributions", [])
                if isinstance(contribs, list):
                    row.append(contribs[0][:50] if contribs else "未提及")
                else:
                    row.append(str(contribs)[:50])

            rows.append(row)

        # Build Markdown table
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = "\n".join(
            "| " + " | ".join(row) + " |" for row in rows
        )

        return f"{header_line}\n{sep_line}\n{data_lines}"

    def _get_comparison_llm(self) -> ChatOpenAI:
        """Get or create a comparison-specialized LLM."""
        if not hasattr(self, '_comparison_llm') or self._comparison_llm is None:
            self._comparison_llm = ChatOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL_NAME,
                temperature=0.3,
                max_retries=settings.MAX_RETRIES,
            )
        return self._comparison_llm


# ================================================================
# 全局单例
# ================================================================

_summarize_service_instance: SummarizeService = None


def get_summarize_service() -> SummarizeService:
    """获取全局唯一的 SummarizeService 实例"""
    global _summarize_service_instance
    if _summarize_service_instance is None:
        _summarize_service_instance = SummarizeService()
    return _summarize_service_instance
