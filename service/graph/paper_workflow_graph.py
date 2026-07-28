"""
Paper Workflow Graph Builder
============================
Builds and compiles the LangGraph StateGraph for the paper research workflow.

Graph Flow:
    START → discover (arXiv search)
         → screen   (LLM quality filter)
         → analyze  (deep structured extraction)
         → store    (save to paper library)
         → END

Conditional routing:
    - No papers found → skip remaining steps → END
    - All papers filtered out → skip analysis → store metadata → END

Usage:
    from service.graph.paper_workflow_graph import build_paper_workflow_graph
    graph = build_paper_workflow_graph()
    result = graph.invoke({"topic": "attention mechanism", ...})
"""

from langgraph.graph import StateGraph, START, END

from service.graph.paper_workflow_state import PaperWorkflowState
from service.graph.paper_workflow_nodes import (
    discover_node,
    screen_node,
    analyze_node,
    store_node,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)

_compiled_workflow = None


def build_paper_workflow_graph():
    """Build and compile the paper research workflow graph."""
    global _compiled_workflow

    if _compiled_workflow is not None:
        return _compiled_workflow

    logger.info("Building paper workflow graph...")

    builder = StateGraph(PaperWorkflowState)

    # Add nodes
    builder.add_node("discover_node", discover_node)
    builder.add_node("screen_node", screen_node)
    builder.add_node("analyze_node", analyze_node)
    builder.add_node("store_node", store_node)

    # Add edges: linear pipeline with conditional skipping
    builder.add_edge(START, "discover_node")

    # Discover → Screen (conditionally skip if no papers)
    builder.add_conditional_edges(
        "discover_node",
        _route_after_discover,
        {
            "screen_node": "screen_node",
            "__end__": END,
        },
    )

    # Screen → Analyze (conditionally skip if all filtered)
    builder.add_conditional_edges(
        "screen_node",
        _route_after_screen,
        {
            "analyze_node": "analyze_node",
            "store_node": "store_node",
        },
    )

    # Analyze → Store → END
    builder.add_edge("analyze_node", "store_node")
    builder.add_edge("store_node", END)

    _compiled_workflow = builder.compile()

    logger.info("Paper workflow graph compiled successfully ✓")
    return _compiled_workflow


# ======================================================================
# Conditional routing functions
# ======================================================================

def _route_after_discover(state: PaperWorkflowState) -> str:
    """Route after discovery: skip to END if no papers found."""
    papers = state.get("found_papers", [])
    if not papers:
        logger.info("[workflow] No papers found, ending workflow")
        return "__end__"
    logger.info(f"[workflow] {len(papers)} papers found, proceeding to screening")
    return "screen_node"


def _route_after_screen(state: PaperWorkflowState) -> str:
    """Route after screening: skip analysis if all papers filtered out."""
    screened = state.get("screened_papers", [])
    if not screened:
        logger.info("[workflow] All papers filtered out, skipping analysis")
        return "store_node"  # Still store metadata
    logger.info(
        f"[workflow] {len(screened)} papers passed screening, "
        "proceeding to analysis"
    )
    return "analyze_node"


def reset_workflow_cache():
    """Clear cached compiled graph."""
    global _compiled_workflow
    _compiled_workflow = None
