"""
Graph Router Module
===================
Conditional edge routing functions for the research graph.

Each function reads the graph state and returns either:
    - A string: the name of the next node to execute
    - A list of Send objects: fan-out to parallel branches

These are the "decision points" in the graph that make it more than
just a linear pipeline — they implement the intelligence of the
research workflow.
"""

from typing import List, Union

from langgraph.types import Send

from config.settings import settings
from service.graph.state import ResearchState
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ======================================================================
# Route: After Planning → Search Fan-out or Human Review
# ======================================================================

def route_after_plan(
    state: ResearchState,
) -> Union[str, List[Send]]:
    """
    Decide what happens after the plan_node.

    Paths (in priority order):
        1. Discovery mode → route to arxiv_search_node (skip local search)
        2. No angles → skip search, go straight to synthesize
        3. Angles >= threshold AND interrupt enabled → human review first
        4. Otherwise → fan out via Send API to search all angles in parallel

    Args:
        state: Current graph state after planning

    Returns:
        "synthesize_node" | "human_review_node" | "arxiv_search_node" | [Send(...), ...]
    """
    angles = state.get("search_angles", [])
    discovery_mode = state.get("discovery_mode", False)

    # Path 0: Paper discovery intent → go straight to arXiv
    if discovery_mode:
        logger.info("[router] Discovery mode → routing to arxiv_search_node")
        return "arxiv_search_node"

    # Path 1: No search angles needed (greeting, non-search question)
    if not angles:
        logger.info("[router] No search angles → routing to synthesize_node")
        return "synthesize_node"

    # Path 2: Many angles + interrupt enabled → ask user
    if (
        settings.GRAPH_ENABLE_INTERRUPT
        and len(angles) >= settings.GRAPH_INTERRUPT_ANGLE_THRESHOLD
    ):
        logger.info(
            f"[router] {len(angles)} angles >= threshold "
            f"({settings.GRAPH_INTERRUPT_ANGLE_THRESHOLD}), "
            f"interrupt enabled → routing to human_review_node"
        )
        return "human_review_node"

    # Path 3: Fan out via Send API
    logger.info(
        f"[router] Fanning out to {len(angles)} parallel search branches"
    )
    return [
        Send(
            "search_angle_node",
            {"angle": angle, "query": state.get("query", "")},
        )
        for angle in angles
    ]


# ======================================================================
# Route: After Human Review → Search Fan-out
# ======================================================================

def route_after_human_review(
    state: ResearchState,
) -> Union[str, List[Send]]:
    """
    After user approves (or filters) the search plan, fan out to search.

    If user rejected all angles, go to synthesize with an explanation.
    """
    angles = state.get("search_angles", [])

    if not angles:
        logger.info("[router] User rejected all angles → routing to synthesize_node")
        return "synthesize_node"

    logger.info(
        f"[router] User approved {len(angles)} angles → fanning out"
    )
    return [
        Send(
            "search_angle_node",
            {"angle": angle, "query": state.get("query", "")},
        )
        for angle in angles
    ]


# ======================================================================
# Route: After Evaluation → Synthesize or Loop Back
# ======================================================================

def route_after_evaluate(state: ResearchState) -> str:
    """
    Decide whether results are sufficient to proceed to synthesis,
    whether to loop back for more local search, or whether to
    fall back to arXiv external search.

    Priority:
        1. Sufficient → synthesize
        2. Insufficient + arXiv not tried yet → arXiv fallback
        3. Insufficient + arXiv already tried → force synthesize
        4. Insufficient + iteration < max → loop back to plan

    Args:
        state: Current graph state after evaluation

    Returns:
        "synthesize_node" | "plan_node" | "arxiv_search_node"
    """
    evaluation = state.get("evaluation", "sufficient")
    iteration = state.get("search_iteration", 0)
    max_iter = settings.GRAPH_MAX_SEARCH_ITERATIONS
    arxiv_searched = state.get("arxiv_searched", False)

    # Check if local results are effectively empty
    results = state.get("search_results", {})
    total_docs = sum(len(v) for v in results.values())

    if evaluation == "sufficient":
        logger.info("[router] Results sufficient → routing to synthesize_node")
        return "synthesize_node"

    # arXiv fallback: local search insufficient, arXiv not tried yet
    if not arxiv_searched and (total_docs == 0 or iteration >= max_iter):
        logger.info(
            f"[router] Local results insufficient ({total_docs} docs, "
            f"iter {iteration}/{max_iter}), arXiv not tried → "
            f"routing to arxiv_search_node"
        )
        return "arxiv_search_node"

    if iteration >= max_iter:
        logger.info(
            f"[router] Max iterations ({max_iter}) reached, "
            f"arXiv already tried={arxiv_searched} → "
            f"forcing synthesize_node"
        )
        return "synthesize_node"

    logger.info(
        f"[router] Results insufficient (iter {iteration}/{max_iter}) → "
        f"looping back to plan_node"
    )
    return "plan_node"
