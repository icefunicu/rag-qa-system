from __future__ import annotations

import httpx
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from shared.api_errors import (
    http_exception_response,
    unexpected_exception_response,
    validation_exception_response,
)
from shared.auth import ensure_auth_configuration_ready
from shared.tracing import TRACE_ID_HEADER, ensure_trace_id, reset_trace_id, set_trace_id

from .ai_client import load_llm_settings
from .gateway_admin_routes import router as gateway_admin_router
from .gateway_analytics_routes import router as gateway_analytics_router
from .gateway_audit_support import merge_audit_event_lists as _merge_audit_event_lists
from .gateway_auth_routes import router as gateway_auth_router
from .gateway_chat_graph_routes import router as gateway_chat_graph_router
from .gateway_chat_routes import router as gateway_chat_router
from .gateway_config import load_gateway_runtime_settings
from .gateway_graph import ensure_gateway_graph_schema
from .gateway_idempotency import IdempotencyState
from .gateway_pricing import estimate_usage_cost
from .gateway_runtime import gateway_db, logger, runtime_settings
from .gateway_schemas import ChatScopePayload
from .gateway_scope import fetch_corpora, fetch_corpus_documents, resolve_scope_snapshot
from .gateway_platform_routes import router as gateway_platform_router
from .gateway_system_routes import router as gateway_system_router
from .gateway_transport import request_service_json


runtime_settings = load_gateway_runtime_settings()
KB_SERVICE_URL = runtime_settings.kb_service_url
REQUEST_TIMEOUT_SECONDS = runtime_settings.request_timeout_seconds


@asynccontextmanager
async def lifespan(_: FastAPI):
    warnings = ensure_auth_configuration_ready()
    for warning in warnings:
        logger.warning("gateway auth configuration warning: %s", warning)
    ensure_gateway_graph_schema()
    yield


app = FastAPI(title="Enterprise RAG QA Gateway", version="3.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    return http_exception_response(exc)


@app.exception_handler(RequestValidationError)
async def handle_validation_exception(request: Request, exc: RequestValidationError):
    return validation_exception_response(exc)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    logger.exception("gateway unexpected error path=%s", request.url.path)
    return unexpected_exception_response()


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = ensure_trace_id(request.headers.get(TRACE_ID_HEADER), prefix="gateway-")
    token = set_trace_id(trace_id)
    try:
        response = await call_next(request)
    finally:
        reset_trace_id(token)
    response.headers[TRACE_ID_HEADER] = trace_id
    return response


async def _fetch_corpus_documents(client: httpx.AsyncClient, *, user, corpus_id: str):
    return await fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=KB_SERVICE_URL)


async def _fetch_corpora(user, *, include_counts: bool):
    return await fetch_corpora(user, include_counts=include_counts, kb_service_url=KB_SERVICE_URL)


async def _resolve_scope_snapshot(user, scope_payload: ChatScopePayload | None):
    return await resolve_scope_snapshot(
        user,
        scope_payload,
        fetch_corpora_fn=_fetch_corpora,
        fetch_corpus_documents_fn=_fetch_corpus_documents,
    )


async def _request_service_json(client: httpx.AsyncClient, method: str, url: str, *, headers: dict[str, str], json_body: dict[str, Any] | None = None):
    return await request_service_json(client, method, url, headers=headers, json_body=json_body)


async def _retrieve_scope_evidence(*, user, scope_snapshot: dict[str, Any], question: str, history: list[dict[str, Any]]):
    from .gateway_retrieval import retrieve_scope_evidence

    return await retrieve_scope_evidence(
        user=user,
        scope_snapshot=scope_snapshot,
        question=question,
        history=history,
        fetch_corpus_documents_fn=_fetch_corpus_documents,
        kb_service_url=KB_SERVICE_URL,
        request_service_json_fn=_request_service_json,
    )


def _estimate_usage_cost(usage: dict[str, Any]) -> dict[str, Any]:
    return estimate_usage_cost(
        usage,
        llm_price_tiers=runtime_settings.llm_price_tiers,
        llm_input_price_per_1k_tokens=runtime_settings.llm_input_price_per_1k_tokens,
        llm_output_price_per_1k_tokens=runtime_settings.llm_output_price_per_1k_tokens,
        llm_price_currency=runtime_settings.llm_price_currency,
    )


async def _gateway_readiness_checks() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with gateway_db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "failed", "detail": str(exc)}
    timeout = httpx.Timeout(min(REQUEST_TIMEOUT_SECONDS, 5.0))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{KB_SERVICE_URL}/readyz")
        checks["kb_service"] = {"status": "ok"} if response.status_code < 400 else {"status": "failed", "detail": f"kb-service readiness returned {response.status_code}"}
    except httpx.HTTPError as exc:
        checks["kb_service"] = {"status": "failed", "detail": str(exc)}
    settings = load_llm_settings()
    checks["llm"] = {"status": "fallback" if not settings.configured else "ok", "configured": settings.configured}
    return checks


app.include_router(gateway_auth_router)
app.include_router(gateway_system_router)
app.include_router(gateway_chat_router)
app.include_router(gateway_chat_graph_router)
app.include_router(gateway_admin_router)
app.include_router(gateway_platform_router)
app.include_router(gateway_analytics_router)


__all__ = [
    "ChatScopePayload",
    "HTTPException",
    "IdempotencyState",
    "_estimate_usage_cost",
    "_fetch_corpora",
    "_fetch_corpus_documents",
    "_gateway_readiness_checks",
    "_merge_audit_event_lists",
    "_request_service_json",
    "_resolve_scope_snapshot",
    "_retrieve_scope_evidence",
    "app",
    "gateway_db",
    "httpx",
]
