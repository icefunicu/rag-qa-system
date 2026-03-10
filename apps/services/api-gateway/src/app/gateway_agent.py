from __future__ import annotations

import json
import time
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from shared.auth import CurrentUser
from shared.grounded_answering import compact_text
from shared.langchain_chat import build_chat_model, extract_message_text

from .ai_client import load_llm_settings
from .gateway_answering import contextualize_question
from .gateway_runtime import logger, runtime_settings
from .gateway_transport import downstream_headers, parse_corpus_id, request_service_json


AGENT_MAX_TOOL_CALLS = 3
AGENT_MAX_EVIDENCE = 8
AGENT_MAX_DOCUMENTS = 20


async def run_agent_search(
    *,
    user: CurrentUser,
    scope_snapshot: dict[str, Any],
    question: str,
    history: list[dict[str, Any]],
    retrieve_scope_evidence_fn: Any,
    fetch_corpus_documents_fn: Any,
    kb_service_url: str,
    request_service_json_fn: Any = request_service_json,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    contextualized_question = contextualize_question(question, history)
    settings = load_llm_settings()
    if not settings.configured:
        return await retrieve_scope_evidence_fn(
            user=user,
            scope_snapshot=scope_snapshot,
            question=question,
            history=history,
        )

    tool_events: list[dict[str, Any]] = []
    evidence_by_unit: dict[str, dict[str, Any]] = {}
    services: list[dict[str, Any]] = []
    total_retrieval_ms = 0.0

    async def search_scope_tool(search_question: str, limit: int = AGENT_MAX_EVIDENCE) -> dict[str, Any]:
        nonlocal total_retrieval_ms
        tool_started = time.perf_counter()
        items, _, retrieval_meta = await retrieve_scope_evidence_fn(
            user=user,
            scope_snapshot=scope_snapshot,
            question=search_question,
            history=history,
        )
        total_retrieval_ms += round((time.perf_counter() - tool_started) * 1000.0, 3)
        _collect_evidence(evidence_by_unit, items, limit=limit)
        services.extend(list(retrieval_meta.get("services") or []))
        tool_events.append(
            {
                "tool": "search_scope",
                "question": search_question,
                "result_count": len(items),
                "retrieval": retrieval_meta,
            }
        )
        return {
            "result_count": len(items),
            "summary": _summarize_evidence(items),
            "selected_candidates": int((retrieval_meta.get("aggregate") or {}).get("selected_candidates", len(items))),
        }

    async def list_scope_documents_tool(corpus_id: str = "") -> dict[str, Any]:
        timeout = httpx.Timeout(runtime_settings.request_timeout_seconds)
        selected_corpora = [corpus_id] if corpus_id else list(scope_snapshot.get("corpus_ids") or [])
        documents: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for candidate in selected_corpora:
                if candidate and candidate not in scope_snapshot.get("corpus_ids", []):
                    continue
                docs = await fetch_corpus_documents_fn(client, user=user, corpus_id=candidate)
                documents.extend(docs[:AGENT_MAX_DOCUMENTS])
        tool_events.append(
            {
                "tool": "list_scope_documents",
                "corpus_id": corpus_id,
                "result_count": len(documents),
            }
        )
        rendered = [
            {
                "corpus_id": str(item.get("corpus_id") or ""),
                "document_id": str(item.get("document_id") or ""),
                "title": str(item.get("title") or item.get("file_name") or ""),
                "query_ready": bool(item.get("query_ready")),
            }
            for item in documents[:AGENT_MAX_DOCUMENTS]
        ]
        return {"documents": rendered}

    async def search_corpus_tool(
        corpus_id: str,
        search_question: str,
        document_ids: list[str] | None = None,
        limit: int = AGENT_MAX_EVIDENCE,
    ) -> dict[str, Any]:
        nonlocal total_retrieval_ms
        if corpus_id not in scope_snapshot.get("corpus_ids", []):
            return {"result_count": 0, "summary": "corpus_id is outside the current scope"}
        _, raw_id = parse_corpus_id(corpus_id)
        timeout = httpx.Timeout(runtime_settings.request_timeout_seconds)
        headers = downstream_headers(user)
        tool_started = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = await request_service_json_fn(
                client,
                "POST",
                f"{kb_service_url}/api/v1/kb/retrieve",
                headers=headers,
                json_body={
                    "base_id": raw_id,
                    "question": search_question,
                    "document_ids": list(document_ids or []),
                    "limit": max(1, min(limit, AGENT_MAX_EVIDENCE)),
                },
            )
        total_retrieval_ms += round((time.perf_counter() - tool_started) * 1000.0, 3)
        items = list(payload.get("items") or [])
        _collect_evidence(evidence_by_unit, items, limit=limit)
        services.append(
            {
                "corpus_id": corpus_id,
                "trace_id": str(payload.get("trace_id") or ""),
                "status": "ok",
                "retrieval": dict(payload.get("retrieval") or {}),
            }
        )
        tool_events.append(
            {
                "tool": "search_corpus",
                "corpus_id": corpus_id,
                "question": search_question,
                "result_count": len(items),
                "retrieval": dict(payload.get("retrieval") or {}),
            }
        )
        return {
            "result_count": len(items),
            "summary": _summarize_evidence(items),
            "selected_candidates": int((payload.get("retrieval") or {}).get("selected_candidates", len(items))),
        }

    tools = [
        StructuredTool.from_function(
            coroutine=search_scope_tool,
            name="search_scope",
            description="Search across all corpora currently visible in the user's scope and return grounded evidence.",
        ),
        StructuredTool.from_function(
            coroutine=list_scope_documents_tool,
            name="list_scope_documents",
            description="List queryable documents in the current scope, optionally filtered by one corpus_id.",
        ),
        StructuredTool.from_function(
            coroutine=search_corpus_tool,
            name="search_corpus",
            description="Search one corpus in the current scope, optionally restricted to a list of document_ids.",
        ),
    ]
    tools_by_name = {tool.name: tool for tool in tools}
    try:
        chat_model = build_chat_model(
            settings=settings,
            model=settings.model,
            temperature=0.1,
            max_tokens=min(settings.default_max_tokens, 800),
            streaming=False,
        ).bind_tools(tools)
        messages: list[Any] = [
            SystemMessage(
                content=(
                    "You are a retrieval agent for a grounded RAG system. "
                    "Use tools to gather evidence before answering. "
                    "Stay strictly inside the user's current scope. "
                    "Prefer search_scope first, then narrow with list_scope_documents or search_corpus if needed. "
                    "Stop after enough evidence is found. Do not exceed 3 rounds of tool calls."
                )
            ),
            HumanMessage(content=f"User question:\n{contextualized_question}"),
        ]

        for _ in range(AGENT_MAX_TOOL_CALLS):
            response = await chat_model.ainvoke(messages)
            messages.append(response)
            tool_calls = list(getattr(response, "tool_calls", []) or [])
            if not tool_calls:
                break
            for tool_call in tool_calls:
                tool_name = str(tool_call.get("name") or "")
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    continue
                tool_args = dict(tool_call.get("args") or {})
                result = await tool.ainvoke(tool_args)
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=str(tool_call.get("id") or ""),
                        name=tool_name,
                    )
                )

        final_ai_text = ""
        if messages and isinstance(messages[-1], AIMessage):
            final_ai_text = extract_message_text(messages[-1])
        if not evidence_by_unit:
            logger.info("agent mode completed without evidence final_message=%s", compact_text(final_ai_text, 120))

        evidence = _ordered_evidence(evidence_by_unit, limit=AGENT_MAX_EVIDENCE)
        retrieval_meta = {
            "services": services,
            "aggregate": {
                "empty_scope": False,
                "service_count": len(services),
                "successful_service_count": sum(1 for item in services if item.get("status") == "ok"),
                "failed_service_count": sum(1 for item in services if item.get("status") == "failed"),
                "partial_failure": any(item.get("status") == "failed" for item in services),
                "selected_candidates": len(evidence),
                "original_query": question.strip(),
                "contextualized_query": contextualized_question,
                "retrieval_ms": round(total_retrieval_ms, 3),
                "tool_call_count": len(tool_events),
                "execution_mode": "agent",
            },
            "agent": {
                "tool_calls": tool_events,
                "final_message": final_ai_text,
            },
        }
        return evidence, contextualized_question, retrieval_meta
    except Exception as exc:
        logger.warning("agent mode degraded to grounded retrieval because tool-calling failed", exc_info=True)
        fallback_evidence, fallback_question, fallback_meta = await retrieve_scope_evidence_fn(
            user=user,
            scope_snapshot=scope_snapshot,
            question=question,
            history=history,
        )
        fallback_meta = dict(fallback_meta or {})
        aggregate = dict(fallback_meta.get("aggregate") or {})
        aggregate["execution_mode"] = "agent"
        aggregate["agent_fallback"] = True
        aggregate["agent_fallback_reason"] = exc.__class__.__name__
        fallback_meta["aggregate"] = aggregate
        fallback_meta["agent"] = {
            "tool_calls": tool_events,
            "final_message": "",
            "fallback": True,
            "fallback_reason": exc.__class__.__name__,
        }
        return fallback_evidence, fallback_question, fallback_meta


def _collect_evidence(
    evidence_by_unit: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    limit: int,
) -> None:
    for item in items[: max(limit, AGENT_MAX_EVIDENCE)]:
        unit_id = str(item.get("unit_id") or "")
        if not unit_id:
            continue
        existing = evidence_by_unit.get(unit_id)
        if existing is None:
            evidence_by_unit[unit_id] = item
            continue
        existing_score = float(((existing.get("evidence_path") or {}).get("final_score") or 0.0))
        next_score = float(((item.get("evidence_path") or {}).get("final_score") or 0.0))
        if next_score > existing_score:
            evidence_by_unit[unit_id] = item


def _ordered_evidence(evidence_by_unit: dict[str, dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        evidence_by_unit.values(),
        key=lambda item: float(((item.get("evidence_path") or {}).get("final_score") or 0.0)),
        reverse=True,
    )
    limited = ordered[: max(limit, 1)]
    for index, item in enumerate(limited, start=1):
        evidence_path = dict(item.get("evidence_path") or {})
        evidence_path["final_rank"] = index
        item["evidence_path"] = evidence_path
    return limited


def _summarize_evidence(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No evidence found."
    lines: list[str] = []
    for index, item in enumerate(items[:3], start=1):
        lines.append(
            f"[{index}] {item.get('document_title') or ''} / {item.get('section_title') or ''}: "
            f"{compact_text(str(item.get('quote') or item.get('raw_text') or ''), 120)}"
        )
    return "\n".join(lines)
