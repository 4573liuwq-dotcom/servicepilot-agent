import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field

from insightforge.agents.graph import graph
from insightforge.config import get_settings
from insightforge.domain import ResearchResult
from insightforge.services.retriever import KnowledgeBase
from insightforge.support.graph import support_graph
from insightforge.support.models import SupportResult
from insightforge.support.store import CommerceStore

settings = get_settings()
knowledge_base = KnowledgeBase(settings.database_path)
commerce_store = CommerceStore(settings.database_path)
commerce_store.seed_demo_orders()
logger = logging.getLogger("insightforge")


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = None
    require_approval: bool | None = None


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str = Field(default="", max_length=2000)


class SupportRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class TextDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)
    source: str = Field(default="manual", max_length=500)


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    configured = settings.app_api_key
    if configured and x_api_key != configured.get_secret_value():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


Auth = Annotated[None, Depends(verify_api_key)]


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}


def _initial_state(request: ResearchRequest) -> dict[str, Any]:
    return {
        "query": request.query,
        "max_iterations": settings.max_reflection_loops,
        "quality_threshold": settings.quality_threshold,
        "require_approval": (
            settings.require_plan_approval
            if request.require_approval is None
            else request.require_approval
        ),
    }


def _has_interrupt(result: dict[str, Any]) -> bool:
    return bool(result.get("__interrupt__"))


def _response(thread_id: str, result: dict[str, Any]) -> ResearchResult:
    review = result.get("review")
    if _has_interrupt(result):
        task_status = "needs_approval"
    elif result.get("approval_status") == "rejected":
        task_status = "rejected"
    elif result.get("error"):
        task_status = "blocked"
    else:
        task_status = "completed"
    return ResearchResult(
        thread_id=thread_id,
        status=task_status,
        report=result.get("final_report", ""),
        quality_score=review.score if review else 0,
        evidence_count=len(result.get("evidence", [])),
        iterations=result.get("iteration", 0),
        plan=result.get("plan"),
    )


def _support_response(thread_id: str, result: dict[str, Any]) -> SupportResult:
    if _has_interrupt(result):
        task_status = "needs_approval"
    elif result.get("approval_status") == "rejected":
        task_status = "rejected"
    elif result.get("error"):
        task_status = "blocked"
    else:
        task_status = "completed"
    intent = result.get("intent")
    return SupportResult(
        thread_id=thread_id,
        status=task_status,
        reply=result.get("final_reply", ""),
        intent=intent.intent if intent else None,
        order=result.get("order"),
        decision=result.get("decision"),
        action_result=result.get("action_result"),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("starting app=%s demo_mode=%s", settings.app_name, settings.demo_mode)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Enterprise deep-research and knowledge copilot powered by LangGraph",
    lifespan=lifespan,
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": settings.app_version,
        "demo_mode": settings.demo_mode,
        "knowledge_chunks": knowledge_base.count(),
    }


@app.post(
    "/v1/support/chat",
    response_model=SupportResult,
    dependencies=[Depends(verify_api_key)],
)
def support_chat(request: SupportRequest) -> SupportResult:
    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        result = support_graph.invoke(
            {"thread_id": thread_id, "message": request.message}, config=_config(thread_id)
        )
        return _support_response(thread_id, result)
    except Exception as exc:
        logger.exception("support_failed thread=%s", thread_id)
        raise HTTPException(status_code=502, detail=f"Support Agent failed: {exc}") from exc


@app.post(
    "/v1/support/{thread_id}/resume",
    response_model=SupportResult,
    dependencies=[Depends(verify_api_key)],
)
def resume_support(thread_id: str, request: ApprovalRequest) -> SupportResult:
    try:
        result = support_graph.invoke(
            Command(resume={"approved": request.approved, "feedback": request.feedback}),
            config=_config(thread_id),
        )
        return _support_response(thread_id, result)
    except Exception as exc:
        logger.exception("support_resume_failed thread=%s", thread_id)
        raise HTTPException(
            status_code=409, detail=f"Unable to resume support task: {exc}"
        ) from exc


@app.get("/v1/support/orders/{order_id}", dependencies=[Depends(verify_api_key)])
def get_order(order_id: str) -> dict[str, Any]:
    order = commerce_store.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.model_dump(mode="json")


@app.get("/v1/support/actions", dependencies=[Depends(verify_api_key)])
def list_actions() -> list[dict]:
    return commerce_store.list_actions()


@app.post("/v1/research", response_model=ResearchResult, dependencies=[Depends(verify_api_key)])
def research(request: ResearchRequest) -> ResearchResult:
    thread_id = request.thread_id or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        result = graph.invoke(_initial_state(request), config=_config(thread_id))
        logger.info(
            "research_completed thread=%s duration=%.3f",
            thread_id,
            time.perf_counter() - started,
        )
        return _response(thread_id, result)
    except Exception as exc:
        logger.exception("research_failed thread=%s", thread_id)
        raise HTTPException(status_code=502, detail=f"Agent execution failed: {exc}") from exc


@app.post(
    "/v1/research/{thread_id}/resume",
    response_model=ResearchResult,
    dependencies=[Depends(verify_api_key)],
)
def resume_research(thread_id: str, request: ApprovalRequest) -> ResearchResult:
    try:
        result = graph.invoke(
            Command(resume={"approved": request.approved, "feedback": request.feedback}),
            config=_config(thread_id),
        )
        return _response(thread_id, result)
    except Exception as exc:
        logger.exception("resume_failed thread=%s", thread_id)
        raise HTTPException(status_code=409, detail=f"Unable to resume task: {exc}") from exc


@app.post("/v1/research/stream", dependencies=[Depends(verify_api_key)])
def stream_research(request: ResearchRequest) -> StreamingResponse:
    thread_id = request.thread_id or str(uuid.uuid4())

    async def events() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'start', 'thread_id': thread_id})}\n\n"
        try:
            for update in graph.stream(
                _initial_state(request), config=_config(thread_id), stream_mode="updates"
            ):
                node = next(iter(update), "unknown")
                payload = update.get(node, {})
                event = {"type": "node", "node": node}
                if isinstance(payload, dict) and payload.get("review"):
                    event["score"] = payload["review"].score
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            snapshot = graph.get_state(_config(thread_id)).values
            event = {
                "type": "complete",
                "thread_id": thread_id,
                "report": snapshot.get("final_report", ""),
                "needs_approval": bool(
                    snapshot.get("plan") and not snapshot.get("approval_status")
                ),
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/knowledge/text", dependencies=[Depends(verify_api_key)])
def ingest_text(document: TextDocumentRequest) -> dict[str, Any]:
    chunks = knowledge_base.ingest_text(document.content, document.source, document.title)
    return {"status": "indexed", "chunks": chunks, "total_chunks": knowledge_base.count()}


@app.post("/v1/knowledge/file", dependencies=[Depends(verify_api_key)])
async def ingest_file(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    suffix = Path(file.filename or "document.txt").suffix.lower()
    if suffix not in {".txt", ".md", ".markdown"}:
        raise HTTPException(status_code=415, detail="当前学习版支持 .txt/.md 文件")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="文件不能超过 2 MB")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="文件必须使用 UTF-8 编码") from exc
    chunks = knowledge_base.ingest_text(content, file.filename or "upload", file.filename)
    return {"status": "indexed", "chunks": chunks, "total_chunks": knowledge_base.count()}
