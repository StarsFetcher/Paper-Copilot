"""
Paper Workflow Graph Nodes
==========================
Node functions for the paper discovery → screening → analysis → storage graph.

Each node wraps the corresponding service and writes results to state.
"""

from typing import Any, Dict

from langgraph.config import get_stream_writer

from service.graph.paper_workflow_state import PaperWorkflowState
from service.paper_discovery_service import get_discovery_service
from service.paper_screening_service import get_screening_service
from service.deep_analysis_service import get_analysis_service
from service.paper_library import get_paper_library
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ======================================================================
# Node: Discover — Search arXiv
# ======================================================================

def discover_node(state: PaperWorkflowState) -> Dict[str, Any]:
    """Search arXiv for papers matching the research topic."""
    writer = get_stream_writer()

    topic = state.get("topic", "")
    max_results = state.get("max_results", 10)
    days_back = state.get("days_back", 90)

    logger.info(f"[discover_node] Searching arXiv: topic='{topic[:60]}...'")
    writer({"type": "status", "content": f"🔍 Searching arXiv for: {topic[:50]}..."})

    service = get_discovery_service()
    result = service.discover(
        topic=topic,
        max_results=max_results,
        days_back=days_back,
    )

    papers = result.get("papers", [])
    writer({
        "type": "status",
        "content": f"✅ Found {len(papers)} papers on arXiv",
    })

    return {
        "query_used": result.get("query_used", ""),
        "found_papers": papers,
        "total_found": result.get("total_found", 0),
        "phase": "discover",
    }


# ======================================================================
# Node: Screen — Filter by quality
# ======================================================================

def screen_node(state: PaperWorkflowState) -> Dict[str, Any]:
    """Evaluate paper quality and filter out low-quality results."""
    writer = get_stream_writer()

    papers = state.get("found_papers", [])
    topic = state.get("topic", "")

    if not papers:
        logger.info("[screen_node] No papers to screen, skipping")
        return {
            "screened_papers": [],
            "filtered_out": [],
            "pass_rate": 0.0,
            "phase": "screen",
        }

    logger.info(f"[screen_node] Screening {len(papers)} papers")
    writer({"type": "status", "content": f"📋 Evaluating {len(papers)} papers..."})

    service = get_screening_service()
    result = service.screen(papers=papers, topic=topic)

    screened = result.get("screened", [])
    filtered = result.get("filtered_out", [])

    writer({
        "type": "status",
        "content": f"✅ {len(screened)} papers passed quality check ({len(filtered)} filtered)",
    })

    return {
        "screened_papers": screened,
        "filtered_out": filtered,
        "pass_rate": result.get("pass_rate", 0.0),
        "phase": "screen",
    }


# ======================================================================
# Node: Analyze — Deep structured extraction
# ======================================================================

def analyze_node(state: PaperWorkflowState) -> Dict[str, Any]:
    """Perform deep structured analysis on screened papers."""
    writer = get_stream_writer()

    papers = state.get("screened_papers", [])

    if not papers:
        logger.info("[analyze_node] No papers to analyze, skipping")
        return {"analyzed_papers": [], "phase": "analyze"}

    logger.info(f"[analyze_node] Analyzing {len(papers)} papers")
    writer({
        "type": "status",
        "content": f"🤖 Performing deep analysis on {len(papers)} papers...",
    })

    service = get_analysis_service()

    results = []
    for i, paper in enumerate(papers):
        paper_id = paper.get("paper_id", f"paper-{i}")
        title = paper.get("title", "Unknown")

        writer({
            "type": "status",
            "content": f"  Analyzing [{i+1}/{len(papers)}]: {title[:60]}...",
        })

        # Use abstract as text if full text not available
        text = paper.get("abstract", "")
        analysis = service.analyze(
            text=text,
            paper_id=paper_id,
            metadata={"title": title, "authors": paper.get("authors", "")},
        )
        results.append(analysis)

    writer({
        "type": "status",
        "content": f"✅ Deep analysis complete for {len(results)} papers",
    })

    return {
        "analyzed_papers": results,
        "phase": "analyze",
    }


# ======================================================================
# Node: Store — Save to library and optionally vectorize
# ======================================================================

def store_node(state: PaperWorkflowState) -> Dict[str, Any]:
    """Store analyzed papers in the paper library."""
    writer = get_stream_writer()

    papers = state.get("screened_papers", [])
    analyses = state.get("analyzed_papers", [])
    stored = 0

    if not papers:
        logger.info("[store_node] No papers to store")
        return {"stored_count": 0, "phase": "store"}

    logger.info(f"[store_node] Storing {len(papers)} papers")
    writer({"type": "status", "content": f"💾 Storing {len(papers)} papers..."})

    library = get_paper_library()

    for i, paper in enumerate(papers):
        paper_id = paper.get("paper_id", f"paper-{i}")

        # Merge paper metadata with analysis results
        analysis = {}
        for a in analyses:
            if a.get("paper_id") == paper_id:
                analysis = a.get("raw_analysis", a)
                break

        try:
            is_new = library.add_paper({
                "paper_id": paper_id,
                "title": paper.get("title", ""),
                "authors": ", ".join(paper.get("authors", [])[:10]),
                "abstract": paper.get("abstract", ""),
                "arxiv_id": paper_id,
                "url": paper.get("url", ""),
                "published_date": paper.get("published", ""),
                "tags": paper.get("tags", []),
                "quality_score": paper.get("quality_score", 0),
                "relevance_score": paper.get("relevance_score", 0),
                "analysis_json": analysis,
                "status": "analyzed",
            })
            if is_new or i == 0:  # Always count
                stored += 1
        except Exception as e:
            logger.error(f"Failed to store paper {paper_id}: {e}")

    writer({
        "type": "status",
        "content": f"✅ Stored {stored} papers in library",
    })

    return {
        "stored_count": stored,
        "phase": "store",
    }
