"""
Graph Streaming Adapter Module
===============================
Adapts LangGraph graph.stream() output to SSE-compatible events.

The challenge: custom StateGraph doesn't have built-in stream_mode="messages"
like create_react_agent. Instead, we use stream_mode="custom" where each node
emits events via get_stream_writer(). This adapter wraps the graph.stream()
call and produces the same event format that the Flask SSE endpoint expects.

Event format (backward compatible with existing agent_service.py):
    {"type": "token", "content": "..."}   — LLM output token
    {"type": "status", "content": "..."}  — phase status notification
    {"type": "done", "content": None}     — completion signal
    {"type": "error", "content": "..."}   — error message
    {"type": "interrupt", "content": {...}} — new: interrupt payload
"""

from typing import Any, Dict, Generator

from langgraph.graph.state import CompiledStateGraph

from utils.logger import setup_logger

logger = setup_logger(__name__)


def stream_graph_events(
    graph: CompiledStateGraph,
    inputs: Dict[str, Any],
    config: Dict[str, Any],
) -> Generator[Dict[str, Any], None, None]:
    """
    Stream graph execution as SSE-compatible events.

    Uses stream_mode="custom" — each node emits events through
    get_stream_writer(), and this function yields them as-is.

    Also handles:
        - Interrupt detection: when the graph pauses for human input
        - Error recovery: catches graph-level exceptions gracefully
        - Completion signal: always yields {"type": "done"} at end

    Args:
        graph:    Compiled StateGraph to execute
        inputs:   Initial state dict
        config:   RunnableConfig with thread_id, recursion_limit, etc.

    Yields:
        Dict events in SSE-compatible format
    """
    try:
        for event in graph.stream(
            inputs,
            config,
            stream_mode="custom",
        ):
            # Pass through events emitted by nodes via get_stream_writer()
            # These are already in the correct SSE format
            yield event

        # Check if graph was interrupted (paused for human input)
        try:
            state_snapshot = graph.get_state(config)
            if state_snapshot and hasattr(state_snapshot, 'interrupts') and state_snapshot.interrupts:
                yield {
                    "type": "interrupt",
                    "content": {
                        "thread_id": config.get("configurable", {}).get("thread_id", ""),
                        "message": "Graph paused. Resume with /api/chat/resume",
                        "interrupts": list(state_snapshot.interrupts),
                    },
                }
                logger.info(
                    f"[streaming] Graph interrupted at thread "
                    f"{config.get('configurable', {}).get('thread_id', 'unknown')}"
                )
                return  # Stop here; client will resume later
        except Exception:
            pass  # get_state may fail if no state exists yet

        yield {"type": "done", "content": None}
        logger.info("[streaming] Graph execution completed")

    except Exception as e:
        logger.error(f"[streaming] Graph execution error: {e}", exc_info=True)
        yield {
            "type": "error",
            "content": f"Graph execution error: {str(e)}",
        }
        yield {"type": "done", "content": None}


def stream_graph_updates(
    graph: CompiledStateGraph,
    inputs: Dict[str, Any],
    config: Dict[str, Any],
) -> Generator[Dict[str, Any], None, None]:
    """
    Fallback streaming mode: stream_mode="updates".

    Yields node-level state changes as status events. Does NOT
    provide token-level streaming — use stream_mode="custom" for that.

    Useful as a debugging tool and for non-streaming scenarios
    where you still want phase visibility.

    Args:
        graph:    Compiled StateGraph to execute
        inputs:   Initial state dict
        config:   RunnableConfig

    Yields:
        Dict events with type="status" for each node completion
    """
    try:
        for update in graph.stream(inputs, config, stream_mode="updates"):
            node_name = next(iter(update.keys()))
            node_output = update[node_name]

            # Skip internal nodes
            if node_name in ("__start__",):
                continue

            phase = node_output.get("phase", "")
            yield {
                "type": "status",
                "content": f"[{node_name}] {phase}",
            }

        yield {"type": "done", "content": None}

    except Exception as e:
        logger.error(f"[streaming-updates] Error: {e}", exc_info=True)
        yield {"type": "error", "content": str(e)}
        yield {"type": "done", "content": None}
