"""
Paper Workflow State Definition
===============================
Typed state for the paper discovery → screening → analysis → storage workflow.
"""

from typing import Any, Dict, List, Optional, TypedDict


class PaperWorkflowState(TypedDict):
    """
    State for the paper research workflow graph.

    Flows through: discover → screen → analyze → store
    """
    # Input
    topic: str
    max_results: int
    days_back: int

    # Discovery output
    query_used: str
    found_papers: List[Dict[str, Any]]
    total_found: int

    # Screening output
    screened_papers: List[Dict[str, Any]]
    filtered_out: List[Dict[str, Any]]
    pass_rate: float

    # Analysis output
    analyzed_papers: List[Dict[str, Any]]

    # Storage output
    stored_count: int

    # Status
    phase: str  # "discover" | "screen" | "analyze" | "store" | "done" | "error"
    error_message: str
