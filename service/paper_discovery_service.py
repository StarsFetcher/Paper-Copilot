"""
Paper Discovery Service Module
==============================
Searches arXiv API for academic papers matching a research topic.

Features:
    - Natural language query → LLM-optimized arXiv search terms
    - Date range filtering
    - Iterative search: when results are sparse, automatically tries
      alternative search strategies
    - Returns structured paper metadata for downstream processing
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import arxiv

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from prompts.templates import ARXIV_QUERY_PROMPT, ITERATIVE_SEARCH_PROMPT
from utils.logger import setup_logger

logger = setup_logger(__name__)


class PaperDiscoveryService:
    """
    Searches arXiv for academic papers.

    Uses LLM to translate natural language topics into optimized
    arXiv API queries. Supports iterative retry with alternative
    keywords when initial search returns too few results.
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None
        logger.info("PaperDiscoveryService instance created")

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

    def discover(
        self,
        topic: str,
        max_results: Optional[int] = None,
        days_back: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Search arXiv for papers matching a research topic.

        Args:
            topic:        Natural language research topic
            max_results:  Maximum number of results (default: settings.ARXIV_MAX_RESULTS)
            days_back:    How many days back to search (default: settings.ARXIV_SEARCH_DAYS_BACK)

        Returns:
            {
                "topic": str,
                "query_used": str,
                "total_found": int,
                "papers": [
                    {
                        "paper_id": "arxiv-xxxx.xxxxx",
                        "title": "...",
                        "authors": ["Author A", "Author B"],
                        "abstract": "...",
                        "url": "https://arxiv.org/abs/...",
                        "published": "2024-01-15",
                        "categories": ["cs.AI", "cs.CL"]
                    }
                ]
            }
        """
        if not topic or not topic.strip():
            return {"topic": topic, "query_used": "", "total_found": 0, "papers": []}

        max_results = max_results or settings.ARXIV_MAX_RESULTS
        days_back = days_back or settings.ARXIV_SEARCH_DAYS_BACK

        logger.info(
            f"Paper discovery: topic='{topic}', max={max_results}, "
            f"days_back={days_back}"
        )

        # Step 1: Translate topic to arXiv query
        query = self._build_query(topic)

        # Step 2: Execute arXiv search
        papers, total = self._search_arxiv(query, max_results, days_back)

        # Step 3: Iterative retry if too few results
        if (
            len(papers) < 3
            and settings.ARXIV_ENABLE_ITERATIVE_SEARCH
            and max_results >= 5
        ):
            logger.info(
                f"Only {len(papers)} results, attempting iterative search..."
            )
            alt_queries = self._generate_alternative_queries(topic, len(papers))
            for alt_query in alt_queries:
                alt_papers, _ = self._search_arxiv(alt_query, max_results, days_back)
                # Merge, deduplicating by arxiv_id
                existing_ids = {p["paper_id"] for p in papers}
                for p in alt_papers:
                    if p["paper_id"] not in existing_ids:
                        papers.append(p)
                        existing_ids.add(p["paper_id"])
                if len(papers) >= 5:
                    break

        logger.info(
            f"Discovery complete: {len(papers)} papers found "
            f"(query='{query}')"
        )

        return {
            "topic": topic,
            "query_used": query,
            "total_found": total,
            "papers": papers[:max_results],
        }

    # =================================================================
    # Internal methods
    # =================================================================

    def _build_query(self, topic: str) -> str:
        """Use LLM to translate natural language topic to arXiv query."""
        try:
            prompt = ARXIV_QUERY_PROMPT.format(topic=topic)
            response = self.llm.invoke([HumanMessage(content=prompt)])
            query = response.content.strip().strip('"').strip("'")
            # Validate: query should be non-empty and reasonable
            if not query or len(query) < 2:
                return topic
            logger.info(f"LLM translated '{topic[:60]}...' → '{query}'")
            return query
        except Exception as e:
            logger.warning(f"Query translation failed: {e}, using raw topic")
            return topic

    def _search_arxiv(
        self, query: str, max_results: int, days_back: int,
    ) -> tuple:
        """
        Execute arXiv API search.

        Returns:
            (papers_list, total_count)
        """
        try:
            # Build search (arxiv 4.0+ uses Client().results() API)
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
            )

            client = arxiv.Client()
            papers = []
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

            for result in client.results(search):
                # Date filter
                published = result.published.replace(tzinfo=timezone.utc)
                if published < cutoff:
                    continue

                papers.append({
                    "paper_id": result.entry_id.split("/")[-1],
                    "title": result.title,
                    "authors": [a.name for a in result.authors],
                    "abstract": result.summary.replace("\n", " ").strip(),
                    "url": result.entry_id,
                    "published": published.strftime("%Y-%m-%d"),
                    "categories": result.categories,
                })

                if len(papers) >= max_results:
                    break

            return papers, len(papers)

        except Exception as e:
            logger.error(f"arXiv search failed: {e}", exc_info=True)
            return [], 0

    def _generate_alternative_queries(
        self, topic: str, current_count: int,
    ) -> List[str]:
        """Generate alternative search strategies when results are sparse."""
        try:
            prompt = ITERATIVE_SEARCH_PROMPT.format(
                topic=topic, count=current_count,
            )
            response = self.llm.invoke([HumanMessage(content=prompt)])
            # Parse each non-empty line as a query
            queries = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip() and len(line.strip()) > 3
            ]
            logger.info(f"Generated {len(queries)} alternative queries")
            return queries[:3]
        except Exception as e:
            logger.warning(f"Alternative query generation failed: {e}")
            return []

    # =================================================================
    # Status
    # =================================================================

    def get_status(self) -> Dict[str, Any]:
        return {
            "arxiv_max_results": settings.ARXIV_MAX_RESULTS,
            "arxiv_days_back": settings.ARXIV_SEARCH_DAYS_BACK,
            "iterative_search": settings.ARXIV_ENABLE_ITERATIVE_SEARCH,
        }


# ================================================================
# Global Singleton
# ================================================================

_discovery_instance: Optional[PaperDiscoveryService] = None


def get_discovery_service() -> PaperDiscoveryService:
    global _discovery_instance
    if _discovery_instance is None:
        _discovery_instance = PaperDiscoveryService()
    return _discovery_instance
