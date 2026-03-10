from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .tracing import current_trace_id


_STATUS_CODE_MAP = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    502: "upstream_unavailable",
    503: "service_unavailable",
}


def raise_api_error(status_code: int, code: str, detail: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "detail": detail,
            "code": code,
        },
    )


def json_error_response(
    *,
    status_code: int,
    detail: str,
    code: str,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "detail": detail,
        "code": code,
        "trace_id": current_trace_id(),
    }
    if errors:
        payload["errors"] = errors
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def http_exception_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    headers = dict(exc.headers or {})
    if isinstance(detail, dict):
        message = str(detail.get("detail") or detail.get("message") or "request failed")
        code = str(detail.get("code") or _STATUS_CODE_MAP.get(exc.status_code, "http_error"))
        errors = detail.get("errors")
        normalized_errors = list(errors) if isinstance(errors, list) else None
        return json_error_response(
            status_code=exc.status_code,
            detail=message,
            code=code,
            errors=normalized_errors,
            headers=headers or None,
        )

    return json_error_response(
        status_code=exc.status_code,
        detail=str(detail or "request failed"),
        code=_STATUS_CODE_MAP.get(exc.status_code, "http_error"),
        headers=headers or None,
    )


def validation_exception_response(exc: RequestValidationError) -> JSONResponse:
    errors = []
    for item in exc.errors():
        errors.append(
            {
                "loc": [str(part) for part in item.get("loc", ())],
                "msg": str(item.get("msg") or ""),
                "type": str(item.get("type") or ""),
            }
        )
    return json_error_response(
        status_code=422,
        detail="request validation failed",
        code="validation_error",
        errors=errors,
    )


def unexpected_exception_response() -> JSONResponse:
    return json_error_response(
        status_code=500,
        detail="internal server error",
        code="internal_error",
    )
