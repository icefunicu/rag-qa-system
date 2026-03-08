from __future__ import annotations

import os
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from shared.auth import CurrentUser, authenticate_local_user, create_access_token
from shared.logging import setup_logging

from .ai_client import create_ai_completion, load_ai_chat_settings


logger = setup_logging("gateway")

NOVEL_SERVICE_URL = os.getenv("NOVEL_SERVICE_URL", "http://novel-service:8100").rstrip("/")
KB_SERVICE_URL = os.getenv("KB_SERVICE_URL", "http://kb-service:8200").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "180"))
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class LoginRequest(BaseModel):
    email: str
    password: str


class AIChatMessage(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=12000)


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage] = Field(min_length=1, max_length=32)
    system_prompt: str = Field(default="", max_length=2000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=128, le=8192)


app = FastAPI(title="RAG-QA 2.0 Gateway", version="2.1.0")


def _sanitize_headers(headers: Request) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


async def _iter_upstream_bytes(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk


async def _close_upstream(response: httpx.Response, client: httpx.AsyncClient) -> None:
    await response.aclose()
    await client.aclose()


async def _proxy_request(
    request: Request,
    *,
    service_base_url: str,
    service_path: str,
) -> Response:
    target_url = f"{service_base_url}{service_path}"
    logger.info("proxy request method=%s target=%s", request.method, target_url)
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        upstream = await client.send(
            client.build_request(
                method=request.method,
                url=target_url,
                headers=_sanitize_headers(request),
                params=request.query_params,
                content=request.stream(),
            ),
            stream=True,
        )
        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        media_type = upstream.headers.get("content-type")
        if media_type and media_type.startswith("text/event-stream"):
            return StreamingResponse(
                _iter_upstream_bytes(upstream),
                status_code=upstream.status_code,
                headers=response_headers,
                background=BackgroundTask(_close_upstream, upstream, client),
                media_type=media_type,
            )

        try:
            body = await upstream.aread()
        finally:
            await _close_upstream(upstream, client)
        return Response(
            content=body,
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=media_type,
        )
    except Exception:
        await client.aclose()
        raise


def _normalize_ai_messages(payload: AIChatRequest) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    total_chars = 0
    for item in payload.messages:
        role = item.role.strip().lower()
        if role not in {"system", "user", "assistant"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported message role: {item.role}",
            )
        content = item.content.strip()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="message content cannot be empty",
            )
        total_chars += len(content)
        normalized.append({"role": role, "content": content})

    if total_chars > 50000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message payload is too large",
        )

    system_prompt = payload.system_prompt.strip()
    if system_prompt and not any(message["role"] == "system" for message in normalized):
        normalized.insert(0, {"role": "system", "content": system_prompt})
    return normalized


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
async def login(payload: LoginRequest) -> JSONResponse:
    user = authenticate_local_user(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = create_access_token(user)
    return JSONResponse(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.user_id,
                "email": user.email,
                "role": user.role,
            },
        }
    )


@app.get("/api/v1/auth/me")
async def me(user: CurrentUser) -> dict[str, str]:
    return {
        "id": user.user_id,
        "email": user.email,
        "role": user.role,
    }


@app.get("/api/v1/ai/config")
async def get_ai_config(user: CurrentUser) -> dict[str, Any]:
    settings = load_ai_chat_settings()
    return {
        "enabled": settings.enabled,
        "configured": settings.configured,
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "timeout_seconds": settings.timeout_seconds,
        "default_temperature": settings.default_temperature,
        "default_max_tokens": settings.default_max_tokens,
        "has_system_prompt": bool(settings.system_prompt),
    }


@app.post("/api/v1/ai/chat")
async def ai_chat(payload: AIChatRequest, user: CurrentUser) -> dict[str, Any]:
    settings = load_ai_chat_settings()
    normalized_messages = _normalize_ai_messages(payload)
    if settings.system_prompt and not any(message["role"] == "system" for message in normalized_messages):
        normalized_messages.insert(0, {"role": "system", "content": settings.system_prompt})

    logger.info(
        "ai chat request user_id=%s messages=%s provider=%s model=%s",
        user.user_id,
        len(normalized_messages),
        settings.provider,
        settings.model or "unconfigured",
    )
    completion = await create_ai_completion(
        settings=settings,
        messages=normalized_messages,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return {
        "answer": completion["answer"],
        "reasoning": completion["reasoning"],
        "provider": completion["provider"],
        "model": completion["model"],
        "finish_reason": completion["finish_reason"],
        "usage": completion["usage"],
    }


@app.api_route(
    "/api/v1/novel/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_novel(path: str, request: Request) -> Response:
    return await _proxy_request(
        request,
        service_base_url=NOVEL_SERVICE_URL,
        service_path=f"/api/v1/novel/{path}",
    )


@app.api_route(
    "/api/v1/kb/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_kb(path: str, request: Request) -> Response:
    return await _proxy_request(
        request,
        service_base_url=KB_SERVICE_URL,
        service_path=f"/api/v1/kb/{path}",
    )
