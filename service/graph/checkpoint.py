"""
Checkpoint Module
=================
Factory for LangGraph checkpointers (InMemorySaver or SqliteSaver).

Checkpoints enable:
    1. Multi-turn conversation memory (state persists across requests)
    2. Graph interrupt/resume (pause and continue execution)
    3. State replay and debugging

Usage:
    from service.graph.checkpoint import create_checkpointer
    checkpointer = create_checkpointer()
    graph = builder.compile(checkpointer=checkpointer)
"""

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Module-level cache — reuses the same checkpointer across requests
# InMemorySaver: persisted in memory for the process lifetime
# SqliteSaver: persisted to disk across restarts
_checkpointer_instance = None


def create_checkpointer():
    """
    Create or return a cached LangGraph checkpointer.

    Based on GRAPH_CHECKPOINT_TYPE:
        - "memory": InMemorySaver — fast, process-lifetime, no disk
        - "sqlite":  SqliteSaver  — persistent, survives restarts

    Returns:
        A LangGraph checkpointer instance, or None if checkpointing is disabled
    """
    global _checkpointer_instance

    if not settings.GRAPH_ENABLE_CHECKPOINTING:
        logger.info("Checkpointing is disabled")
        return None

    if _checkpointer_instance is not None:
        return _checkpointer_instance

    checkpointer_type = settings.GRAPH_CHECKPOINT_TYPE.lower()

    if checkpointer_type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            db_path = Path(settings.GRAPH_CHECKPOINT_DB_PATH)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            _checkpointer_instance = SqliteSaver.from_conn_string(str(db_path))
            logger.info(
                f"SqliteSaver initialized: {db_path}"
            )
            return _checkpointer_instance

        except ImportError:
            logger.warning(
                "langgraph-checkpoint-sqlite not installed. "
                "Falling back to InMemorySaver."
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize SqliteSaver: {e}. "
                "Falling back to InMemorySaver.",
                exc_info=True,
            )

    # Default: InMemorySaver
    _checkpointer_instance = InMemorySaver()
    logger.info("InMemorySaver initialized (process-lifetime)")
    return _checkpointer_instance


def reset_checkpointer():
    """
    Reset the cached checkpointer instance.

    Useful for testing or when config changes at runtime.
    """
    global _checkpointer_instance
    _checkpointer_instance = None
    logger.info("Checkpointer cache cleared")
