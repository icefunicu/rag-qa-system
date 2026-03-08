from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

_BOUNDARY_GROUPS = (
    ("\r\n\r\n", "\n\n", "\r\n", "\n"),
    ("；", ";"),
    ("。", "！", "？", ".", "!", "?"),
)
_TRAILING_BOUNDARY_CHARS = frozenset(' \t\r\n"\'”’」』》】）)]}')


def encode_sse_event(event_name: str, payload: Any) -> str:
    """Encode one SSE event.

    Input:
    - event_name: SSE event name.
    - payload: JSON-serializable payload.

    Output:
    - A complete SSE event frame string.

    Failure:
    - Raises TypeError if payload cannot be JSON encoded.
    """
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extend_boundary_end(text: str, end: int) -> int:
    while end < len(text) and text[end] in _TRAILING_BOUNDARY_CHARS:
        end += 1
    return end


def _find_preferred_boundary(text: str, start: int, hard_limit: int, min_chunk_size: int) -> int | None:
    for markers in _BOUNDARY_GROUPS:
        best_end: int | None = None
        for marker in markers:
            marker_start = text.rfind(marker, start, hard_limit)
            if marker_start < start:
                continue
            candidate_end = _extend_boundary_end(text, marker_start + len(marker))
            if candidate_end - start < min_chunk_size and candidate_end < len(text):
                continue
            if best_end is None or candidate_end > best_end:
                best_end = candidate_end
        if best_end is not None:
            return best_end
    return None


def _force_split_end(text: str, start: int, soft_limit: int, min_chunk_size: int) -> int:
    if soft_limit >= len(text):
        return len(text)

    whitespace_end = text.rfind(" ", start + min_chunk_size, soft_limit)
    if whitespace_end > start:
        return whitespace_end + 1
    return soft_limit


def iter_answer_snapshots(answer: str, *, chunk_size: int = 48) -> Iterator[str]:
    """Yield cumulative answer snapshots for SSE.

    Input:
    - answer: Full answer text.
    - chunk_size: Soft target size for one semantic chunk.

    Output:
    - Iterator of cumulative snapshots, ordered from short to full answer.

    Failure:
    - Raises ValueError if chunk_size is less than 1.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")

    text = answer or ""
    if not text:
        yield ""
        return

    min_chunk_size = max(8, chunk_size // 2)
    lookahead = max(12, chunk_size // 2)
    cursor = 0
    last_snapshot = ""

    while cursor < len(text):
        soft_limit = min(cursor + chunk_size, len(text))
        hard_limit = min(cursor + chunk_size + lookahead, len(text))
        end = _find_preferred_boundary(text, cursor, hard_limit, min_chunk_size)
        if end is None:
            end = _force_split_end(text, cursor, soft_limit, min_chunk_size)

        snapshot = text[:end]
        if snapshot != last_snapshot:
            yield snapshot
            last_snapshot = snapshot
        cursor = end


def iter_query_sse_messages(result: Mapping[str, Any], *, answer_chunk_size: int = 48) -> Iterator[str]:
    """Yield the full SSE message sequence for one query result.

    Input:
    - result: Query result mapping with metadata, citations and answer fields.
    - answer_chunk_size: Soft target size for answer snapshots.

    Output:
    - Iterator of encoded SSE event frames.

    Failure:
    - Propagates ValueError from iter_answer_snapshots.
    - Propagates TypeError if any payload cannot be JSON encoded.
    """
    yield encode_sse_event(
        "metadata",
        {
            "strategy_used": result.get("strategy_used", ""),
            "evidence_status": result.get("evidence_status", ""),
            "refusal_reason": result.get("refusal_reason", ""),
        },
    )

    for citation in result.get("citations", []) or []:
        yield encode_sse_event("citation", citation)

    answer_payload = {
        "grounding_score": result.get("grounding_score", 0),
        "refusal_reason": result.get("refusal_reason", ""),
    }
    for answer_snapshot in iter_answer_snapshots(str(result.get("answer", "")), chunk_size=answer_chunk_size):
        yield encode_sse_event(
            "answer",
            {
                **answer_payload,
                "answer": answer_snapshot,
            },
        )

    yield encode_sse_event("done", {})
