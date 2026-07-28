"""
Graph Node Functions Module
============================
Implements all nodes for the custom LangGraph research graph.

Each node is a standalone function that:
    1. Reads needed fields from the state
    2. Performs its task (LLM call, vector search, etc.)
    3. Returns a partial state dict with updates
    4. Emits custom events via get_stream_writer() for SSE streaming

Node types:
    - plan_node:       LLM decomposes query into search angles
    - search_angle_node: Executes vector search (called via Send API, no LLM)
    - evaluate_results_node: LLM judges if results are sufficient
    - synthesize_node: LLM generates final answer with streaming tokens
    - human_review_node: LangGraph interrupt() for user confirmation
"""

from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from config.settings import settings
from prompts.templates import (
    AGENT_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    EVALUATION_PROMPT,
    SYNTHESIS_PROMPT,
)
from service.graph.state import ResearchState, SearchAngleState
from service.vector_service import get_vector_service
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ======================================================================
# Specialized LLM Instances (lazy-loaded)
# ======================================================================

_plan_llm: Optional[ChatOpenAI] = None
_eval_llm: Optional[ChatOpenAI] = None
_synthesize_llm: Optional[ChatOpenAI] = None


def _get_plan_llm() -> ChatOpenAI:
    """Plan LLM: low temperature for consistent query decomposition."""
    global _plan_llm
    if _plan_llm is None:
        _plan_llm = ChatOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.2,
            max_retries=settings.MAX_RETRIES,
        )
    return _plan_llm


def _get_eval_llm() -> ChatOpenAI:
    """Evaluate LLM: very low temperature for deterministic judgment."""
    global _eval_llm
    if _eval_llm is None:
        _eval_llm = ChatOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.0,
            max_retries=settings.MAX_RETRIES,
        )
    return _eval_llm


def _get_synthesize_llm() -> ChatOpenAI:
    """Synthesize LLM: streaming enabled for token-by-token output."""
    global _synthesize_llm
    if _synthesize_llm is None:
        _synthesize_llm = ChatOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True,
            max_retries=settings.MAX_RETRIES,
        )
    return _synthesize_llm


# ======================================================================
# Node: Plan
# ======================================================================

def plan_node(state: ResearchState) -> Dict[str, Any]:
    """
    Analyze user query and decompose into 1~5 search angles.

    This is the first node after START. It uses a specialized LLM to
    identify what aspects of the question need to be searched.
    Simple/greeting questions may result in zero angles (straight to synthesize).

    Reads:  query, messages, search_iteration, search_results (for context)
    Writes: search_angles, search_iteration (+1), phase="plan", messages
    """
    writer = get_stream_writer()

    query = state.get("query", "")
    iteration = state.get("search_iteration", 0) + 1

    logger.info(f"[plan_node] Iteration {iteration}: planning for query='{query[:80]}...'")

    # --- Quick check: is this a non-search question? ---
    greeting_patterns = ["你好", "hello", "hi", "你能做什么", "你是谁", "谢谢", "thank"]
    if any(p in query.lower() for p in greeting_patterns):
        logger.info("[plan_node] Detected greeting/non-search query, skipping search")
        return {
            "search_angles": [],
            "search_iteration": iteration,
            "phase": "plan",
            "messages": [AIMessage(content="[Planning: no search needed for this query]")],
        }

    # --- Local library check: user asks about papers already stored locally ---
    local_patterns = ["本地", "local", "知识库", "已入库", "已有", "现有", "存了", "下载了", "my paper"]
    is_local_query = any(p in query.lower() for p in local_patterns)

    # --- Direct local paper listing: "本地有哪些论文" → fetch file list, skip search ---
    listing_patterns = ["罗列", "列出", "有哪些", "有什么", "多少篇", "多少本", "list", "告诉我", "显示", "所有", "全部", "发我", "给我", "都有什么", "都有哪些", "看看", "哪些"]
    is_listing = any(p in query.lower() for p in listing_patterns)
    paper_mention_any = any(w in query.lower() for w in ["论文", "paper", "文献", "pdf"])

    if is_local_query and is_listing and paper_mention_any:
        logger.info(f"[plan_node] Detected LOCAL PAPER LISTING intent: '{query[:80]}...'")
        writer({"type": "status", "content": "📂 正在查询本地论文库…"})

        # Fetch from both SQLite paper library (metadata) and local storage (files)
        try:
            from service.storage_service import get_storage_service
            from service.paper_library import get_paper_library

            storage = get_storage_service()
            file_papers = storage.list_objects(prefix="papers/") if storage else []

            paper_lib = get_paper_library()
            db_papers = paper_lib.list_papers(limit=500)

            if db_papers:
                # Rich listing from SQLite: title, authors, quality score
                lines = []
                for i, p in enumerate(db_papers, 1):
                    title = p.get("title", "无标题")
                    authors = p.get("authors", "")
                    if authors:
                        # Truncate long author lists
                        author_list = authors.split(",") if "," in authors else [authors]
                        authors_short = ", ".join(a.strip()[:20] for a in author_list[:2])
                        if len(author_list) > 2:
                            authors_short += " 等"
                    else:
                        authors_short = "未知作者"
                    score = p.get("quality_score") or 0
                    status = p.get("status", "")
                    lines.append(f"{i}. **{title}** — {authors_short}")
                    if score > 0:
                        lines[-1] += f" [质量分:{score:.0f}]"
                    if status:
                        lines[-1] += f" [{status}]"
                paper_list = "\n".join(lines)
                context_msg = (
                    f"[系统上下文] 用户询问本地有哪些论文。以下是本地论文数据库中的实际论文列表"
                    f"（共 {len(db_papers)} 篇）：\n\n{paper_list}\n\n"
                    f"请根据以上真实论文列表回答用户，不要编造论文名称。"
                )
            elif file_papers:
                # Fallback: file listing without metadata
                lines = []
                for i, p in enumerate(file_papers, 1):
                    name = p["name"].replace("papers/", "")
                    size_mb = p.get("size", 0) / (1024 * 1024)
                    lines.append(f"{i}. {name} ({size_mb:.1f} MB)")
                file_list = "\n".join(lines)
                context_msg = (
                    f"[系统上下文] 用户询问本地有哪些论文。以下是本地论文目录的实际文件列表"
                    f"（共 {len(file_papers)} 篇）：\n\n{file_list}\n\n"
                    f"请根据以上真实文件列表回答用户，不要编造论文名称。"
                )
            else:
                context_msg = (
                    "[系统上下文] 用户询问本地有哪些论文。当前本地论文库为空，"
                    "没有任何论文。请如实告知用户。"
                )
        except Exception as e:
            logger.error(f"Failed to list local papers: {e}")
            context_msg = "[系统上下文] 用户询问本地论文列表，但读取数据库失败，请告知用户稍后重试。"

        return {
            "search_angles": [],
            "search_iteration": iteration,
            "phase": "plan",
            "discovery_mode": False,
            "search_mode": "local",
            "messages": [AIMessage(content=context_msg)],
        }

    # --- Search mode override (from UI toggle) ---
    search_mode = state.get("search_mode", "auto")

    # Force arXiv discovery mode
    if search_mode == "arxiv":
        logger.info(f"[plan_node] Search mode override: FORCE ARXIV DISCOVERY")
        writer({"type": "status", "content": "🌐 联网搜索模式：正在搜索 arXiv..."})
        return {
            "search_angles": [],
            "search_iteration": iteration,
            "phase": "plan",
            "discovery_mode": True,
            "messages": [AIMessage(content=f"[Planning: forced arXiv discovery mode for '{query}']")],
        }

    # Force local search only (skip discovery mode)
    if search_mode == "local":
        is_local_query = True  # Block discovery mode below

    # --- Discovery intent detection: user wants to FIND new papers ---
    discovery_patterns = [
        "查询", "查找", "找", "搜索", "检索", "发现",
        "find", "search", "discover", "look for", "latest",
        "最新", "最近", "近期", "有哪些", "有没有", "帮我找",
        "推荐", "recommend", "browse", "浏览",
    ]
    is_discovery = any(p in query.lower() for p in discovery_patterns)
    # Stronger signal: query explicitly mentions "论文" or "paper" + discovery verb
    paper_mention = any(w in query.lower() for w in ["论文", "paper", "文献", "article", "工作", "work"])
    # Skip discovery mode if user is asking about local papers
    if is_discovery and paper_mention and not is_local_query:
        logger.info(f"[plan_node] Detected PAPER DISCOVERY intent: '{query[:80]}...'")
        writer({"type": "status", "content": "🔍 检测到论文发现意图，将直接搜索 arXiv..."})
        return {
            "search_angles": [],
            "search_iteration": iteration,
            "phase": "plan",
            "discovery_mode": True,
            "messages": [AIMessage(content=f"[Planning: paper discovery mode — searching arXiv for '{query}']")],
        }

    writer({"type": "status", "content": f"🔍 正在规划第 {iteration} 轮搜索..."})

    # --- Build planning prompt ---
    previous_context = ""
    existing_results = state.get("search_results", {})
    if existing_results and iteration > 1:
        angles_done = list(existing_results.keys())
        doc_count = sum(len(docs) for docs in existing_results.values())
        previous_context = (
            f"\n\n## 之前已搜索的角度\n"
            + "\n".join(f"- {a}" for a in angles_done)
            + f"\n\n## 已检索到 {doc_count} 个相关片段"
            + f"\n请基于已有结果，确定是否还需要新的搜索角度。"
        )

    messages = [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=f"用户问题: {query}{previous_context}"),
    ]

    try:
        llm = _get_plan_llm()
        response = llm.invoke(messages)

        # Parse "- " prefixed lines as angles
        angles = _parse_search_angles(response.content)

        logger.info(
            f"[plan_node] Identified {len(angles)} search angles: {angles}"
        )

        writer({
            "type": "status",
            "content": (
                f"📋 识别到 {len(angles)} 个搜索方向"
                + (f": {angles[0][:50]}..." if angles else "")
            ),
        })

        return {
            "search_angles": angles,
            "search_iteration": iteration,
            "phase": "plan",
            "messages": [AIMessage(content=response.content)],
        }

    except Exception as e:
        logger.error(f"[plan_node] Failed: {e}", exc_info=True)
        # Fallback: use the original query as the only search angle
        return {
            "search_angles": [query],
            "search_iteration": iteration,
            "phase": "plan",
            "messages": [AIMessage(content=f"Planning fallback: using original query")],
        }


def _parse_search_angles(text: str) -> List[str]:
    """
    Parse LLM output for search angle lines.

    Expects lines starting with "- " as search angles.
    Strips numbering, markdown, and whitespace.
    """
    angles = []
    for line in text.strip().split("\n"):
        line = line.strip()
        # Match "- angle text" pattern
        if line.startswith("- "):
            angle = line[2:].strip()
            # Remove leading numbering like "1. " or "1)"
            while angle and (angle[0].isdigit() or angle[0] in ". )-"):
                angle = angle[1:].strip()
            if angle and len(angle) > 3:
                angles.append(angle)
    return angles[:settings.GRAPH_MAX_SEARCH_ANGLES]


# ======================================================================
# Node: Human Review (interrupt before expensive search)
# ======================================================================

def human_review_node(state: ResearchState) -> Dict[str, Any]:
    """
    Pause graph execution and ask user to confirm the search plan.

    This node is only reached when GRAPH_ENABLE_INTERRUPT=True and
    the number of search angles >= GRAPH_INTERRUPT_ANGLE_THRESHOLD.

    Uses LangGraph's interrupt() to pause and wait for user resume.

    Reads:  search_angles
    Writes: search_angles (potentially filtered by user), phase="plan"
    """
    writer = get_stream_writer()
    angles = state.get("search_angles", [])

    logger.info(
        f"[human_review_node] Pausing for user review: {len(angles)} angles"
    )

    interrupt_payload = {
        "type": "human_review",
        "question": (
            f"我识别了 {len(angles)} 个搜索方向，是否全部执行？"
            f"如果只关注其中几个，请选择后再继续。"
        ),
        "angles": angles,
    }

    writer({
        "type": "interrupt",
        "content": interrupt_payload,
    })

    # This pauses the graph until Command(resume=...) is received
    user_response = interrupt(interrupt_payload)

    # User resumed — check if they filtered the angles
    selected = user_response.get("selected_angles", angles) if user_response else angles

    if selected and selected != angles:
        logger.info(
            f"[human_review_node] User filtered angles: {len(angles)} → {len(selected)}"
        )
        return {"search_angles": selected, "phase": "plan"}

    return {"phase": "plan"}


# ======================================================================
# Node: Search Angle (called via Send API — no LLM, parallel execution)
# ======================================================================

def search_angle_node(state: SearchAngleState) -> Dict[str, Any]:
    """
    Execute vector search for a single search angle.

    This node is called N times in parallel via the Send API.
    Each invocation searches one angle independently and returns
    its results, which are merged by the reduce_search_results reducer.

    NO LLM calls — pure vector store retrieval.
    """
    writer = get_stream_writer()

    angle = state.get("angle", "")
    query = state.get("query", "")

    if not angle:
        return {"search_results": {}}

    logger.info(f"[search_angle_node] Searching: '{angle[:80]}...'")

    writer({
        "type": "status",
        "content": f"🔎 正在搜索: {angle[:60]}...",
    })

    try:
        vector_service = get_vector_service()

        if not vector_service.is_initialized:
            logger.warning("[search_angle_node] Vector store not initialized")
            return {"search_results": {angle: []}}

        documents = vector_service.similarity_search(
            query=angle,
            k=settings.RETRIEVAL_TOP_K,
        )

        # Filter out placeholder documents
        documents = [
            d for d in documents
            if d.metadata.get("section") != "__placeholder__"
        ]

        logger.info(
            f"[search_angle_node] Found {len(documents)} results for '{angle[:50]}...'"
        )

        writer({
            "type": "status",
            "content": f"✅ 「{angle[:40]}...」— 找到 {len(documents)} 个相关片段",
        })

        return {"search_results": {angle: documents}}

    except Exception as e:
        logger.error(
            f"[search_angle_node] Search failed for '{angle}': {e}", exc_info=True
        )
        return {"search_results": {angle: []}}


# ======================================================================
# Node: Evaluate Results
# ======================================================================

def evaluate_results_node(state: ResearchState) -> Dict[str, Any]:
    """
    Evaluate whether collected search results are sufficient to answer.

    LLM reviews all results gathered so far and decides:
    - SUFFICIENT: enough to proceed to synthesis
    - NEEDS_MORE: should loop back to plan for another search iteration

    Reads:  query, search_results, search_iteration
    Writes: evaluation, evaluation_reason, phase="evaluate"
    """
    writer = get_stream_writer()

    query = state.get("query", "")
    results = state.get("search_results", {})
    iteration = state.get("search_iteration", 1)
    max_iterations = settings.GRAPH_MAX_SEARCH_ITERATIONS

    logger.info(
        f"[evaluate_results_node] Evaluating: "
        f"{sum(len(v) for v in results.values())} total docs "
        f"from {len(results)} angles, iteration {iteration}/{max_iterations}"
    )

    writer({"type": "status", "content": "🤔 正在评估检索结果是否充分..."})

    # --- Build evaluation context ---
    context_parts = []
    for angle, docs in results.items():
        context_parts.append(f"\n### 搜索角度: {angle}")
        context_parts.append(f"找到 {len(docs)} 个相关片段")
        for i, doc in enumerate(docs[:3], 1):  # Show up to 3 per angle
            snippet = doc.page_content[:200].replace("\n", " ")
            title = doc.metadata.get("title", "未知")
            context_parts.append(f"  [{i}] {title}: {snippet}...")

    if not context_parts:
        # No results at all — skip evaluation, go straight to synthesize
        logger.info("[evaluate_results_node] No results to evaluate, marking sufficient")
        return {
            "evaluation": "sufficient",
            "evaluation_reason": "未检索到任何结果",
            "phase": "evaluate",
        }

    context_text = "\n".join(context_parts)

    try:
        eval_prompt = EVALUATION_PROMPT.format(
            query=query,
            context=context_text,
            iteration=iteration,
            max_iterations=max_iterations,
        )

        llm = _get_eval_llm()
        response = llm.invoke([HumanMessage(content=eval_prompt)])
        content = response.content.strip()

        # Parse decision
        if content.upper().startswith("SUFFICIENT"):
            evaluation = "sufficient"
        else:
            evaluation = "needs_more"

        reason = content.split(":", 1)[1].strip() if ":" in content else content

        logger.info(f"[evaluate_results_node] Decision: {evaluation} — {reason[:80]}")

        writer({
            "type": "status",
            "content": (
                "✅ 检索结果充分，开始生成回答"
                if evaluation == "sufficient"
                else f"🔄 需要补充检索: {reason[:60]}..."
            ),
        })

        return {
            "evaluation": evaluation,
            "evaluation_reason": reason,
            "phase": "evaluate",
        }

    except Exception as e:
        logger.error(f"[evaluate_results_node] Failed: {e}", exc_info=True)
        # On error, proceed to synthesis with whatever we have
        return {
            "evaluation": "sufficient",
            "evaluation_reason": f"评估失败，基于已有结果生成回答: {e}",
            "phase": "evaluate",
        }


# ======================================================================
# Node: Synthesize
# ======================================================================

# ======================================================================
# Node: arXiv Search (external paper discovery fallback)
# ======================================================================

def arxiv_search_node(state: ResearchState) -> Dict[str, Any]:
    """
    Search arXiv for papers when local vector store has insufficient results.

    This node is reached when:
        - Local FAISS search returns 0 results for ALL angles, OR
        - The evaluate node says "needs_more" and arXiv hasn't been tried yet

    It calls the PaperDiscoveryService to search arXiv, then formats
    the paper metadata as search result documents so the synthesize_node
    can use them just like local results.

    Reads:  query
    Writes: search_results (augmented with arXiv papers), arxiv_searched=True,
            phase="arxiv_search"
    """
    writer = get_stream_writer()

    query = state.get("query", "")
    existing_results = state.get("search_results", {})

    total_local = sum(len(v) for v in existing_results.values())
    logger.info(
        f"[arxiv_search_node] Local results: {total_local} docs. "
        f"Falling back to arXiv for '{query[:80]}...'"
    )

    writer({
        "type": "status",
        "content": "🌐 本地知识库未找到相关内容，正在搜索 arXiv...",
    })

    try:
        from service.paper_discovery_service import get_discovery_service

        discovery = get_discovery_service()
        result = discovery.discover(
            topic=query,
            max_results=5,
            days_back=365,  # Search last year for broader coverage
        )

        papers = result.get("papers", [])
        logger.info(f"[arxiv_search_node] arXiv returned {len(papers)} papers")

        if not papers:
            writer({
                "type": "status",
                "content": "😔 arXiv 也未找到相关论文。",
            })
            return {
                "arxiv_searched": True,
                "phase": "arxiv_search",
            }

        # Format arXiv papers as pseudo-documents for synthesize_node
        from langchain_core.documents import Document

        arxiv_docs = []
        for i, paper in enumerate(papers):
            # Build a rich text representation of the paper
            content = (
                f"标题: {paper.get('title', 'Unknown')}\n"
                f"作者: {', '.join(paper.get('authors', [])[:5])}\n"
                f"发布日期: {paper.get('published', 'Unknown')}\n"
                f"arXiv ID: {paper.get('paper_id', 'Unknown')}\n"
                f"URL: {paper.get('url', '')}\n\n"
                f"摘要: {paper.get('abstract', '')}"
            )

            doc = Document(
                page_content=content,
                metadata={
                    "title": paper.get("title", "Unknown"),
                    "section": "Abstract",
                    "source": "arxiv",
                    "arxiv_id": paper.get("paper_id", ""),
                    "url": paper.get("url", ""),
                    "published": paper.get("published", ""),
                    "authors": ", ".join(paper.get("authors", [])[:5]),
                },
            )
            arxiv_docs.append(doc)

        writer({
            "type": "status",
            "content": f"✅ arXiv 找到 {len(papers)} 篇相关论文",
        })

        # Add arXiv results as a new search angle
        updated_results = dict(existing_results)
        updated_results["arXiv 检索结果"] = arxiv_docs

        return {
            "search_results": updated_results,
            "arxiv_searched": True,
            "phase": "arxiv_search",
        }

    except Exception as e:
        logger.error(f"[arxiv_search_node] arXiv search failed: {e}", exc_info=True)
        writer({
            "type": "status",
            "content": f"⚠️ arXiv 搜索失败: {str(e)[:50]}",
        })
        return {
            "arxiv_searched": True,
            "phase": "arxiv_search",
        }


def synthesize_node(state: ResearchState) -> Dict[str, Any]:
    """
    Generate the final answer from all collected search results.

    This node streams tokens via get_stream_writer() for real-time SSE output.
    It uses the main AGENT_SYSTEM_PROMPT to maintain consistent persona.

    Reads:  query, search_results, messages
    Writes: final_answer, sources, phase="synthesize"
    """
    writer = get_stream_writer()

    query = state.get("query", "")
    results = state.get("search_results", {})

    total_docs = sum(len(v) for v in results.values())
    logger.info(
        f"[synthesize_node] Synthesizing answer from {total_docs} docs "
        f"across {len(results)} angles"
    )

    # --- Check if we have arXiv results ---
    has_arxiv = any(
        doc.metadata.get("source") == "arxiv"
        for docs in results.values()
        for doc in docs
    )

    # --- If no results, generate a direct answer ---
    if not results or total_docs == 0:
        logger.info("[synthesize_node] No search results, generating direct answer")
        writer({"type": "status", "content": "📝 生成回答（本地和 arXiv 均未找到相关内容）..."})

        # 收集 plan_node（或其他上游节点）注入到 messages 中的上下文
        state_messages = state.get("messages", [])
        context_msgs = [
            msg for msg in state_messages
            if isinstance(msg, AIMessage) and msg.content.startswith("[系统上下文]")
        ]

        messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT)]
        messages.extend(context_msgs)
        messages.append(HumanMessage(content=query))

        full_answer = ""
        try:
            llm = _get_synthesize_llm()
            for chunk in llm.stream(messages):
                if chunk.content:
                    if isinstance(chunk.content, str):
                        writer({"type": "token", "content": chunk.content})
                        full_answer += chunk.content
        except Exception as e:
            logger.error(f"[synthesize_node] Streaming failed: {e}", exc_info=True)
            full_answer = f"生成回答时发生错误: {str(e)}"

        return {
            "final_answer": full_answer,
            "sources": [],
            "phase": "synthesize",
        }

    # --- Build context from search results ---
    context_parts = []
    sources = []

    for angle, docs in results.items():
        for doc in docs:
            meta = doc.metadata
            title = meta.get("title", meta.get("file_name", "未知"))
            section = meta.get("section", "未知")

            # Collect source info
            source_key = title
            if not any(s["title"] == source_key for s in sources):
                sources.append({
                    "title": title,
                    "sections": [section],
                })
            else:
                for s in sources:
                    if s["title"] == title and section not in s["sections"]:
                        s["sections"].append(section)

    # Deduplicate and format context
    seen_content = set()
    for angle, docs in results.items():
        context_parts.append(f"\n### 搜索角度: {angle}")
        for doc in docs:
            content_key = doc.page_content[:80]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)

            title = doc.metadata.get("title", "未知")
            section = doc.metadata.get("section", "")
            content = doc.page_content.strip()
            if len(content) > 1200:
                content = content[:1200] + "..."

            context_parts.append(
                f"\n[来源: {title}" + (f", {section}" if section else "") + "]"
                f"\n{content}\n"
            )

    context_text = "\n".join(context_parts)

    # Limit context to avoid exceeding token limits
    if len(context_text) > 8000:
        context_text = context_text[:8000] + "\n...(上下文已截断)"

    # --- Generate answer with streaming ---
    arxiv_note = ""
    if has_arxiv:
        arxiv_note = (
            "\n\n**注意**: 以上部分内容来自 arXiv 外部搜索，非本地知识库中的论文全文。"
            "请在回答中明确标注哪些信息来自 arXiv 摘要，"
            "并建议用户如需深入分析可上传该论文的 PDF 到系统。"
        )
        writer({
            "type": "status",
            "content": f"📝 基于 {total_docs} 个片段生成回答（含 arXiv 外部搜索）...",
        })
    else:
        writer({
            "type": "status",
            "content": f"📝 基于 {total_docs} 个片段生成回答...",
        })

    synthesis_user_prompt = SYNTHESIS_PROMPT.format(
        query=query,
        context=context_text,
    ) + arxiv_note

    messages = [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_user_prompt),
    ]

    full_answer = ""
    try:
        llm = _get_synthesize_llm()
        for chunk in llm.stream(messages):
            if chunk.content:
                if isinstance(chunk.content, str):
                    writer({"type": "token", "content": chunk.content})
                    full_answer += chunk.content
                elif isinstance(chunk.content, list):
                    for item in chunk.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            writer({"type": "token", "content": item["text"]})
                            full_answer += item["text"]
    except Exception as e:
        logger.error(f"[synthesize_node] Streaming failed: {e}", exc_info=True)
        full_answer = f"生成回答时发生错误: {str(e)}"
        writer({"type": "token", "content": full_answer})

    logger.info(
        f"[synthesize_node] Answer generated: {len(full_answer)} chars, "
        f"{len(sources)} sources"
    )

    return {
        "final_answer": full_answer,
        "sources": sources,
        "phase": "synthesize",
    }
