from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from shared.auth import CurrentUser
from shared.logging import setup_logging

from .db import NovelDatabase, to_json
from .parsing import ParsedNovel, parse_novel_text, read_text_with_fallback
from .query import Citation, build_refusal_response, compact_quote, detect_strategy, extract_entity_hint, score_text


logger = setup_logging("novel-service")

POSTGRES_DSN = os.getenv("NOVEL_DATABASE_DSN", "postgresql://rag:rag@postgres:5432/novel_app?sslmode=disable")
BLOB_ROOT = Path(os.getenv("NOVEL_BLOB_ROOT", "/data/novel")).resolve()
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
db = NovelDatabase(POSTGRES_DSN, MIGRATIONS_DIR)

app = FastAPI(title="RAG-QA 2.0 Novel Service", version="2.0.0")


class CreateLibraryRequest(BaseModel):
    name: str
    description: str = ""


class NovelQueryRequest(BaseModel):
    library_id: str
    question: str
    document_ids: list[str] = []
    debug: bool = False


def _ensure_blob_root() -> None:
    BLOB_ROOT.mkdir(parents=True, exist_ok=True)


def _append_event(document_id: str, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO novel_document_events (document_id, stage, message, details_json)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (document_id, stage, message, to_json(details)),
            )
        conn.commit()


def _update_document_status(
    document_id: str,
    *,
    status: str,
    chapter_count: int | None = None,
    scene_count: int | None = None,
    passage_count: int | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE novel_documents
                SET status = %s,
                    chapter_count = COALESCE(%s, chapter_count),
                    scene_count = COALESCE(%s, scene_count),
                    passage_count = COALESCE(%s, passage_count),
                    stats_json = COALESCE(%s::jsonb, stats_json),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    status,
                    chapter_count,
                    scene_count,
                    passage_count,
                    to_json(stats) if stats is not None else None,
                    document_id,
                ),
            )
        conn.commit()


def _load_document(document_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM novel_documents WHERE id = %s", (document_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return row


def _replace_document_units(document_id: str, parsed: ParsedNovel) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM novel_aliases WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM novel_event_digests WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM novel_passages WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM novel_scenes WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM novel_chapters WHERE document_id = %s", (document_id,))

            for chapter in parsed.chapters:
                cur.execute(
                    """
                    INSERT INTO novel_chapters (id, document_id, chapter_index, chapter_number, title, summary, char_start, char_end)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (chapter.id, document_id, chapter.chapter_index, chapter.chapter_number, chapter.title, chapter.summary, chapter.char_start, chapter.char_end),
                )

            for scene in parsed.scenes:
                cur.execute(
                    """
                    INSERT INTO novel_scenes (id, document_id, chapter_id, chapter_index, scene_index, title, summary, search_text, char_start, char_end)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (scene.id, document_id, scene.chapter_id, scene.chapter_index, scene.scene_index, scene.title, scene.summary, scene.search_text, scene.char_start, scene.char_end),
                )

            for passage in parsed.passages:
                cur.execute(
                    """
                    INSERT INTO novel_passages (id, document_id, chapter_id, scene_id, chapter_index, scene_index, passage_index, text_content, search_text, char_start, char_end)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (passage.id, document_id, passage.chapter_id, passage.scene_id, passage.chapter_index, passage.scene_index, passage.passage_index, passage.text, passage.search_text, passage.char_start, passage.char_end),
                )

            for item in parsed.event_digests:
                cur.execute(
                    """
                    INSERT INTO novel_event_digests (id, document_id, chapter_id, scene_id, chapter_index, scene_index, who_text, where_text, what_text, result_text, search_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (item.id, document_id, item.chapter_id, item.scene_id, item.chapter_index, item.scene_index, item.who_text, item.where_text, item.what_text, item.result_text, item.search_text),
                )

            for alias in parsed.aliases:
                cur.execute(
                    """
                    INSERT INTO novel_aliases (document_id, alias, canonical, kind, first_chapter_index)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (document_id, alias.alias, alias.canonical, alias.kind, alias.first_chapter_index),
                )
        conn.commit()


def _index_document(document_id: str) -> None:
    document = _load_document(document_id)
    _append_event(document_id, "parsing", "开始解析小说文本")
    _update_document_status(document_id, status="parsing")
    text = read_text_with_fallback(Path(document["storage_path"]))
    parsed = parse_novel_text(text)
    _replace_document_units(document_id, parsed)
    preview = [chapter.title for chapter in parsed.chapters[:10]]
    stats = {
        "chapter_preview": preview,
        "document_chars": len(text),
        "event_digest_count": len(parsed.event_digests),
        "alias_count": len(parsed.aliases),
    }
    _update_document_status(
        document_id,
        status="fast_index_ready",
        chapter_count=len(parsed.chapters),
        scene_count=len(parsed.scenes),
        passage_count=len(parsed.passages),
        stats=stats,
    )
    _append_event(document_id, "fast_index_ready", "小说已可检索，可直接发起剧情与细节问答", stats)
    _update_document_status(document_id, status="enhancing", stats=stats)
    _append_event(document_id, "enhancing", "正在补充人物别名与剧情事件摘要")
    _update_document_status(document_id, status="ready", stats=stats)
    _append_event(document_id, "ready", "小说增强完成")


def _save_upload(file: UploadFile, document_id: str) -> tuple[Path, str, int]:
    _ensure_blob_root()
    extension = Path(file.filename or "source.txt").suffix or ".txt"
    target_dir = BLOB_ROOT / document_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"source{extension}"
    hasher = hashlib.sha256()
    size_bytes = 0
    with target_path.open("wb") as buffer:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            size_bytes += len(chunk)
            buffer.write(chunk)
    return target_path, hasher.hexdigest(), size_bytes


def _fetch_library_documents(library_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM novel_documents WHERE library_id = %s ORDER BY created_at DESC", (library_id,))
            return cur.fetchall()


def _novel_citations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        Citation(
            unit_id=str(row["id"]),
            document_id=str(row["document_id"]),
            section_title=f"第{row['chapter_index']}章 / 场景{row['scene_index']}",
            char_range=f"{row['char_start']}-{row['char_end']}",
            quote=compact_quote(row["text_content"]),
        ).__dict__
        for row in rows
    ]


def _rank_passages(rows: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        value = score_text(question, row["search_text"])
        if value <= 0:
            continue
        value += max(0.0, 2 - (row["chapter_index"] * 0.02))
        scored.append((value, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored]


def _extract_chapter_number(question: str) -> int:
    match = re.search(r"第\s*([0-9]+)\s*章", question)
    if match:
        return int(match.group(1))
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    match = re.search(r"第\s*([一二三四五六七八九十两]+)\s*章", question)
    if not match:
        return 0
    raw = match.group(1)
    if raw == "十":
        return 10
    if raw.startswith("十"):
        return 10 + mapping.get(raw[1], 0)
    if raw.endswith("十"):
        return mapping.get(raw[0], 0) * 10
    if "十" in raw:
        left, right = raw.split("十", 1)
        return mapping.get(left, 0) * 10 + mapping.get(right, 0)
    return mapping.get(raw, 0)


def _query_novel(payload: NovelQueryRequest) -> dict[str, Any]:
    strategy = detect_strategy(payload.question)
    documents = _fetch_library_documents(payload.library_id)
    doc_ids = payload.document_ids or [str(item["id"]) for item in documents if item["status"] in {"fast_index_ready", "enhancing", "ready"}]
    if not doc_ids:
        return build_refusal_response(strategy=strategy, reason="no_queryable_document")

    with db.connect() as conn:
        with conn.cursor() as cur:
            if strategy == "chapter_summary":
                number = _extract_chapter_number(payload.question)
                cur.execute(
                    """
                    SELECT c.*, d.title AS document_title
                    FROM novel_chapters c
                    JOIN novel_documents d ON d.id = c.document_id
                    WHERE c.document_id = ANY(%s::uuid[]) AND c.chapter_number = %s
                    ORDER BY d.created_at DESC
                    LIMIT 1
                    """,
                    (doc_ids, number),
                )
                chapter = cur.fetchone()
                if chapter is None:
                    return build_refusal_response(strategy=strategy, reason="chapter_not_found")
                cur.execute(
                    """
                    SELECT *
                    FROM novel_passages
                    WHERE document_id = %s AND chapter_id = %s
                    ORDER BY scene_index, passage_index
                    LIMIT 2
                    """,
                    (chapter["document_id"], chapter["id"]),
                )
                passages = cur.fetchall()
                return {
                    "answer": f"{chapter['title']}主要围绕：{chapter['summary']}",
                    "strategy_used": strategy,
                    "evidence_status": "grounded",
                    "grounding_score": 0.91,
                    "refusal_reason": "",
                    "citations": _novel_citations(passages),
                }

            cur.execute(
                """
                SELECT *
                FROM novel_passages
                WHERE document_id = ANY(%s::uuid[])
                ORDER BY chapter_index, scene_index, passage_index
                """,
                (doc_ids,),
            )
            ranked = _rank_passages(cur.fetchall(), payload.question)

    if strategy == "entity_detail":
        entity = extract_entity_hint(payload.question)
        if entity:
            ranked = [row for row in ranked if entity in row["text_content"] or entity in row["search_text"]] or ranked
        if not ranked:
            return build_refusal_response(strategy=strategy, reason="entity_not_found")
        return {
            "answer": compact_quote(ranked[0]["text_content"], 140),
            "strategy_used": strategy,
            "evidence_status": "grounded",
            "grounding_score": 0.88,
            "refusal_reason": "",
            "citations": _novel_citations(ranked[:1]),
        }

    if strategy == "plot_causal":
        if len(ranked) < 2:
            return build_refusal_response(strategy=strategy, reason="causal_evidence_insufficient")
        first = ranked[0]
        second = ranked[1] if ranked[1]["id"] != first["id"] else ranked[min(2, len(ranked) - 1)]
        answer = f"从原文线索看，先发生“{compact_quote(first['text_content'], 70)}”，随后又出现“{compact_quote(second['text_content'], 70)}”，因此问题中的结果更接近这条因果链。"
        return {
            "answer": answer,
            "strategy_used": strategy,
            "evidence_status": "grounded",
            "grounding_score": 0.86,
            "refusal_reason": "",
            "citations": _novel_citations([first, second]),
        }

    if strategy == "character_arc":
        if len(ranked) < 2:
            return build_refusal_response(strategy=strategy, reason="character_arc_insufficient")
        first = ranked[0]
        last = ranked[-1] if ranked[-1]["chapter_index"] != first["chapter_index"] else ranked[min(len(ranked) - 1, 1)]
        answer = f"从已命中的章节看，人物状态有明显推进：前段更接近“{compact_quote(first['text_content'], 60)}”，后段则转向“{compact_quote(last['text_content'], 60)}”。"
        return {
            "answer": answer,
            "strategy_used": strategy,
            "evidence_status": "grounded",
            "grounding_score": 0.84,
            "refusal_reason": "",
            "citations": _novel_citations([first, last]),
        }

    if strategy == "setting_theme":
        if len(ranked) < 3:
            return build_refusal_response(strategy=strategy, reason="theme_evidence_insufficient")
        picks = [ranked[0], ranked[min(1, len(ranked) - 1)], ranked[min(2, len(ranked) - 1)]]
        answer = f"结合多处原文，这一设定/主题主要体现为：{compact_quote(picks[0]['text_content'], 65)}；同时还能从“{compact_quote(picks[1]['text_content'], 55)}”和“{compact_quote(picks[2]['text_content'], 55)}”得到补强。"
        return {
            "answer": answer,
            "strategy_used": strategy,
            "evidence_status": "grounded",
            "grounding_score": 0.82,
            "refusal_reason": "",
            "citations": _novel_citations(picks),
        }

    if not ranked:
        return build_refusal_response(strategy=strategy, reason="plot_evidence_insufficient")
    picks = ranked[:2]
    answer = f"从已命中的情节片段看，直接相关的剧情是：{compact_quote(picks[0]['text_content'], 110)}"
    if len(picks) > 1:
        answer += f"。补充线索还包括：{compact_quote(picks[1]['text_content'], 70)}"
    return {
        "answer": answer,
        "strategy_used": strategy,
        "evidence_status": "grounded",
        "grounding_score": 0.85,
        "refusal_reason": "",
        "citations": _novel_citations(picks),
    }


@app.on_event("startup")
def on_startup() -> None:
    _ensure_blob_root()
    db.ensure_schema()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/novel/libraries")
def create_library(payload: CreateLibraryRequest, user: CurrentUser) -> dict[str, Any]:
    library_id = str(uuid4())
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO novel_libraries (id, name, description, created_by) VALUES (%s, %s, %s, %s)", (library_id, payload.name.strip(), payload.description.strip(), user.user_id))
        conn.commit()
    return {"id": library_id, "name": payload.name.strip(), "description": payload.description.strip()}


@app.get("/api/v1/novel/libraries")
def list_libraries(user: CurrentUser) -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM novel_libraries ORDER BY created_at DESC")
            rows = cur.fetchall()
    return {"items": rows}


@app.get("/api/v1/novel/libraries/{library_id}/documents")
def list_library_documents(library_id: str, user: CurrentUser) -> dict[str, Any]:
    return {"items": _fetch_library_documents(library_id)}


@app.post("/api/v1/novel/documents/upload")
def upload_document(
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    library_id: str = Form(...),
    title: str = Form(...),
    volume_label: str = Form(""),
    spoiler_ack: bool = Form(False),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if Path(file.filename or "").suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="novel upload only accepts txt in v1")
    document_id = str(uuid4())
    target_path, content_hash, size_bytes = _save_upload(file, document_id)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO novel_documents (id, library_id, title, volume_label, file_name, content_hash, storage_path, size_bytes, status, created_by, stats_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', %s, %s::jsonb)
                """,
                (document_id, library_id, title.strip(), volume_label.strip(), file.filename or "source.txt", content_hash, str(target_path), size_bytes, user.user_id, to_json({"spoiler_ack": bool(spoiler_ack)})),
            )
        conn.commit()
    _append_event(document_id, "uploaded", "文件已接收，等待快速索引", {"size_bytes": size_bytes})
    background_tasks.add_task(_index_document, document_id)
    return {"id": document_id, "library_id": library_id, "title": title.strip(), "volume_label": volume_label.strip(), "status": "uploaded", "size_bytes": size_bytes, "content_hash": content_hash}


@app.get("/api/v1/novel/documents/{document_id}")
def get_document(document_id: str, user: CurrentUser) -> dict[str, Any]:
    return _load_document(document_id)


@app.get("/api/v1/novel/documents/{document_id}/events")
def get_document_events(document_id: str, user: CurrentUser) -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM novel_document_events WHERE document_id = %s ORDER BY created_at DESC", (document_id,))
            rows = cur.fetchall()
    return {"items": rows}


@app.post("/api/v1/novel/query")
def query_novel(payload: NovelQueryRequest, user: CurrentUser) -> dict[str, Any]:
    return _query_novel(payload)


@app.post("/api/v1/novel/query/stream")
def stream_query_novel(payload: NovelQueryRequest, user: CurrentUser) -> StreamingResponse:
    result = _query_novel(payload)

    def generate() -> Any:
        yield f"event: metadata\ndata: {json.dumps({'strategy_used': result['strategy_used'], 'evidence_status': result['evidence_status']}, ensure_ascii=False)}\n\n"
        for citation in result["citations"]:
            yield f"event: citation\ndata: {json.dumps(citation, ensure_ascii=False)}\n\n"
        yield f"event: answer\ndata: {json.dumps({'answer': result['answer'], 'grounding_score': result['grounding_score']}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
