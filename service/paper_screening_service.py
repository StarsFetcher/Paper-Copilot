"""
Paper Screening Service Module
==============================
LLM-based quality assessment and auto-tagging for discovered papers.

Evaluates each paper's relevance and quality based on title + abstract,
assigns tags, and filters out low-quality results.

This is the "gatekeeper" between paper discovery and deep analysis.
"""

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from prompts.templates import SCREENING_PROMPT
from utils.logger import setup_logger

logger = setup_logger(__name__)


class PaperScreeningService:
    """
    Evaluates and filters papers using LLM quality assessment.

    Each paper receives:
        - relevance_score (0-10): match to research topic
        - quality_score (0-10): estimated academic quality
        - tags: 2-5 keyword labels
        - assessment: one-sentence evaluation
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None
        logger.info("PaperScreeningService instance created")

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL_NAME,
                temperature=0.1,
                max_retries=settings.MAX_RETRIES,
            )
        return self._llm

    # =================================================================
    # Core method
    # =================================================================

    def screen(
        self,
        papers: List[Dict[str, Any]],
        topic: str,
        quality_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Screen a batch of papers for quality and relevance.

        Args:
            papers:            List of paper dicts (from discovery service)
            topic:             The original research topic
            quality_threshold: Minimum quality score to pass (0-10)

        Returns:
            {
                "screened": [...],    # Papers that passed (with scores + tags)
                "filtered_out": [...],  # Papers that failed
                "pass_rate": float
            }
        """
        threshold = quality_threshold or settings.SCREENING_QUALITY_THRESHOLD

        if not papers:
            return {"screened": [], "filtered_out": [], "pass_rate": 0.0}

        logger.info(
            f"Screening {len(papers)} papers for topic='{topic[:60]}...', "
            f"threshold={threshold}"
        )

        screened = []
        filtered_out = []

        for i, paper in enumerate(papers):
            logger.info(
                f"Screening [{i+1}/{len(papers)}]: "
                f"{paper.get('title', 'Unknown')[:60]}..."
            )

            assessment = self._assess_paper(paper, topic)

            if assessment is None:
                # Assessment failed, include paper with default scores
                paper["relevance_score"] = 5.0
                paper["quality_score"] = 5.0
                paper["tags"] = []
                paper["assessment"] = "评估失败"
                screened.append(paper)
                continue

            paper["relevance_score"] = assessment.get("relevance_score", 5)
            paper["quality_score"] = assessment.get("quality_score", 5)
            paper["tags"] = assessment.get("tags", [])
            paper["assessment"] = assessment.get("assessment", "")

            if paper["quality_score"] >= threshold:
                screened.append(paper)
                logger.info(
                    f"  ✓ PASS (quality={paper['quality_score']}, "
                    f"relevance={paper['relevance_score']})"
                )
            else:
                filtered_out.append(paper)
                logger.info(
                    f"  ✗ FILTERED (quality={paper['quality_score']}, "
                    f"relevance={paper['relevance_score']})"
                )

        pass_rate = len(screened) / len(papers) if papers else 0.0

        logger.info(
            f"Screening complete: {len(screened)} passed, "
            f"{len(filtered_out)} filtered (pass_rate={pass_rate:.0%})"
        )

        return {
            "screened": screened,
            "filtered_out": filtered_out,
            "pass_rate": pass_rate,
        }

    # =================================================================
    # Internal
    # =================================================================

    def _assess_paper(
        self, paper: Dict[str, Any], topic: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Call LLM to assess a single paper.

        Returns parsed JSON dict or None if parsing fails.
        """
        title = paper.get("title", "Unknown")
        authors = ", ".join(paper.get("authors", [])[:5])
        abstract = paper.get("abstract", "")

        # Truncate abstract if too long
        if len(abstract) > 2000:
            abstract = abstract[:2000] + "..."

        prompt = SCREENING_PROMPT.format(
            topic=topic,
            title=title,
            authors=authors,
            abstract=abstract,
        )

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return self._parse_json(response.content)
        except Exception as e:
            logger.error(f"Screening assessment failed for '{title}': {e}")
            return None

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response."""
        # Try code block first
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        json_str = m.group(1) if m else text
        # Find outermost braces
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            return json.loads(json_str[start:end + 1])
        except json.JSONDecodeError:
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "quality_threshold": settings.SCREENING_QUALITY_THRESHOLD,
        }


# ================================================================
# Global Singleton
# ================================================================

_screening_instance: Optional[PaperScreeningService] = None


def get_screening_service() -> PaperScreeningService:
    global _screening_instance
    if _screening_instance is None:
        _screening_instance = PaperScreeningService()
    return _screening_instance
