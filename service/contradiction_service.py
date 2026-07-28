"""
跨论文矛盾检测服务模块
=======================
负责对多篇学术论文中关于同一主题的论述进行对比分析，自动发现
结论矛盾、实验设置差异，并生成结构化的矛盾分析报告。

核心流程:
    1. 广泛检索向量库中与主题相关的论文片段（3倍常规检索量）
    2. 按论文标题聚合与按章节排序
    3. 至少需要 2 篇论文才能启动分析
    4. 构建对比上下文，让 LLM 看到所有论文的 claims 并排展示
    5. LLM 分析并返回结构化 JSON（矛盾点、一致点、实验对比表）

设计原则:
    - 温度设为 0.0，确保矛盾判断的确定性
    - JSON 输出便于前端结构化展示
    - 论文不足时不调用 LLM，节省 API 开销
    - 不在启动时预热（低频功能，按需加载）
"""

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config.settings import settings
from prompts.templates import (
    CONTRADICTION_SYSTEM_PROMPT,
    CONTRADICTION_USER_TEMPLATE,
)
from service.vector_service import get_vector_service
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ContradictionService:
    """
    跨论文矛盾检测服务

    负责对比分析多篇论文对同一主题的论述，自动发现矛盾与一致点。
    """

    def __init__(self):
        """初始化矛盾检测服务"""
        self._llm: ChatOpenAI = None
        logger.info("ContradictionService 实例已创建")

    # =================================================================
    # LLM 懒加载
    # =================================================================

    @property
    def llm(self) -> ChatOpenAI:
        """
        懒加载 ChatOpenAI 实例。

        使用极低温度（0.0）以确保矛盾判断的确定性，
        这是检测类任务（而非创意生成类任务）的最佳实践。
        """
        if self._llm is None:
            logger.info(
                f"正在初始化 Contradiction LLM: model={settings.LLM_MODEL_NAME}, "
                f"temperature={settings.CONTRADICTION_TEMPERATURE}"
            )
            self._llm = ChatOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL_NAME,
                temperature=settings.CONTRADICTION_TEMPERATURE,
                max_retries=settings.MAX_RETRIES,
            )
        return self._llm

    # =================================================================
    # 核心方法
    # =================================================================

    def detect_contradictions(self, topic: str) -> Dict[str, Any]:
        """
        检测多篇论文中关于指定主题的矛盾与一致观点。

        完整流程:
            1. 检索: 在向量库中广泛搜索与主题相关的论文片段
            2. 聚合: 按论文标题分组，按章节排序
            3. 检查: 确认至少有 2 篇论文，否则返回提示
            4. 构建: 将多篇论文的 claims 并排展示为对比上下文
            5. 分析: 调用 LLM 生成结构化矛盾分析（JSON）
            6. 组装: 收集来源信息并返回完整结果

        Args:
            topic: 用户指定的研究主题或分析问题

        Returns:
            {
                "topic": str,
                "papers_analyzed": int,
                "contradictions": [...],
                "agreements": [...],
                "experiment_comparison_table": str,
                "summary": str,
                "sources": [...]
            }
        """
        # ----------------------------------------------------------
        # 步骤 0: 输入校验
        # ----------------------------------------------------------
        if not topic or not topic.strip():
            return self._degraded_response(
                topic=topic,
                message="请提供有效的分析主题或研究问题。",
            )

        logger.info(f"收到矛盾检测请求: topic='{topic}'")

        try:
            # ----------------------------------------------------------
            # 步骤 1: 广泛检索
            # ----------------------------------------------------------
            vector_service = get_vector_service()
            if not vector_service.is_initialized:
                return self._degraded_response(
                    topic=topic,
                    message="知识库尚未初始化，请先上传 PDF 论文文件。",
                )

            documents = vector_service.similarity_search(
                query=topic,
                k=settings.CONTRADICTION_RETRIEVAL_TOP_K,
            )

            if not documents:
                return self._degraded_response(
                    topic=topic,
                    message=(
                        f"在知识库中未找到与「{topic}」相关的论文内容。\n\n"
                        "建议:\n"
                        "1. 检查主题名称的拼写\n"
                        "2. 尝试更宽泛的关键词\n"
                        "3. 上传更多相关领域的论文 PDF"
                    ),
                )

            logger.info(f"检索到 {len(documents)} 个相关片段")

            # ----------------------------------------------------------
            # 步骤 2: 按论文标题聚合
            # ----------------------------------------------------------
            aggregated = self._aggregate_by_paper(documents)
            paper_count = len(aggregated)
            logger.info(
                f"聚合后共 {paper_count} 篇论文: {list(aggregated.keys())}"
            )

            # ----------------------------------------------------------
            # 步骤 3: 论文数量检查
            # ----------------------------------------------------------
            if paper_count < 2:
                return self._degraded_response(
                    topic=topic,
                    message=(
                        f"当前找到 {paper_count} 篇论文，至少需要 2 篇论文"
                        f"才能进行矛盾检测。请尝试更宽泛的主题，"
                        f"或上传更多相关论文。"
                    ),
                    papers_analyzed=paper_count,
                    sources=self._build_source_list(aggregated),
                )

            # ----------------------------------------------------------
            # 步骤 4: 构建对比上下文
            # ----------------------------------------------------------
            context_text = self._build_context(aggregated)

            # ----------------------------------------------------------
            # 步骤 5: LLM 矛盾分析
            # ----------------------------------------------------------
            result = self._generate_analysis(topic=topic, context=context_text)

            # ----------------------------------------------------------
            # 步骤 6: 组装最终响应
            # ----------------------------------------------------------
            sources = self._build_source_list(aggregated)

            contradictions = result.get("contradictions", [])
            agreements = result.get("agreements", [])

            logger.info(
                f"矛盾检测完成: topic='{topic}', "
                f"papers={paper_count}, "
                f"contradictions={len(contradictions)}, "
                f"agreements={len(agreements)}"
            )

            return {
                "topic": topic,
                "papers_analyzed": paper_count,
                "contradictions": contradictions,
                "agreements": agreements,
                "experiment_comparison_table": result.get(
                    "experiment_comparison_table", ""
                ),
                "summary": result.get("summary", "未能生成矛盾分析总结。"),
                "sources": sources,
            }

        except Exception as e:
            logger.error(f"矛盾检测失败: {e}", exc_info=True)
            return self._degraded_response(
                topic=topic,
                message=f"矛盾检测过程发生错误: {str(e)}",
            )

    # =================================================================
    # 内部方法
    # =================================================================

    def _aggregate_by_paper(
        self, documents: List[Any],
    ) -> Dict[str, List[Any]]:
        """
        按论文标题对检索结果进行聚合分组，
        并按学术章节逻辑顺序排列每篇论文的片段。

        与 SummarizeService._aggregate_by_paper 逻辑一致。
        """
        aggregated: Dict[str, List[Any]] = {}

        for doc in documents:
            meta = doc.metadata
            paper_key = meta.get("title", meta.get("file_name", "未知论文"))
            if paper_key not in aggregated:
                aggregated[paper_key] = []
            aggregated[paper_key].append(doc)

        # 按学术章节逻辑顺序排列
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
                    d.metadata.get("section", "ZZZ"), 99,
                )
            )

        return aggregated

    def _build_context(
        self, aggregated: Dict[str, List[Any]],
    ) -> str:
        """
        构建跨论文对比上下文。

        每篇论文的内容以标记块呈现，章节作为子标题，
        便于 LLM 进行并排对比分析。
        """
        parts = []

        for i, (paper_title, docs) in enumerate(aggregated.items(), start=1):
            parts.append(f"\n{'='*70}")
            parts.append(f"论文 {i}: {paper_title}")
            parts.append(f"{'='*70}")

            sections_seen = set()
            for doc in docs:
                section = doc.metadata.get("section", "其他")
                if section not in sections_seen:
                    sections_seen.add(section)
                    parts.append(f"\n### [{section}]")

                content = doc.page_content.strip()
                # 截断过长内容，保持上下文可管理
                if len(content) > 1500:
                    content = content[:1500] + "...(内容已截断)"
                parts.append(content)

            parts.append("")

        return "\n".join(parts)

    def _generate_analysis(
        self, topic: str, context: str,
    ) -> Dict[str, Any]:
        """
        调用 LLM 生成矛盾分析。

        LLM 返回 JSON 字符串，可能包含 markdown 代码块包裹。
        _extract_json 负责处理各种输出格式。
        """
        user_prompt = CONTRADICTION_USER_TEMPLATE.format(
            topic=topic,
            context=context,
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", CONTRADICTION_SYSTEM_PROMPT),
            ("human", user_prompt),
        ])

        messages = prompt.format_messages()

        try:
            response = self.llm.invoke(messages)
            raw_content = response.content.strip()

            parsed = self._extract_json(raw_content)

            if parsed is None:
                logger.warning(
                    "LLM 返回内容无法解析为 JSON，返回降级结果"
                )
                logger.debug(f"原始输出（前500字符）: {raw_content[:500]}")
                return {
                    "contradictions": [],
                    "agreements": [],
                    "experiment_comparison_table": "",
                    "summary": "LLM 返回格式异常，无法解析矛盾分析结果。请重试。",
                }

            return parsed

        except Exception as e:
            logger.error(f"LLM 分析调用失败: {e}", exc_info=True)
            return {
                "contradictions": [],
                "agreements": [],
                "experiment_comparison_table": "",
                "summary": f"生成矛盾分析时发生错误: {str(e)}",
            }

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        从 LLM 响应文本中提取 JSON 对象。

        处理三种情况:
            1. 纯 JSON 输出（理想情况）
            2. Markdown 代码块包裹 ```json ... ```
            3. JSON 前后有额外说明文字
        """
        # 优先匹配 markdown 代码块
        code_block_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
        match = re.search(code_block_pattern, text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            json_str = text.strip()

        # 定位最外层的 { ... }
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start == -1 or brace_end == -1:
            logger.warning("未在 LLM 输出中找到 JSON 花括号")
            return None

        json_str = json_str[brace_start: brace_end + 1]

        try:
            result = json.loads(json_str)
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return None

    def _build_source_list(
        self, aggregated: Dict[str, List[Any]],
    ) -> List[Dict[str, Any]]:
        """
        构建结构化的论文来源列表。
        """
        sources = []
        for paper_title, docs in aggregated.items():
            sections = list(set(
                doc.metadata.get("section", "未知") for doc in docs
            ))
            page_range = set()
            for doc in docs:
                ps = doc.metadata.get("page_start")
                if ps:
                    page_range.add(str(ps))

            sources.append({
                "title": paper_title,
                "sections": sorted(sections),
                "pages": sorted(page_range, key=int) if page_range else [],
                "chunk_count": len(docs),
            })

        return sources

    def _degraded_response(
        self,
        topic: str,
        message: str,
        papers_analyzed: int = 0,
        sources: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        构建降级响应——当矛盾检测无法正常执行时返回。

        确保 API 始终返回统一结构，前端无需特殊处理。
        """
        return {
            "topic": topic,
            "papers_analyzed": papers_analyzed,
            "contradictions": [],
            "agreements": [],
            "experiment_comparison_table": "",
            "summary": message,
            "sources": sources or [],
        }


# ================================================================
# 全局单例
# ================================================================

_contradiction_service_instance: Optional[ContradictionService] = None


def get_contradiction_service() -> ContradictionService:
    """获取全局唯一的 ContradictionService 实例"""
    global _contradiction_service_instance
    if _contradiction_service_instance is None:
        _contradiction_service_instance = ContradictionService()
    return _contradiction_service_instance
