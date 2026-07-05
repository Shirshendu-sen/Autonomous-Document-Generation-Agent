"""
app/main.py
-----------
FastAPI entry point. Wires together the autonomous pipeline:

    Request -> Planner -> Executor -> Reflection (review only) ->
    targeted revise of flagged sections -> DOCX -> Response

Error handling at the API boundary: planning/execution failures that exhaust
retries return a clean 502 with a description instead of leaking a stack
trace; rendering failures return 500. Reflection failures never bubble up as
HTTP errors at all -- they're caught inside reflection.py and the loop just
skips a round, because a broken *reviewer* should never block shipping an
already-valid document.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import storage
from app.llm_client import get_llm_client, LLMError
from app.planner import create_plan
from app.executor import execute_plan
from app.reflection import run_reflection_loop
from app.doc_generator import build_docx
from app.schemas import AgentRequest, AgentResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agent.main")

app = FastAPI(
    title="Autonomous Document Agent",
    description="Plans, drafts, self-checks, and renders a business document from a natural-language request.",
    version="1.0.0",
)

# get_llm_client() performs a live provider health check (see app/llm_client.py),
# which is worth paying for once, not on every request. Resolving it fresh per
# request would mean an extra Groq API call on top of every single /agent call
# -- pure overhead that also adds to rate-limit pressure on a free tier for no
# benefit, since the provider practically never changes mid-process. Cached
# lazily on first use rather than at import time, so tests that monkeypatch
# LLM_PROVIDER before the first request still pick it up correctly.
_llm_client = None


def _resolve_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = get_llm_client()
        logger.info("LLM provider resolved for this server process: %s", _llm_client.name)
    return _llm_client


@app.get("/health", summary="Liveness check")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/agent",
    response_model=AgentResponse,
    summary="Plan, draft, self-check, and render a business document from a natural-language request",
)
async def run_agent(payload: AgentRequest) -> AgentResponse:
    request_id = str(uuid.uuid4())
    logger.info("[%s] new request: %.80s", request_id, payload.request)
    llm = _resolve_llm_client()

    try:
        plan = create_plan(payload.request, llm)
    except LLMError as e:
        logger.exception("[%s] planning failed", request_id)
        raise HTTPException(status_code=502, detail=f"Could not reach the language model to plan the document: {e}")

    try:
        sections = await execute_plan(plan, llm)
    except LLMError as e:
        logger.exception("[%s] execution failed", request_id)
        raise HTTPException(status_code=502, detail=f"Could not reach the language model to draft the document: {e}")

    sections, reflection_log = await run_reflection_loop(payload.request, plan, sections, llm)

    try:
        docx_path = build_docx(plan, sections, request_id)
    except Exception as e:
        logger.exception("[%s] document rendering failed", request_id)
        raise HTTPException(status_code=500, detail=f"Document rendering failed: {e}")

    storage.save(request_id, {"path": str(docx_path), "plan": plan.model_dump(), "reflection_log": reflection_log})

    response = AgentResponse(
        request_id=request_id, status="completed",
        message=f"Generated a {plan.document_type.replace('_', ' ')} titled '{plan.title}'.",
        document_type=plan.document_type, title=plan.title, assumptions=plan.assumptions,
        task_list=[f"{s.title} — {s.goal}" for s in plan.sections],
        reflection_log=reflection_log, sections_generated=len(sections),
        llm_provider_used=llm.name, download_url=f"/agent/download/{request_id}",
    )
    logger.info("[%s] completed via provider=%s, sections=%d, reflection_rounds=%d",
                request_id, llm.name, len(sections), len(reflection_log))
    return response


@app.get("/agent/download/{request_id}", summary="Download the generated .docx for a previous request")
def download_document(request_id: str) -> FileResponse:
    record = storage.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Unknown request_id, or the server has since restarted.")
    return FileResponse(
        record["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{request_id}.docx",
    )


@app.get("/agent/plan/{request_id}", summary="Inspect the plan and reflection log behind a previous request")
def get_plan_and_reflection(request_id: str) -> Dict[str, Any]:
    record = storage.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Unknown request_id, or the server has since restarted.")
    return {"plan": record["plan"], "reflection_log": record["reflection_log"]}
