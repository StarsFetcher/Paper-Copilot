"""
LangGraph Module
================
Custom LangGraph research agent with StateGraph, Send API,
conditional edges, checkpointing, and human-in-the-loop support.

This module replaces the prebuilt `create_react_agent` with a
fully custom graph architecture.

Exports:
    build_research_graph: Build and compile the research StateGraph
    reset_graph_cache:    Clear cached compiled graph (for testing)
"""

from service.graph.research_graph import (
    build_research_graph,
    reset_graph_cache,
)
from service.graph.state import (
    ResearchState,
    SearchAngleState,
    create_initial_state,
)

__all__ = [
    "build_research_graph",
    "reset_graph_cache",
    "ResearchState",
    "SearchAngleState",
    "create_initial_state",
]
