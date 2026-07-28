"""
Research Graph Builder Module
==============================
Builds and compiles the custom LangGraph StateGraph for the research agent.

This is the central orchestration file — it wires together all nodes,
conditional edges, and the checkpointer into a compiled graph ready for
invocation and streaming.

Graph Flow:
    START → plan_node → [conditional]
        ├─ 0 angles → synthesize_node → END
        ├─ N angles (interrupt off) → Send(×N) → search_angle_node
        ├─ N angles (interrupt on)  → human_review_node → Send(×N) → search_angle_node
        └─ search_angle_node → evaluate_results_node → [conditional]
              ├─ sufficient → synthesize_node → END
              └─ needs_more → plan_node (loop)

Usage:
    from service.graph.research_graph import build_research_graph
    graph = build_research_graph()
    result = graph.invoke(inputs, config)
"""

from langgraph.graph import StateGraph, START, END

from config.settings import settings
from service.graph.state import ResearchState
from service.graph.nodes import (
    plan_node,
    human_review_node,
    search_angle_node,
    evaluate_results_node,
    synthesize_node,
    arxiv_search_node,
)
from service.graph.router import (
    route_after_plan,
    route_after_human_review,
    route_after_evaluate,
)
from service.graph.checkpoint import create_checkpointer
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Module-level cache for the compiled graph
_compiled_graph = None


def build_research_graph():
    """
    Build and compile the complete research graph.

    The graph is cached at module level after first compilation.
    Subsequent calls return the same compiled graph instance.

    Returns:
        A compiled StateGraph ready for .invoke() and .stream()

    Raises:
        ValueError: If graph configuration is invalid
    """
    global _compiled_graph

    if _compiled_graph is not None:
        return _compiled_graph

    logger.info("Building custom LangGraph research graph...")

    # ------------------------------------------------------------------
    # Step 1: Create StateGraph with typed state
    # ------------------------------------------------------------------
    builder = StateGraph(ResearchState)

    # ------------------------------------------------------------------
    # Step 2: Add all nodes
    # ------------------------------------------------------------------
    builder.add_node("plan_node", plan_node)
    builder.add_node("human_review_node", human_review_node)
    builder.add_node("search_angle_node", search_angle_node)
    builder.add_node("evaluate_results_node", evaluate_results_node)
    builder.add_node("synthesize_node", synthesize_node)
    builder.add_node("arxiv_search_node", arxiv_search_node)

    logger.info(
        "Added 6 nodes: plan_node, human_review_node, search_angle_node, "
        "evaluate_results_node, arxiv_search_node, synthesize_node"
    )

    # ------------------------------------------------------------------
    # Step 3: Add edges
    # ------------------------------------------------------------------

    # Entry: START → plan
    builder.add_edge(START, "plan_node")

    # Plan → search fan-out, human review, arXiv discovery, or synthesize
    builder.add_conditional_edges(
        "plan_node",
        route_after_plan,
        {
            "search_angle_node": "search_angle_node",
            "human_review_node": "human_review_node",
            "arxiv_search_node": "arxiv_search_node",
            "synthesize_node": "synthesize_node",
        },
    )

    # Human review → search fan-out or synthesize (if user rejected all)
    builder.add_conditional_edges(
        "human_review_node",
        route_after_human_review,
        {
            "search_angle_node": "search_angle_node",
            "synthesize_node": "synthesize_node",
        },
    )

    # After parallel search completes → evaluate
    builder.add_edge("search_angle_node", "evaluate_results_node")

    # Evaluate → synthesize, loop back, OR arXiv fallback
    builder.add_conditional_edges(
        "evaluate_results_node",
        route_after_evaluate,
        {
            "synthesize_node": "synthesize_node",
            "plan_node": "plan_node",
            "arxiv_search_node": "arxiv_search_node",
        },
    )

    # arXiv search → synthesize (with whatever results we have)
    builder.add_edge("arxiv_search_node", "synthesize_node")

    # Synthesize → END
    builder.add_edge("synthesize_node", END)

    logger.info("Added 4 conditional edges and 4 regular edges")

    # ------------------------------------------------------------------
    # Step 4: Configure checkpointer
    # ------------------------------------------------------------------
    checkpointer = create_checkpointer()

    # ------------------------------------------------------------------
    # Step 5: Configure interrupt points
    # ------------------------------------------------------------------
    interrupt_before = None
    if settings.GRAPH_ENABLE_INTERRUPT:
        # Interrupt before human_review_node so the graph pauses there
        # Note: the actual interrupt() call is inside human_review_node;
        # this just ensures the node is reachable as an interrupt point
        pass  # We handle interrupt inside the node itself

    # ------------------------------------------------------------------
    # Step 6: Compile
    # ------------------------------------------------------------------
    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if interrupt_before is not None:
        compile_kwargs["interrupt_before"] = interrupt_before

    _compiled_graph = builder.compile(**compile_kwargs)

    logger.info(
        f"Graph compiled successfully ✓ "
        f"(checkpointer={'enabled' if checkpointer else 'disabled'}, "
        f"interrupt={'enabled' if settings.GRAPH_ENABLE_INTERRUPT else 'disabled'})"
    )

    return _compiled_graph


def reset_graph_cache():
    """
    Reset the cached compiled graph.

    Useful for testing or when configuration changes at runtime.
    """
    global _compiled_graph
    _compiled_graph = None
    logger.info("Graph cache cleared")
