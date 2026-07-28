"""
Graph State Definition Module
=============================
Defines the typed state schema for the custom LangGraph research agent.

State is the heart of LangGraph — every node reads from and writes to it,
and conditional edges use it to decide routing.

Key design decisions:
    - search_results uses a custom reducer (reduce_search_results) to merge
      parallel Send API branches without overwriting each other
    - messages uses LangGraph's built-in add_messages reducer for chat history
    - phase tracks the current graph stage for streaming visibility
"""

from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# ======================================================================
# Custom Reducer: Merge search results from parallel Send branches
# ======================================================================

def reduce_search_results(
    left: Optional[Dict[str, List[Document]]],
    right: Optional[Dict[str, List[Document]]],
) -> Dict[str, List[Document]]:
    """
    Merge search results from multiple parallel Send branches.

    When Send API fans out N parallel searches, each branch returns
    {search_results: {angle: [docs]}}. This reducer merges them all
    into a single dict, deduplicating by (page_content, title) key.

    Args:
        left:  Accumulated results so far (or None on first call)
        right: New results from the latest branch to merge

    Returns:
        Merged dict with deduplicated documents per angle
    """
    if left is None:
        return right or {}
    if right is None:
        return left

    merged = dict(left)
    for angle, docs in right.items():
        if angle in merged:
            # Deduplicate by (content_prefix, title) compound key
            existing_keys = {
                (d.page_content[:80], d.metadata.get("title", ""))
                for d in merged[angle]
            }
            for d in docs:
                key = (d.page_content[:80], d.metadata.get("title", ""))
                if key not in existing_keys:
                    merged[angle].append(d)
                    existing_keys.add(key)
        else:
            merged[angle] = list(docs)

    return merged


# ======================================================================
# Main Research State
# ======================================================================

class ResearchState(TypedDict):
    """
    Complete state schema for the research graph.

    This state flows through every node in the graph. Each node reads
    what it needs and writes only what it changes — LangGraph merges
    the partial return dict into the full state.

    Fields:
        query:              Original user question (set once at START)
        messages:           Full conversation history (add_messages reducer)
        search_angles:      LLM-identified sub-questions for parallel search
        search_iteration:   Current plan→search→evaluate loop count (anti-loop)
        search_results:     Accumulated results from all search branches
        evaluation:         "sufficient" or "needs_more" from evaluate node
        evaluation_reason:  LLM's explanation for the evaluation decision
        final_answer:       Synthesized answer text from synthesize node
        sources:            Extracted source citations
        phase:              Current stage for SSE status events
        arxiv_searched:     Whether arXiv fallback has been attempted
    """

    # --- Input ---
    query: str
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # --- Search Planning ---
    search_angles: List[str]
    search_iteration: int

    # --- Search Results (merged from parallel Send branches) ---
    search_results: Annotated[
        Dict[str, List[Document]],
        reduce_search_results,
    ]

    # --- Evaluation ---
    evaluation: str
    evaluation_reason: str

    # --- Synthesis Output ---
    final_answer: str
    sources: List[Dict[str, Any]]

    # --- Phase Tracking (for streaming visibility) ---
    phase: str

    # --- Fallback flag ---
    arxiv_searched: bool

    # --- Discovery mode (skip local search, go to arXiv directly) ---
    discovery_mode: bool

    # --- Search mode override ("auto" | "local" | "arxiv") ---
    search_mode: str


# ======================================================================
# Search Angle Sub-state (for Send branches)
# ======================================================================

class SearchAngleState(TypedDict):
    """
    Minimal state passed to each parallel search_angle_node via Send.

    Each Send branch receives one search angle + the original query
    for context. Results are written to search_results in the parent state.
    """
    angle: str
    query: str


# ======================================================================
# Default State Factory
# ======================================================================

def create_initial_state(query: str, search_mode: str = "auto") -> Dict[str, Any]:
    """
    Create a fresh state dict for a new conversation turn.

    Args:
        query:       The user's natural language question
        search_mode: "auto" | "local" | "arxiv" — overrides discovery detection

    Returns:
        Initial state dict with all fields set to defaults
    """
    from langchain_core.messages import HumanMessage

    return {
        "query": query.strip(),
        "messages": [HumanMessage(content=query.strip())],
        "search_angles": [],
        "search_iteration": 0,
        "search_results": {},
        "evaluation": "",
        "evaluation_reason": "",
        "final_answer": "",
        "sources": [],
        "phase": "start",
        "arxiv_searched": False,
        "discovery_mode": False,
        "search_mode": search_mode,
    }
