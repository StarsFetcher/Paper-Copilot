"""
LangGraph Agent 服务模块（自定义 StateGraph 版）
================================================
核心职责:
    1. 构建自定义 LangGraph StateGraph 研究 Agent
    2. 利用 Send API 实现并行搜索
    3. 利用条件边实现搜索→评估→循环
    4. 利用 InMemorySaver 实现多轮对话记忆
    5. 支持 stream_mode="custom" 流式输出
    6. 可选 human-in-the-loop 中断

架构说明 (v3.0 — 自定义 StateGraph):
    - 替代 v2.0 的 langgraph.prebuilt.create_react_agent
    - plan → Send(×N parallel search) → evaluate → synthesize
    - 条件路由: 搜索结果充分 → 生成回答; 不充分 → 重新规划
    - 检查点支持多轮对话和中断恢复
    - 图结构: service/graph/research_graph.py

与 v2.0 的兼容:
    - AgentService.chat(query) → {"answer": str, "sources": list}  不变
    - AgentService.chat_stream(query) → Generator[dict]              不变
    - app.py 和前端零改动
"""

import uuid
from typing import Any, Dict, Generator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

from config.settings import settings
from service.graph import (
    build_research_graph,
    create_initial_state,
    reset_graph_cache,
)
from service.graph.streaming import stream_graph_events
from service.vector_service import get_vector_service
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ======================================================================
# Agent 服务
# ======================================================================

class AgentService:
    """
    LangGraph Agent 服务 (v3.0 — 自定义 StateGraph)

    使用自定义 StateGraph 替代 create_react_agent，具备:
        - 多步骤研究流程（计划→搜索→评估→综合）
        - 并行搜索（Send API）
        - 多轮对话记忆（InMemorySaver 检查点）
        - 可选人机交互中断
    """

    def __init__(self):
        """初始化 Agent 服务"""
        self._agent = None  # Compiled StateGraph
        self._initialized: bool = False
        logger.info("AgentService 实例已创建（自定义 StateGraph 模式）")

    # =================================================================
    # 初始化
    # =================================================================

    def _ensure_initialized(self):
        """确保图已构建和编译（懒加载）"""
        if self._initialized:
            return

        logger.info("正在构建自定义 LangGraph 研究 Agent...")

        try:
            self._agent = build_research_graph()
            self._initialized = True

            logger.info(
                f"自定义 LangGraph Agent 初始化完成 ✓ "
                f"(model={settings.LLM_MODEL_NAME}, "
                f"max_iterations={settings.GRAPH_MAX_SEARCH_ITERATIONS}, "
                f"interrupt={'enabled' if settings.GRAPH_ENABLE_INTERRUPT else 'disabled'}, "
                f"checkpointing={'enabled' if settings.GRAPH_ENABLE_CHECKPOINTING else 'disabled'})"
            )
        except Exception as e:
            logger.error(f"图构建失败: {e}", exc_info=True)
            raise RuntimeError(f"Failed to build LangGraph agent: {e}")

    # =================================================================
    # 同步调用接口
    # =================================================================

    def chat(self, query: str, thread_id: Optional[str] = None,
             search_mode: str = "auto") -> Dict[str, Any]:
        """
        同步聊天接口（非流式）。

        使用 graph.invoke() 执行完整的研究流程，
        等待所有节点完成后返回最终结果。

        Args:
            query:       用户的自然语言提问
            thread_id:   可选的会话线程 ID（用于多轮对话记忆）
            search_mode: "auto" | "local" | "arxiv" 搜索模式

        Returns:
            {"answer": str, "sources": [...]}
        """
        self._ensure_initialized()

        if not query or not query.strip():
            return {"answer": "请输入您的问题。", "sources": []}

        logger.info(f"Agent 同步调用: query='{query[:100]}...', search_mode={search_mode}")

        try:
            # Build initial state
            inputs = create_initial_state(query.strip(), search_mode=search_mode)

            # Build config with thread_id for checkpointing
            if thread_id is None:
                thread_id = str(uuid.uuid4())

            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": (
                    2 + settings.GRAPH_MAX_SEARCH_ITERATIONS * 3
                ),
            }

            # Execute the graph
            result = self._agent.invoke(inputs, config)

            # Extract answer
            answer = result.get("final_answer", "")
            if not answer:
                # Fallback: extract from last AI message
                messages = result.get("messages", [])
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        answer = msg.content
                        break

            if not answer:
                answer = "抱歉，我暂时无法回答这个问题。"

            # Extract sources
            sources = result.get("sources", [])

            logger.info(
                f"Agent 同步调用完成: "
                f"iterations={result.get('search_iteration', 0)}, "
                f"sources={len(sources)}, "
                f"answer_length={len(answer)}"
            )

            return {"answer": answer, "sources": sources}

        except Exception as e:
            logger.error(f"Agent 同步调用失败: {e}", exc_info=True)
            return {
                "answer": f"处理您的问题时发生错误: {str(e)}",
                "sources": [],
            }

    # =================================================================
    # 流式调用接口
    # =================================================================

    def chat_stream(
        self,
        query: str,
        thread_id: Optional[str] = None,
        search_mode: str = "auto",
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式聊天接口（使用 LangGraph 自定义图 stream_mode="custom"）。

        节点通过 get_stream_writer() 发出自定义事件，
        stream_graph_events 适配器将这些事件转换为 SSE 格式。

        Yields:
            {"type": "token", "content": "..."}    — LLM token
            {"type": "status", "content": "..."}   — 状态通知
            {"type": "done", "content": None}      — 完成
            {"type": "error", "content": "..."}    — 错误
            {"type": "interrupt", "content": {...}} — 中断（新增）
        """
        self._ensure_initialized()

        if not query or not query.strip():
            yield {"type": "token", "content": "请输入您的问题。"}
            yield {"type": "done", "content": None}
            return

        logger.info(f"Agent 流式调用: query='{query[:100]}...', search_mode={search_mode}")

        # Build initial state and config
        inputs = create_initial_state(query.strip(), search_mode=search_mode)

        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": (
                2 + settings.GRAPH_MAX_SEARCH_ITERATIONS * 3
            ),
        }

        try:
            yield from stream_graph_events(self._agent, inputs, config)
            logger.info("Agent 流式调用完成")

        except Exception as e:
            logger.error(f"Agent 流式调用失败: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": f"处理您的问题时发生错误: {str(e)}",
            }
            yield {"type": "done", "content": None}

    # =================================================================
    # 中断恢复接口
    # =================================================================

    def resume_chat_stream(
        self,
        thread_id: str,
        resume_input: Dict[str, Any],
    ) -> Generator[Dict[str, Any], None, None]:
        """
        恢复被中断的图执行。

        当图在 human_review_node 处暂停后，用户通过此方法
        传入选择结果来恢复执行。

        Args:
            thread_id:    被中断的会话 thread_id
            resume_input: 用户的恢复输入，如 {"selected_angles": ["angle1"]}

        Yields:
            与 chat_stream 相同的 SSE 事件格式
        """
        self._ensure_initialized()

        from langgraph.types import Command

        logger.info(
            f"Resuming graph: thread_id={thread_id}, "
            f"input_keys={list(resume_input.keys())}"
        )

        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": (
                2 + settings.GRAPH_MAX_SEARCH_ITERATIONS * 3
            ),
        }

        try:
            # Resume with Command
            for event in self._agent.stream(
                Command(resume=resume_input),
                config,
                stream_mode="custom",
            ):
                yield event

            yield {"type": "done", "content": None}
            logger.info(f"Graph resumed and completed: thread_id={thread_id}")

        except Exception as e:
            logger.error(f"Graph resume failed: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": f"恢复执行时发生错误: {str(e)}",
            }
            yield {"type": "done", "content": None}

    # =================================================================
    # 状态检查
    # =================================================================

    def get_status(self) -> Dict[str, Any]:
        """获取 Agent 服务的状态信息"""
        return {
            "initialized": self._initialized,
            "model": settings.LLM_MODEL_NAME,
            "framework": "LangGraph Custom StateGraph (v3.0)",
            "features": {
                "parallel_search": True,       # Send API
                "conditional_routing": True,    # 条件边
                "checkpointing": settings.GRAPH_ENABLE_CHECKPOINTING,
                "checkpoint_type": settings.GRAPH_CHECKPOINT_TYPE,
                "interrupt": settings.GRAPH_ENABLE_INTERRUPT,
            },
            "config": {
                "max_iterations": settings.GRAPH_MAX_SEARCH_ITERATIONS,
                "max_angles": settings.GRAPH_MAX_SEARCH_ANGLES,
                "retrieval_top_k": settings.RETRIEVAL_TOP_K,
            },
            "vector_store": get_vector_service().get_stats(),
        }


# ================================================================
# 全局单例
# ================================================================

_agent_service_instance: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """获取全局唯一的 AgentService 实例"""
    global _agent_service_instance
    if _agent_service_instance is None:
        _agent_service_instance = AgentService()
    return _agent_service_instance
