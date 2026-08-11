"""
Flask 应用主入口 — Paper-Copilot
=================================
学术论文检索与整理 Agent 系统

启动流程:
    1. 加载环境变量配置
    2. 初始化日志系统
    3. 初始化本地存储目录
    4. 检查并恢复向量数据库备份
    5. 启动 Flask HTTP 服务

核心 API 接口:
    POST /api/upload     — 知识入库（上传 PDF → 解析 → 向量化 → 备份）
    POST /api/chat       — RAG Agent 交互（流式/非流式）
    POST /api/summarize  — 文献结构化整理（六段式学术总结）
    POST /api/scan       — 扫描本地目录中的 PDF 并自动入库
    GET  /api/health     — 健康检查

设计约束:
    - 所有接口返回标准 JSON 结构: {"code": int, "message": str, "data": Any}
    - 流式接口使用 Server-Sent Events (SSE) 协议
    - 上传文件大小限制由 settings.MAX_UPLOAD_SIZE_MB 控制
"""

import json
import time
import traceback
from pathlib import Path
from typing import Dict, Any

from flask import Flask, request, jsonify, Response, stream_with_context, render_template, send_from_directory

from config.settings import settings
from utils.logger import setup_logger

# ================================================================
# 应用初始化
# ================================================================

app = Flask(__name__)

# 配置 Flask 内置参数
app.config["MAX_CONTENT_LENGTH"] = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
app.config["JSON_AS_ASCII"] = False  # 确保 JSON 中中文正常显示

# 初始化日志
logger = setup_logger("PaperCopilot.App")

# ================================================================
# 启动时的初始化 Hook
# ================================================================

def _init_storage() -> bool:
    """
    启动步骤 1: 初始化本地存储目录。

    创建 papers/ 和 backups/ 目录，用于后续 PDF 存储和向量库备份。
    本地文件系统无需网络连接，正常情况下总是成功。
    """
    from service.storage_service import LocalStorageService

    logger.info("=" * 60)
    logger.info("Paper-Copilot 启动初始化开始...")
    logger.info("=" * 60)

    storage_service = LocalStorageService()
    ready = storage_service.connect()

    if ready:
        logger.info("[步骤 1/3] 本地存储初始化成功 ✓")
    else:
        logger.critical(
            "[步骤 1/3] 本地存储初始化失败 ✗ — "
            "无法创建数据目录，请检查磁盘权限！"
        )

    # 注册为全局单例
    _register_storage_service(storage_service)
    return ready


def _init_vector_store() -> Dict[str, Any]:
    """
    启动步骤 2: 初始化向量数据库。

    加载顺序:
        1. 首先尝试从本地磁盘加载 Chroma 向量库
        2. 如果本地不存在，尝试从本地备份目录恢复
        3. 如果备份也不存在，创建空白向量库
    """
    from service.storage_service import get_storage_service
    from service.vector_service import get_vector_service

    logger.info("[步骤 2/3] 正在初始化向量数据库...")

    vector_service = get_vector_service()
    storage_service = get_storage_service()

    # 尝试从本地加载
    loaded_from_local = vector_service.load_or_create()

    if loaded_from_local:
        logger.info("[步骤 2/3] 向量数据库从本地加载成功 ✓")
        return {"source": "local", "document_count": "已恢复"}

    # 本地加载失败，尝试从本地备份恢复
    logger.info("[步骤 2/3] 尝试从本地备份恢复向量库...")

    downloaded = storage_service.download_vector_backup()

    if downloaded:
        # 备份恢复成功，重新加载
        loaded = vector_service.load_or_create()
        if loaded:
            logger.info("[步骤 2/3] 向量数据库从本地备份恢复成功 ✓")
            return {"source": "local_backup", "document_count": "已恢复"}
        else:
            logger.error("[步骤 2/3] 备份文件已找到但加载失败")
    else:
        logger.info("[步骤 2/3] 本地未找到向量库备份")

    # 既无本地也无备份 → 空白向量库
    logger.info("[步骤 2/3] 以空白向量库启动（等待论文上传）")
    return {"source": "empty", "document_count": 0}


def _init_agent_services():
    """
    启动步骤 3: 预热 Agent 和 Summarize 服务。

    预先初始化 LLM 连接和 Agent 组件，
    避免首次请求时的冷启动延迟。
    """
    from service.agent_service import get_agent_service
    from service.summarize_service import get_summarize_service

    logger.info("[步骤 3/3] 正在预热 Agent 服务...")

    agent_service = get_agent_service()
    # 触发懒加载初始化
    agent_service._ensure_initialized()

    summarize_service = get_summarize_service()
    # 访问 llm 属性触发初始化
    _ = summarize_service.llm

    logger.info("[步骤 3/3] Agent 服务预热完成 ✓")


def _print_startup_banner():
    """打印启动成功的横幅"""
    stats = _get_system_stats()
    logger.info("=" * 60)
    logger.info("🎓 Paper-Copilot 启动成功！")
    logger.info(f"   LLM 模型:    {settings.LLM_MODEL_NAME}")
    logger.info(f"   Embedding:   {settings.EMBEDDING_MODEL_NAME}")
    logger.info(f"   向量库文档:  {stats['vector_store']['document_count']}")
    logger.info(f"   本地论文数:  {stats['papers_count']}")
    logger.info(f"   数据目录:    {settings.PAPERS_DIR}")
    logger.info(f"   API 地址:    http://0.0.0.0:5000")
    logger.info("=" * 60)


# ================================================================
# 存储服务获取（委托给 service.storage_service 单例）
# ================================================================

def get_storage_service():
    """获取本地存储服务全局单例（委托给 service 包）"""
    from service.storage_service import get_storage_service as _get
    return _get()


def _register_storage_service(service):
    """注册存储服务实例到 service 包的单例中"""
    import service.storage_service as mod
    mod._storage_service_instance = service


# ================================================================
# 辅助函数
# ================================================================

def _make_response(code: int, message: str, data: Any = None) -> tuple:
    """
    构造标准的 API JSON 响应。

    Args:
        code: HTTP 状态码（业务层面）
        message: 人类可读的状态描述
        data: 响应数据体

    Returns:
        (json_response, http_status_code) 元组
    """
    body = {
        "code": code,
        "message": message,
        "data": data,
    }
    http_status = code if 100 <= code < 600 else 500
    return jsonify(body), http_status


def _get_system_stats() -> Dict[str, Any]:
    """收集系统运行状态统计"""
    from service.vector_service import get_vector_service
    from service.paper_library import get_paper_library

    storage_service = get_storage_service()
    vector_service = get_vector_service()
    paper_lib = get_paper_library()

    # 以 SQLite 数据库为论文数量的唯一权威来源
    db_count = paper_lib.count() if paper_lib else 0

    return {
        "storage_ready": storage_service.is_connected() if storage_service else False,
        "papers_count": db_count,
        "vector_store": vector_service.get_stats() if vector_service else {},
        "model": settings.LLM_MODEL_NAME,
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
    }


# ================================================================
# 前端页面路由
# ================================================================

FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

@app.route("/")
def index():
    """
    前端首页 — 返回 Vue 3 + Vite SPA。
    生产环境使用 npm run build 构建产物，开发环境使用 npm run dev (Vite dev server :5173)。
    """
    if FRONTEND_DIST.exists():
        return send_from_directory(FRONTEND_DIST, "index.html")
    # Fallback for dev without build: use old Jinja template
    return render_template("index.html")

@app.route("/assets/<path:filename>")
def spa_assets(filename):
    """
    SPA 静态资源（JS / CSS / 字体等），带长期缓存。
    """
    return send_from_directory(FRONTEND_DIST / "assets", filename, max_age=31536000)


# ================================================================
# API 路由: 健康检查
# ================================================================

@app.route("/api/health", methods=["GET"])
def health_check():
    """
    健康检查接口。

    返回系统各组件的运行状态，用于监控和调试。

    Returns:
        {
            "code": 200,
            "message": "ok",
            "data": {
                "status": "healthy",
                "storage_ready": bool,
                "papers_count": int,
                "vector_store": {...},
                "uptime_seconds": float
            }
        }
    """
    stats = _get_system_stats()
    return _make_response(
        code=200,
        message="Paper-Copilot 运行中",
        data={
            "status": "healthy",
            **stats,
        },
    )


# ================================================================
# API 路由: 知识入库 (PDF Upload)
# ================================================================

@app.route("/api/upload", methods=["POST"])
def upload_paper():
    """
    知识入库接口 — 上传 PDF 论文并完成全流程入库。

    请求格式: multipart/form-data
    参数:
        - file: PDF 文件（必填，最大 {MAX_UPLOAD_SIZE_MB}MB）

    处理流程:
        1. 校验文件类型和大小
        2. 保存原始 PDF 到本地 papers 目录
        3. 提取 PDF 全文文本（处理双栏排版）
        4. 基于学术章节的语义切片
        5. 向量化并写入 Chroma 本地向量库
        6. 备份向量库到本地 backups 目录

    Returns:
        {
            "code": 200,
            "message": "论文入库成功",
            "data": {
                "file_name": str,
                "storage_object": str,
                "page_count": int,
                "chunk_count": int,
                "content_hash": str,
                "sections_detected": [...]
            }
        }
    """
    from service.pdf_service import PDFService
    from service.vector_service import get_vector_service

    # ----------------------------------------------------------
    # 步骤 1: 文件校验
    # ----------------------------------------------------------
    if "file" not in request.files:
        return _make_response(400, "请求中未包含文件，请使用 'file' 字段上传 PDF")

    file = request.files["file"]

    if file.filename == "" or file.filename is None:
        return _make_response(400, "文件名为空")

    if not file.filename.lower().endswith(".pdf"):
        return _make_response(
            400,
            f"不支持的文件类型，仅接受 PDF 文件。当前文件名: {file.filename}",
        )

    # 读取文件内容到内存
    file_data = file.read()
    file_size_mb = len(file_data) / (1024 * 1024)

    if len(file_data) == 0:
        return _make_response(400, "上传的文件为空")

    if file_size_mb > settings.MAX_UPLOAD_SIZE_MB:
        return _make_response(
            400,
            f"文件过大 ({file_size_mb:.1f} MB)，"
            f"上限为 {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    logger.info(
        f"收到 PDF 上传请求: file={file.filename}, "
        f"size={file_size_mb:.2f} MB"
    )

    start_time = time.time()

    try:
        # ----------------------------------------------------------
        # 步骤 2: 保存原始 PDF 到本地
        # ----------------------------------------------------------
        storage_service = get_storage_service()
        if not storage_service.is_connected():
            return _make_response(
                503,
                "本地存储不可用，无法保存文件。请检查磁盘权限。",
            )

        storage_object = storage_service.upload_pdf(file_data, file.filename)
        if storage_object is None:
            return _make_response(500, "PDF 保存到本地失败，请稍后重试")

        # ----------------------------------------------------------
        # 步骤 3: PDF 文本提取
        # ----------------------------------------------------------
        pdf_service = PDFService()
        full_text, pdf_metadata = pdf_service.extract_text(file_data, file.filename)

        if not full_text or len(full_text.strip()) < 50:
            return _make_response(
                400,
                "PDF 文本提取失败或内容过短。"
                "该 PDF 可能是扫描版（纯图片），暂不支持 OCR 识别。",
            )

        # 提取论文元数据（标题等）—— 传入 PDF 级别元数据辅助提取
        paper_metadata = pdf_service.extract_paper_metadata(full_text, file.filename, pdf_metadata)
        # 合并 PDF 级别元数据（content_hash, page_count 等）
        paper_metadata.update({k: v for k, v in pdf_metadata.items() if k not in ("pdf_metadata", "first_page_fonts")})

        # ----------------------------------------------------------
        # 步骤 4: 语义切片
        # ----------------------------------------------------------
        documents = pdf_service.semantic_chunk(full_text, paper_metadata)

        if not documents:
            return _make_response(500, "论文文本切片失败，未生成有效文档块")

        # 收集检测到的章节信息
        sections_detected = sorted(set(
            doc.metadata.get("section", "未知")
            for doc in documents
        ))

        # ----------------------------------------------------------
        # 步骤 5: 向量化写入
        # ----------------------------------------------------------
        vector_service = get_vector_service()
        if not vector_service.is_initialized:
            vector_service.load_or_create()

        chunk_count = vector_service.add_documents(documents)

        # 写入 SQLite 元数据库
        try:
            from service.paper_library import get_paper_library
            paper_lib = get_paper_library()
            paper_lib.add_paper({
                "paper_id": paper_metadata.get("title", file.filename).replace(".pdf", ""),
                "title": paper_metadata.get("title", file.filename).replace(".pdf", ""),
                "authors": paper_metadata.get("authors", ""),
                "abstract": full_text[:500] if full_text else "",
                "status": "stored",
                "storage_path": storage_object,
            })
        except Exception as e:
            logger.warning(f"写入元数据库失败（不影响向量库）: {e}")

        # ----------------------------------------------------------
        # 步骤 6: 向量库本地备份
        # ----------------------------------------------------------
        backup_success = storage_service.upload_vector_backup(
            local_dir=settings.VECTOR_DB_PATH,
        )

        elapsed = time.time() - start_time

        logger.info(
            f"论文入库完成: file={file.filename}, "
            f"pages={pdf_metadata['page_count']}, "
            f"chunks={chunk_count}, "
            f"sections={sections_detected}, "
            f"backup={'✓' if backup_success else '✗'}, "
            f"elapsed={elapsed:.2f}s"
        )

        return _make_response(
            code=200,
            message="论文入库成功",
            data={
                "file_name": file.filename,
                "storage_object": storage_object,
                "page_count": pdf_metadata["page_count"],
                "chunk_count": chunk_count,
                "content_hash": pdf_metadata["content_hash"],
                "sections_detected": sections_detected,
                "backup_success": backup_success,
                "elapsed_seconds": round(elapsed, 2),
            },
        )

    except ValueError as e:
        # PDF 解析错误（已知错误类型）
        logger.error(f"PDF 解析失败: {e}")
        return _make_response(400, str(e))

    except Exception as e:
        # 未知错误
        logger.error(f"论文入库失败 (未知错误): {e}\n{traceback.format_exc()}")
        return _make_response(500, f"论文入库处理失败: {str(e)}")


# ================================================================
# API 路由: RAG Agent 交互
# ================================================================

@app.route("/api/chat", methods=["POST"])
def chat_with_agent():
    """
    RAG Agent 交互接口 — 与学术论文知识库进行智能对话。

    请求格式: application/json
    参数:
        {
            "query": str,         # 用户的自然语言提问（必填）
            "stream": bool,       # 是否启用流式输出（可选，默认 false）
            "search_mode": str    # 搜索模式（可选，默认 "auto"）
                                 #   "auto"  — 自动检测意图
                                 #   "local" — 仅本地知识库检索
                                 #   "arxiv" — 联网搜索 arXiv
        }

    流式模式:
        - 响应 Content-Type: text/event-stream
        - 事件格式: data: {"type": "token"|"status"|"done"|"error", "content": "..."}
        - 客户端应持续读取直到收到 type="done" 事件

    非流式模式:
        - 等待 Agent 完整推理完成后一次性返回

    流式安全说明:
        来源信息由 LLM 在回答文本中自然引用（根据系统提示词要求），
        不使用正则表达式在流中捕获或修改链接，
        杜绝了因缓冲分片导致的解析失败问题。

    Returns (非流式):
        {
            "code": 200,
            "message": "success",
            "data": {
                "answer": str,
                "sources": [...]
            }
        }
    """
    from service.agent_service import get_agent_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空，请提供 JSON 格式的数据")

        query = body.get("query", "").strip()
        if not query:
            return _make_response(400, "query 参数不能为空")

        use_stream = body.get("stream", False)
        search_mode = body.get("search_mode", "auto")
        # Validate search_mode
        if search_mode not in ("auto", "local", "arxiv"):
            search_mode = "auto"

        agent_service = get_agent_service()

        # ----------------------------------------------------------
        # 流式模式
        # ----------------------------------------------------------
        if use_stream:
            def generate_sse():
                """生成 SSE 事件流"""
                try:
                    for event in agent_service.chat_stream(query, search_mode=search_mode):
                        event_data = json.dumps(event, ensure_ascii=False)
                        yield f"data: {event_data}\n\n"

                        # 遇到错误或完成信号时退出
                        if event["type"] in ("done", "error"):
                            break
                except Exception as e:
                    logger.error(f"SSE 流生成异常: {e}", exc_info=True)
                    error_event = json.dumps(
                        {"type": "error", "content": f"流式输出异常: {str(e)}"},
                        ensure_ascii=False,
                    )
                    yield f"data: {error_event}\n\n"

            return Response(
                stream_with_context(generate_sse()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
                },
            )

        # ----------------------------------------------------------
        # 非流式模式
        # ----------------------------------------------------------
        else:
            result = agent_service.chat(query, search_mode=search_mode)
            return _make_response(
                code=200,
                message="success",
                data=result,
            )

    except Exception as e:
        logger.error(f"Chat 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"对话处理异常: {str(e)}")


# ================================================================
# API 路由: 中断恢复 (LangGraph interrupt resume)
# ================================================================

@app.route("/api/chat/resume", methods=["POST"])
def resume_chat():
    """
    恢复被中断的 Agent 图执行。

    当 LangGraph 图在 human_review_node 处暂停后，
    客户端通过此端点传入用户的选择来恢复执行。

    请求格式: application/json
    参数:
        {
            "thread_id": str,      # 被中断会话的 thread_id（必填）
            "input": {              # 恢复输入（必填）
                "selected_angles": [...]  # 用户选择的搜索角度
            },
            "stream": bool         # 是否流式输出（可选，默认 false）
        }

    流式模式: SSE（与 /api/chat 流式相同格式）
    """
    from service.agent_service import get_agent_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空，请提供 JSON 格式的数据")

        thread_id = body.get("thread_id", "").strip()
        if not thread_id:
            return _make_response(400, "thread_id 参数不能为空")

        resume_input = body.get("input", {})
        if not resume_input:
            return _make_response(400, "input 参数不能为空")

        use_stream = body.get("stream", False)

        logger.info(
            f"收到恢复请求: thread_id={thread_id}, "
            f"input_keys={list(resume_input.keys())}"
        )

        agent_service = get_agent_service()

        # ----------------------------------------------------------
        # 流式恢复
        # ----------------------------------------------------------
        if use_stream:
            def generate_sse():
                try:
                    for event in agent_service.resume_chat_stream(
                        thread_id, resume_input,
                    ):
                        event_data = json.dumps(event, ensure_ascii=False)
                        yield f"data: {event_data}\n\n"
                        if event["type"] in ("done", "error"):
                            break
                except Exception as e:
                    logger.error(f"Resume SSE 异常: {e}", exc_info=True)
                    error_event = json.dumps(
                        {"type": "error", "content": f"恢复异常: {str(e)}"},
                        ensure_ascii=False,
                    )
                    yield f"data: {error_event}\n\n"

            return Response(
                stream_with_context(generate_sse()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # ----------------------------------------------------------
        # 非流式恢复
        # ----------------------------------------------------------
        else:
            # Collect all events
            events = []
            for event in agent_service.resume_chat_stream(
                thread_id, resume_input,
            ):
                events.append(event)
                if event["type"] in ("done", "error"):
                    break

            # Extract answer from token events
            tokens = [
                e["content"] for e in events
                if e["type"] == "token" and "content" in e
            ]
            answer = "".join(tokens) if tokens else "恢复执行完成，但未生成回答。"

            return _make_response(
                code=200,
                message="执行恢复成功",
                data={"answer": answer, "events": events},
            )

    except Exception as e:
        logger.error(
            f"Resume 接口异常: {e}\n{traceback.format_exc()}"
        )
        return _make_response(500, f"恢复执行异常: {str(e)}")


# ================================================================
# API 路由: 文献结构化整理
# ================================================================

@app.route("/api/summarize", methods=["POST"])
def summarize_papers():
    """
    文献结构化整理接口 — 生成标准化学术总结报告。

    请求格式: application/json
    参数:
        {
            "topic": str  # 文献主题或论文名称（必填）
        }

    处理流程:
        1. 在向量库中检索与主题相关的论文片段
        2. 按论文标题聚合去重
        3. 使用 LLM 结合六段式模板生成结构化总结
        4. 返回 Markdown 格式的总结报告

    Returns:
        {
            "code": 200,
            "message": "总结生成成功",
            "data": {
                "topic": str,
                "summary": str,         # Markdown 格式的六段式总结
                "paper_count": int,     # 涉及的论文数量
                "sources": [...]        # 引用的论文来源
            }
        }

    模板说明:
        LLM 将严格遵循六段式结构（背景→方法→实验→贡献→局限→展望），
        借鉴模板的逻辑层次而非机械替换文字。
        信息不足的部分会标注【信息不足】而非编造。
    """
    from service.summarize_service import get_summarize_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空，请提供 JSON 格式的数据")

        topic = body.get("topic", "").strip()
        if not topic:
            return _make_response(400, "topic 参数不能为空，请指定文献主题或论文名称")

        logger.info(f"收到总结请求: topic='{topic}'")

        summarize_service = get_summarize_service()
        result = summarize_service.summarize(topic)

        if result["paper_count"] == 0:
            return _make_response(
                code=404,
                message="未找到相关论文",
                data=result,
            )

        return _make_response(
            code=200,
            message=f"总结生成成功（涉及 {result['paper_count']} 篇论文）",
            data=result,
        )

    except Exception as e:
        logger.error(f"Summarize 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"总结生成异常: {str(e)}")


# ================================================================
# API 路由: 跨论文矛盾检测
# ================================================================

@app.route("/api/detect-contradictions", methods=["POST"])
def detect_contradictions():
    """
    跨论文矛盾检测接口 — 分析多篇论文对同一主题的矛盾与一致观点。

    请求格式: application/json
    参数:
        {
            "topic": str  # 待分析的研究主题或问题（必填）
        }

    处理流程:
        1. 在向量库中广泛检索与该主题相关的论文片段
        2. 按论文标题聚合
        3. 至少需要 2 篇论文才能进行矛盾检测
        4. 构建对比上下文并调用 LLM 进行分析
        5. 返回结构化的矛盾检测结果

    Returns:
        {
            "code": 200,
            "message": "矛盾检测完成 — 分析了 N 篇论文，发现 X 处矛盾，Y 处一致",
            "data": {
                "topic": str,
                "papers_analyzed": int,
                "contradictions": [
                    {
                        "claim": str,
                        "paper_a": {"title": str, "statement": str, "section": str},
                        "paper_b": {"title": str, "statement": str, "section": str},
                        "analysis": str,
                        "confidence": "high|medium|low"
                    }
                ],
                "agreements": [
                    {
                        "claim": str,
                        "papers": [str],
                        "details": str
                    }
                ],
                "experiment_comparison_table": str (Markdown),
                "summary": str,
                "sources": [...]
            }
        }
    """
    from service.contradiction_service import get_contradiction_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空，请提供 JSON 格式的数据")

        topic = body.get("topic", "").strip()
        if not topic:
            return _make_response(
                400, "topic 参数不能为空，请指定要分析的研究主题或问题",
            )

        logger.info(f"收到矛盾检测请求: topic='{topic}'")

        service = get_contradiction_service()
        result = service.detect_contradictions(topic)

        contradiction_count = len(result.get("contradictions", []))
        agreement_count = len(result.get("agreements", []))

        # 论文不足时仍返回 200（请求处理成功，但数据不足以检测）
        if result["papers_analyzed"] < 2:
            return _make_response(
                code=200,
                message=result.get("summary", "论文数量不足，无法进行矛盾检测"),
                data=result,
            )

        return _make_response(
            code=200,
            message=(
                f"矛盾检测完成 — 分析了 {result['papers_analyzed']} 篇论文，"
                f"发现 {contradiction_count} 处矛盾，"
                f"{agreement_count} 处一致"
            ),
            data=result,
        )

    except Exception as e:
        logger.error(
            f"Contradiction detection 接口异常: {e}\n{traceback.format_exc()}",
        )
        return _make_response(500, f"矛盾检测处理异常: {str(e)}")


# ================================================================
# API 路由: 知识库统计
# ================================================================

@app.route("/api/stats", methods=["GET"])
def get_stats():
    """
    获取知识库统计信息。

    Returns:
        向量库文档数量、本地存储中的文件列表等。
    """
    from service.vector_service import get_vector_service
    from service.paper_library import get_paper_library

    try:
        vector_service = get_vector_service()
        storage_service = get_storage_service()
        paper_lib = get_paper_library()

        papers_list = storage_service.list_objects(prefix="papers/")
        backups_list = storage_service.list_objects(prefix="backups/")

        return _make_response(
            code=200,
            message="success",
            data={
                "vector_store": vector_service.get_stats(),
                "storage_ready": storage_service.is_connected(),
                "papers_count": paper_lib.count(),  # 以 SQLite 数据库为准
                "backups_count": len(backups_list),
                "papers_dir": settings.PAPERS_DIR,
                "config": {
                    "model": settings.LLM_MODEL_NAME,
                    "embedding": settings.EMBEDDING_MODEL_NAME,
                    "chunk_size": settings.CHUNK_SIZE,
                    "chunk_overlap": settings.CHUNK_OVERLAP,
                },
            },
        )

    except Exception as e:
        logger.error(f"Stats 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"获取统计信息失败: {str(e)}")


# ================================================================
# API 路由: 论文列表
# ================================================================

@app.route("/api/papers", methods=["GET"])
def list_papers():
    """
    获取知识库中已入库的论文列表。

    Returns:
        {
            "code": 200,
            "message": "success",
            "data": {
                "papers": [{"name": str, "size": int, "last_modified": str}, ...],
                "count": int
            }
        }
    """
    try:
        storage_service = get_storage_service()

        if not storage_service or not storage_service.is_connected():
            return _make_response(
                503,
                "本地存储不可用，无法获取论文列表",
                data={"papers": [], "count": 0},
            )

        papers_list = storage_service.list_objects(prefix="papers/")

        return _make_response(
            code=200,
            message="success",
            data={
                "papers": papers_list,
                "count": len(papers_list),
            },
        )

    except Exception as e:
        logger.error(f"Papers 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"获取论文列表失败: {str(e)}")


# ================================================================
# API 路由: 论文库管理 (CRUD)
# ================================================================

@app.route("/api/library/papers", methods=["GET"])
def list_library_papers():
    """
    获取论文元数据库中所有论文的完整元数据（从 SQLite 读取）。

    Returns:
        {
            "code": 200,
            "data": {
                "papers": [{paper_id, title, authors, status, ...}],
                "count": int
            }
        }
    """
    from service.paper_library import get_paper_library

    try:
        paper_lib = get_paper_library()
        papers = paper_lib.list_papers(limit=10000, offset=0)
        return _make_response(
            code=200,
            message="success",
            data={"papers": papers, "count": len(papers)},
        )
    except Exception as e:
        logger.error(f"获取论文库列表失败: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"获取论文列表失败: {str(e)}")


@app.route("/api/library/papers/batch-delete", methods=["POST"])
def batch_delete_library_papers():
    """
    批量删除论文（SQLite + Chroma + 本地 PDF）。

    请求: { "paper_ids": [...], "delete_files": bool }
    """
    from service.paper_library import get_paper_library
    from service.vector_service import get_vector_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空，请提供 JSON 数据")

        paper_ids = body.get("paper_ids", [])
        if not paper_ids:
            return _make_response(400, "paper_ids 参数不能为空")

        delete_files = body.get("delete_files", True)

        paper_lib = get_paper_library()
        vector_service = get_vector_service()
        storage_service = get_storage_service()

        deleted_count = 0
        errors = []

        for paper_id in paper_ids:
            try:
                paper = paper_lib.get_paper(paper_id)
                paper_lib.delete_paper(paper_id)

                if vector_service.is_initialized:
                    try:
                        vector_service.delete_by_title(paper_id)
                    except Exception as ve:
                        logger.warning(f"Chroma 删除失败 (继续): {ve}")

                if delete_files and paper and paper.get("storage_path"):
                    try:
                        storage_service.delete_pdf(paper["storage_path"])
                    except Exception as fe:
                        logger.warning(f"PDF 删除失败 (继续): {fe}")

                deleted_count += 1
            except Exception as pe:
                logger.error(f"删除论文失败: paper_id='{paper_id}', {pe}")
                errors.append({"paper_id": paper_id, "error": str(pe)})

        msg = f"成功删除 {deleted_count} 篇论文"
        if errors:
            msg += f"，{len(errors)} 篇失败"

        return _make_response(
            code=200,
            message=msg,
            data={"deleted": deleted_count, "errors": errors},
        )

    except Exception as e:
        logger.error(f"批量删除异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"批量删除失败: {str(e)}")


@app.route("/api/library/papers/<path:paper_id>", methods=["DELETE"])
def delete_library_paper(paper_id):
    """
    删除单篇论文（SQLite + Chroma + 本地 PDF）。
    """
    from urllib.parse import unquote
    from service.paper_library import get_paper_library
    from service.vector_service import get_vector_service

    try:
        decoded_id = unquote(paper_id)

        paper_lib = get_paper_library()
        vector_service = get_vector_service()
        storage_service = get_storage_service()

        paper = paper_lib.get_paper(decoded_id)
        if paper is None:
            return _make_response(
                404,
                f"论文 '{decoded_id}' 不存在",
                data={"paper_id": decoded_id},
            )

        paper_lib.delete_paper(decoded_id)

        if vector_service.is_initialized:
            try:
                vector_service.delete_by_title(decoded_id)
            except Exception as ve:
                logger.warning(f"Chroma 删除失败 (继续): {ve}")

        storage_path = paper.get("storage_path")
        if storage_path:
            try:
                storage_service.delete_pdf(storage_path)
            except Exception as fe:
                logger.warning(f"PDF 删除失败 (继续): {fe}")

        return _make_response(
            code=200,
            message=f"论文 '{decoded_id}' 已删除",
            data={"paper_id": decoded_id},
        )

    except Exception as e:
        logger.error(f"删除论文异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"删除失败: {str(e)}")


# ================================================================
# API 路由: 本地目录扫描入库
# ================================================================

@app.route("/api/scan", methods=["POST"])
def scan_papers():
    """
    扫描本地 papers 目录及其子目录中的 PDF 文件并自动入库。

    递归扫描所有子文件夹。支持 SSE 流式推送进度。

    Query params:
        force=true  — 强制重新处理所有 PDF（忽略历史记录）
        stream=true — SSE 流式推送处理进度（用于进度条展示）
    """
    import hashlib
    from service.pdf_service import PDFService
    from service.vector_service import get_vector_service

    storage_service = get_storage_service()
    vector_service = get_vector_service()

    if not storage_service.is_connected():
        return _make_response(503, "本地存储不可用")

    papers_dir = Path(settings.PAPERS_DIR)
    use_stream = request.args.get("stream", "").lower() == "true"
    force_rescan = request.args.get("force", "").lower() == "true"

    if not papers_dir.exists():
        if use_stream:
            def _empty():
                yield f"data: {json.dumps({'type': 'complete', 'scanned': 0, 'processed': 0, 'errors': 0, 'message': 'papers 目录不存在'}, ensure_ascii=False)}\n\n"
            return Response(stream_with_context(_empty()), mimetype="text/event-stream")
        return _make_response(200, "papers 目录不存在，无需扫描", data={"scanned": 0, "processed": 0, "errors": 0})

    # 读取已处理文件的哈希记录
    tracking_file = papers_dir / ".processed_hashes.txt"
    processed_hashes = set()
    if tracking_file.exists() and not force_rescan:
        processed_hashes = set(tracking_file.read_text().splitlines())
    elif force_rescan:
        logger.info("Force rescan: 清空已处理记录，将重新处理所有 PDF")

    pdf_service = PDFService()

    # 确保向量库可用（提前初始化，避免每个 PDF 都重复失败）
    if not vector_service.is_initialized:
        ok = vector_service.load_or_create()
        if not ok:
            msg = "向量库初始化失败（Embedding 模型下载问题），无法入库。请检查网络或设置 HF_ENDPOINT 环境变量。"
            if use_stream:
                def _fail():
                    yield f"data: {json.dumps({'type': 'error', 'message': msg}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'complete', 'scanned': 0, 'processed': 0, 'skipped': 0, 'errors': 0, 'total': 0, 'message': msg}, ensure_ascii=False)}\n\n"
                return Response(stream_with_context(_fail()), mimetype="text/event-stream")
            return _make_response(500, msg)

    # --- Helper: process a single PDF ---
    def process_one_pdf(fpath: Path) -> dict:
        """Process one PDF file. Returns result dict."""
        from service.paper_library import get_paper_library

        file_data = fpath.read_bytes()
        content_hash = hashlib.md5(file_data).hexdigest()
        rel_path = str(fpath.relative_to(papers_dir))

        # 提取文本
        full_text, pdf_metadata = pdf_service.extract_text(file_data, fpath.name)
        if not full_text or len(full_text.strip()) < 50:
            return {"ok": False, "error": "文本过短（可能是扫描版）", "hash": content_hash, "path": rel_path}

        # 提取元数据 —— 传入 PDF 级别元数据辅助提取
        paper_metadata = pdf_service.extract_paper_metadata(full_text, fpath.name, pdf_metadata)
        paper_metadata.update({k: v for k, v in pdf_metadata.items() if k not in ("pdf_metadata", "first_page_fonts")})

        # 语义切片
        documents = pdf_service.semantic_chunk(full_text, paper_metadata)
        if not documents:
            return {"ok": False, "error": "切片为空", "hash": content_hash, "path": rel_path}

        # 向量化
        if not vector_service.is_initialized:
            vector_service.load_or_create()
        vector_service.add_documents(documents)

        # 写入 SQLite 元数据库（用于论文列表、统计计数等）
        try:
            paper_lib = get_paper_library()
            paper_lib.add_paper({
                "paper_id": paper_metadata.get("title", fpath.stem),
                "title": paper_metadata.get("title", fpath.stem),
                "authors": paper_metadata.get("authors", ""),
                "abstract": full_text[:500] if full_text else "",
                "arxiv_id": paper_metadata.get("arxiv_id", ""),
                "url": paper_metadata.get("url", ""),
                "published_date": paper_metadata.get("published_date", ""),
                "status": "stored",
                "storage_path": f"papers/{rel_path}",
            })
        except Exception as e:
            logger.warning(f"写入元数据库失败（不影响向量库）: {e}")

        return {
            "ok": True,
            "hash": content_hash,
            "path": rel_path,
            "chunks": len(documents),
            "pages": pdf_metadata.get("page_count", 0),
        }

    # --- SSE streaming mode ---
    if use_stream:
        def sse_event(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        def generate():
            # Step 1: Collect all PDFs
            all_files = sorted(
                f for f in papers_dir.rglob("*.pdf")
                if f.is_file() and not f.name.startswith(".")
            )
            total = len(all_files)

            yield sse_event({"type": "start", "total": total, "message": f"发现 {total} 个 PDF 文件，开始扫描..."})

            scanned = processed = errors = skipped = 0

            for fpath in all_files:
                rel_path = str(fpath.relative_to(papers_dir))
                file_data = fpath.read_bytes()
                content_hash = hashlib.md5(file_data).hexdigest()

                # Already processed
                if content_hash in processed_hashes:
                    skipped += 1
                    yield sse_event({
                        "type": "skip", "file": rel_path,
                        "message": "已在库中，跳过",
                        "scanned": scanned, "processed": processed,
                        "skipped": skipped, "errors": errors, "total": total,
                    })
                    continue

                scanned += 1
                yield sse_event({
                    "type": "process", "file": rel_path,
                    "message": f"正在处理 ({scanned}/{total - skipped})...",
                    "scanned": scanned, "processed": processed,
                    "skipped": skipped, "errors": errors, "total": total,
                })

                try:
                    result = process_one_pdf(fpath)
                    if result["ok"]:
                        processed += 1
                        processed_hashes.add(result["hash"])
                        tracking_file.write_text("\n".join(sorted(processed_hashes)))
                        chunks = result["chunks"]
                        pages = result["pages"]
                        yield sse_event({
                            "type": "done", "file": rel_path,
                            "message": f"入库成功 ({chunks} 个片段, {pages} 页)",
                            "scanned": scanned, "processed": processed,
                            "skipped": skipped, "errors": errors, "total": total,
                        })
                    else:
                        errors += 1
                        err_msg = result["error"]
                        yield sse_event({
                            "type": "error", "file": rel_path,
                            "message": f"失败: {err_msg}",
                            "scanned": scanned, "processed": processed,
                            "skipped": skipped, "errors": errors, "total": total,
                        })
                except Exception as e:
                    errors += 1
                    yield sse_event({
                        "type": "error", "file": rel_path,
                        "message": f"异常: {str(e)[:100]}",
                        "scanned": scanned, "processed": processed,
                        "skipped": skipped, "errors": errors, "total": total,
                    })

            # Backup after scan
            if processed > 0:
                storage_service.upload_vector_backup(local_dir=settings.VECTOR_DB_PATH)

            yield sse_event({
                "type": "complete",
                "scanned": scanned, "processed": processed,
                "skipped": skipped, "errors": errors, "total": total,
                "message": f"扫描完成：入库 {processed} 篇，跳过 {skipped} 篇，失败 {errors} 篇",
            })

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Non-streaming mode (original behavior) ---
    try:
        results = {"scanned": 0, "processed": 0, "errors": 0, "skipped": 0}

        for fpath in sorted(papers_dir.rglob("*.pdf")):
            if not fpath.is_file() or fpath.name.startswith("."):
                continue

            file_data = fpath.read_bytes()
            content_hash = hashlib.md5(file_data).hexdigest()
            rel_path = str(fpath.relative_to(papers_dir))

            if content_hash in processed_hashes:
                results["skipped"] += 1
                continue

            results["scanned"] += 1
            logger.info(f"扫描发现新 PDF: {rel_path}")

            result = process_one_pdf(fpath)
            if result["ok"]:
                processed_hashes.add(result["hash"])
                results["processed"] += 1
                tracking_file.write_text("\n".join(sorted(processed_hashes)))
                logger.info(f"入库成功 ({results['processed']}): {rel_path} ({result['chunks']} chunks)")
            else:
                results["errors"] += 1
                logger.warning(f"入库失败: {rel_path}: {result['error']}")

        if results["processed"] > 0:
            storage_service.upload_vector_backup(local_dir=settings.VECTOR_DB_PATH)

        logger.info(
            f"扫描结束: 发现 {results['scanned']} 篇新论文, "
            f"成功 {results['processed']} 篇, 跳过 {results['skipped']} 篇, 失败 {results['errors']} 篇"
        )

        return _make_response(
            code=200,
            message=f"扫描完成: 成功 {results['processed']} 篇, 跳过 {results['skipped']} 篇"
                    f"{'，失败 ' + str(results['errors']) + ' 篇' if results['errors'] > 0 else ''}"
                    f"{'，无新论文' if results['scanned'] == 0 else ''}",
            data=results,
        )

    except Exception as e:
        logger.error(f"Scan 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"扫描入库失败: {str(e)}")

    except Exception as e:
        logger.error(f"Scan 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"扫描入库失败: {str(e)}")


# ================================================================
# API 路由: 论文发现 (arXiv 搜索)
# ================================================================

@app.route("/api/discover", methods=["POST"])
def discover_papers():
    """
    智能论文发现接口 — 在 arXiv 中搜索与主题相关的论文。

    请求格式: application/json
    参数:
        {
            "topic": str,        # 研究主题（自然语言，必填）
            "max_results": int,  # 最大结果数（可选，默认 10）
            "days_back": int     # 搜索回溯天数（可选，默认 90）
        }

    Returns:
        {
            "code": 200,
            "message": "发现 N 篇论文",
            "data": {
                "topic": str,
                "query_used": str,
                "total_found": int,
                "papers": [...]
            }
        }
    """
    from service.paper_discovery_service import get_discovery_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空")

        topic = body.get("topic", "").strip()
        if not topic:
            return _make_response(400, "topic 参数不能为空")

        max_results = body.get("max_results")
        days_back = body.get("days_back")

        logger.info(f"收到论文发现请求: topic='{topic}'")

        service = get_discovery_service()
        result = service.discover(
            topic=topic,
            max_results=max_results,
            days_back=days_back,
        )

        paper_count = len(result.get("papers", []))
        return _make_response(
            code=200,
            message=f"发现 {paper_count} 篇相关论文",
            data=result,
        )

    except Exception as e:
        logger.error(f"Discover 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"论文发现失败: {str(e)}")


# ================================================================
# API 路由: 论文筛选
# ================================================================

@app.route("/api/screen", methods=["POST"])
def screen_papers():
    """
    论文筛选接口 — 使用 LLM 对论文进行质量评估和自动打标签。

    请求格式: application/json
    参数:
        {
            "papers": [...],       # 论文列表（必填）
            "topic": str,          # 研究主题（必填）
            "threshold": float     # 质量阈值（可选，默认 5.0）
        }

    Returns:
        {
            "code": 200,
            "data": {
                "screened": [...],
                "filtered_out": [...],
                "pass_rate": float
            }
        }
    """
    from service.paper_screening_service import get_screening_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空")

        papers = body.get("papers", [])
        if not papers:
            return _make_response(400, "papers 参数不能为空")

        topic = body.get("topic", "").strip()
        if not topic:
            return _make_response(400, "topic 参数不能为空")

        threshold = body.get("threshold")

        logger.info(
            f"收到论文筛选请求: {len(papers)} papers, topic='{topic}'"
        )

        service = get_screening_service()
        result = service.screen(
            papers=papers,
            topic=topic,
            quality_threshold=threshold,
        )

        return _make_response(
            code=200,
            message=(
                f"筛选完成: {len(result['screened'])} 篇通过, "
                f"{len(result['filtered_out'])} 篇被过滤 "
                f"(通过率 {result['pass_rate']:.0%})"
            ),
            data=result,
        )

    except Exception as e:
        logger.error(f"Screen 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"论文筛选失败: {str(e)}")


# ================================================================
# API 路由: 深度论文分析
# ================================================================

@app.route("/api/analyze", methods=["POST"])
def analyze_paper():
    """
    深度论文分析接口 — 对论文全文进行结构化信息提取。

    请求格式: application/json
    参数:
        {
            "text": str,           # 论文全文文本（必填）
            "paper_id": str        # 论文标识符（可选）
        }

    Returns:
        {
            "code": 200,
            "data": {
                "paper_id": str,
                "title": str,
                "background": str,
                "methods": str,
                "experiments": str,
                "contributions": [str],
                "limitations": str,
                "keywords": [str],
                "source_sections": [str]
            }
        }
    """
    from service.deep_analysis_service import get_analysis_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空")

        text = body.get("text", "").strip()
        if not text or len(text) < 100:
            return _make_response(400, "text 参数不能为空且需至少 100 字符")

        paper_id = body.get("paper_id")

        logger.info(
            f"收到深度分析请求: paper_id={paper_id}, text_length={len(text)}"
        )

        service = get_analysis_service()
        result = service.analyze(text=text, paper_id=paper_id)

        return _make_response(
            code=200,
            message=f"深度分析完成: {result.get('title', 'Unknown')}",
            data=result,
        )

    except Exception as e:
        logger.error(f"Analyze 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"深度分析失败: {str(e)}")


# ================================================================
# API 路由: 论文对比分析
# ================================================================

@app.route("/api/compare", methods=["POST"])
def compare_papers():
    """
    论文对比接口 — 对多篇论文的结构化分析结果进行对比。

    请求格式: application/json
    参数:
        {
            "paper_ids": [...],    # 论文 ID 列表（必填，至少 2 个）
            "aspect": str          # 对比维度: methods/experiments/contributions/limitations/overall
        }

    Returns:
        {
            "code": 200,
            "data": {
                "aspect": str,
                "paper_count": int,
                "comparison_table": str (Markdown),
                "analysis": str (Markdown),
                "papers": [...]
            }
        }
    """
    from service.summarize_service import get_summarize_service

    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return _make_response(400, "请求体不能为空")

        paper_ids = body.get("paper_ids", [])
        if not paper_ids or len(paper_ids) < 2:
            return _make_response(400, "paper_ids 至少需要 2 个论文 ID")

        aspect = body.get("aspect", "overall").strip()

        logger.info(
            f"收到对比请求: {len(paper_ids)} papers, aspect='{aspect}'"
        )

        service = get_summarize_service()
        result = service.compare(paper_ids=paper_ids, aspect=aspect)

        return _make_response(
            code=200,
            message=f"对比分析完成: {result['paper_count']} 篇论文",
            data=result,
        )

    except Exception as e:
        logger.error(f"Compare 接口异常: {e}\n{traceback.format_exc()}")
        return _make_response(500, f"论文对比失败: {str(e)}")


# ================================================================
# 全局错误处理
# ================================================================

@app.errorhandler(413)
def request_entity_too_large(error):
    """处理文件过大错误"""
    return _make_response(
        413,
        f"上传文件过大，最大允许 {settings.MAX_UPLOAD_SIZE_MB} MB",
    )


@app.errorhandler(404)
def not_found(error):
    """处理 404 错误"""
    return _make_response(404, "请求的接口不存在")


@app.errorhandler(405)
def method_not_allowed(error):
    """处理不支持的 HTTP 方法"""
    return _make_response(405, "不支持的 HTTP 方法")


@app.errorhandler(500)
def internal_error(error):
    """处理内部服务器错误"""
    logger.error(f"内部服务器错误: {error}")
    return _make_response(500, "服务器内部错误，请稍后重试")


# ================================================================
# 应用启动入口
# ================================================================

def init_app():
    """
    应用初始化函数。

    按顺序执行:
        1. 本地存储目录初始化
        2. 向量库加载/恢复
        3. Agent 服务预热
        4. 打印启动横幅
    """
    # 步骤 1: 本地存储初始化
    storage_ok = _init_storage()

    # 步骤 2: 向量库初始化
    vector_init_result = _init_vector_store()

    # 步骤 3: Agent 预热
    _init_agent_services()

    # 打印启动信息
    _print_startup_banner()

    return {
        "storage_ready": storage_ok,
        "vector_init": vector_init_result,
    }


# 在模块加载时执行初始化（仅在直接运行 app.py 时）
# 当使用 gunicorn 等 WSGI 服务器时，需要在工厂函数中手动调用 init_app()
_init_result = None

if __name__ == "__main__":
    _init_result = init_app()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )
else:
    # 作为 WSGI 模块被加载时，也在导入时初始化
    # （gunicorn 等场景）
    try:
        _init_result = init_app()
    except Exception as e:
        logger.error(f"应用初始化失败: {e}", exc_info=True)
        logger.warning("应用将以降级模式运行，部分功能可能不可用")
