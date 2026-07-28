"""
Deep Paper Analysis Service Module
==================================
Structured extraction of key information from academic paper full text.

Extracts six dimensions from paper content:
    1. Research background & motivation
    2. Core methods & innovations
    3. Experimental design & key results
    4. Main contributions
    5. Limitations
    6. Keywords and terminology

This is the "deep reading" capability — going beyond simple text search
to understand the paper's intellectual structure.
"""

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from prompts.templates import DEEP_ANALYSIS_PROMPT
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DeepAnalysisService:
    """
    Extracts structured information from academic paper full text.

    Uses LLM with a specialized prompt template to identify and extract:
    background, methods, experiments, contributions, limitations, keywords.

    The extraction is grounded in the original text — no fabrication.
    Missing information is explicitly marked as 「未提及」.
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None
        logger.info("DeepAnalysisService instance created")

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL_NAME,
                temperature=settings.DEEP_ANALYSIS_TEMPERATURE,
                max_retries=settings.MAX_RETRIES,
            )
        return self._llm

    # =================================================================
    # Core method
    # =================================================================

    def analyze(
        self,
        text: str,
        paper_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform deep structured analysis of a paper's full text.

        Args:
            text:      Full paper text content
            paper_id:  Optional paper identifier
            metadata:  Optional paper metadata (title, authors, etc.)

        Returns:
            {
                "paper_id": str,
                "title": str,
                "background": str,
                "methods": str,
                "experiments": str,
                "contributions": [str, ...],
                "limitations": str,
                "keywords": [str, ...],
                "source_sections": [str, ...],
                "raw_analysis": dict  # Full LLM output
            }
        """
        if not text or len(text.strip()) < 100:
            return self._empty_result(
                paper_id, "文本内容不足（少于100字符），无法进行深度分析"
            )

        logger.info(
            f"Deep analysis: paper_id={paper_id or 'unknown'}, "
            f"text_length={len(text)}"
        )

        try:
            # Truncate text if too long (most LLMs handle ~16K tokens well)
            max_chars = 16000
            if len(text) > max_chars:
                logger.info(f"Truncating text from {len(text)} to {max_chars} chars")
                text = text[:max_chars] + "\n...(内容已截断)"

            # Call LLM
            prompt = DEEP_ANALYSIS_PROMPT.format(content=text)
            response = self.llm.invoke([HumanMessage(content=prompt)])

            # Parse JSON result
            parsed = self._parse_json(response.content)

            if parsed is None:
                logger.warning("Failed to parse LLM analysis output")
                return self._empty_result(
                    paper_id, "LLM 输出格式异常，无法解析分析结果"
                )

            # Build result
            title = (
                parsed.get("title", "")
                or (metadata or {}).get("title", "")
                or "未知标题"
            )

            result = {
                "paper_id": paper_id or "",
                "title": title,
                "background": parsed.get("background", "未提及"),
                "methods": parsed.get("methods", "未提及"),
                "experiments": parsed.get("experiments", "未提及"),
                "contributions": parsed.get("contributions", []),
                "limitations": parsed.get("limitations", "未提及"),
                "keywords": parsed.get("keywords", []),
                "source_sections": parsed.get("source_sections", []),
                "raw_analysis": parsed,
            }

            logger.info(
                f"Deep analysis complete: title='{title[:50]}...', "
                f"keywords={result['keywords']}, "
                f"contributions={len(result['contributions'])}"
            )

            return result

        except Exception as e:
            logger.error(f"Deep analysis failed: {e}", exc_info=True)
            return self._empty_result(
                paper_id, f"分析过程发生错误: {str(e)}"
            )

    # =================================================================
    # Batch analysis
    # =================================================================

    def analyze_batch(
        self,
        papers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Analyze multiple papers in sequence.

        Args:
            papers: List of dicts, each with at least 'text' or 'abstract' key,
                    plus optional 'paper_id' and metadata.

        Returns:
            List of analysis result dicts
        """
        results = []
        for i, paper in enumerate(papers):
            paper_id = paper.get("paper_id", paper.get("arxiv_id", f"paper-{i}"))
            text = paper.get("text", paper.get("abstract", ""))

            logger.info(
                f"Batch analysis [{i+1}/{len(papers)}]: {paper_id}"
            )

            result = self.analyze(
                text=text,
                paper_id=paper_id,
                metadata={
                    "title": paper.get("title", ""),
                    "authors": paper.get("authors", ""),
                },
            )
            results.append(result)

        logger.info(
            f"Batch analysis complete: {len(results)} papers analyzed"
        )
        return results

    # =================================================================
    # Internal
    # =================================================================

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON object from LLM response."""
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        json_str = m.group(1) if m else text
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            return json.loads(json_str[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}")
            return None

    def _empty_result(
        self, paper_id: Optional[str], reason: str,
    ) -> Dict[str, Any]:
        """Return an empty analysis result with a reason for the failure."""
        return {
            "paper_id": paper_id or "",
            "title": "分析失败",
            "background": reason,
            "methods": "未提及",
            "experiments": "未提及",
            "contributions": [],
            "limitations": "未提及",
            "keywords": [],
            "source_sections": [],
            "raw_analysis": {"error": reason},
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "model": settings.LLM_MODEL_NAME,
            "temperature": settings.DEEP_ANALYSIS_TEMPERATURE,
        }


# ================================================================
# Global Singleton
# ================================================================

_analysis_instance: Optional[DeepAnalysisService] = None


def get_analysis_service() -> DeepAnalysisService:
    global _analysis_instance
    if _analysis_instance is None:
        _analysis_instance = DeepAnalysisService()
    return _analysis_instance
