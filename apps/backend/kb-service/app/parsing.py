from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from docx import Document as DocxDocument
from pypdf import PdfReader


TXT_HEADING_RE = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千万零两〇]+[章节篇].*|[A-Z][A-Za-z0-9\s_-]{2,40}|#+\s+.+)$")
DOCX_HEADING_RE = re.compile(r"heading", re.IGNORECASE)


@dataclass(frozen=True)
class KBSection:
    id: str
    section_index: int
    title: str
    summary: str
    search_text: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class KBChunk:
    id: str
    section_id: str
    section_index: int
    chunk_index: int
    text: str
    search_text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ParsedKB:
    sections: list[KBSection]
    chunks: list[KBChunk]


def parse_document(path: Path, file_type: str) -> ParsedKB:
    normalized = file_type.lower()
    if normalized == "txt":
        text = _read_text_with_fallback(path)
        return _parse_text_sections(text)
    if normalized == "pdf":
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return _parse_text_sections("\n\n".join(pages))
    if normalized == "docx":
        doc = DocxDocument(str(path))
        return _parse_docx(doc)
    raise ValueError(f"unsupported file type: {file_type}")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_docx(doc: DocxDocument) -> ParsedKB:
    sections: list[KBSection] = []
    current_title = "Section 1"
    current_lines: list[str] = []
    cursor = 0
    start = 0
    section_index = 1

    def flush() -> None:
        nonlocal current_title, current_lines, start, section_index
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        section = KBSection(
            id=str(uuid4()),
            section_index=section_index,
            title=current_title,
            summary=_summary(text, 180),
            search_text=normalize_text(f"{current_title} {text[:600]}"),
            text=text,
            char_start=start,
            char_end=start + len(text),
        )
        sections.append(section)
        section_index += 1
        current_lines = []

    for para in doc.paragraphs:
        text = para.text.strip()
        para_len = len(para.text)
        style_name = getattr(getattr(para, "style", None), "name", "")
        is_heading = bool(style_name and DOCX_HEADING_RE.search(style_name))
        if is_heading and current_lines:
            flush()
            current_title = text or f"Section {section_index}"
            start = cursor
        elif is_heading:
            current_title = text or f"Section {section_index}"
            start = cursor
        elif text:
            if not current_lines:
                start = cursor
            current_lines.append(text)
        cursor += para_len + 1
    flush()
    return ParsedKB(sections=sections, chunks=_chunk_sections(sections))


def _parse_text_sections(text: str) -> ParsedKB:
    lines = text.splitlines(keepends=True)
    sections: list[KBSection] = []
    current_title = "Section 1"
    current_lines: list[str] = []
    section_index = 1
    cursor = 0
    start = 0

    def flush() -> None:
        nonlocal current_lines, current_title, start, section_index
        content = "".join(current_lines).strip()
        if not content:
            current_lines = []
            return
        sections.append(
            KBSection(
                id=str(uuid4()),
                section_index=section_index,
                title=current_title,
                summary=_summary(content, 180),
                search_text=normalize_text(f"{current_title} {content[:600]}"),
                text=content,
                char_start=start,
                char_end=start + len(content),
            )
        )
        section_index += 1
        current_lines = []

    for raw in lines:
        stripped = raw.strip()
        if stripped and TXT_HEADING_RE.match(stripped) and current_lines:
            flush()
            current_title = stripped[:80]
            start = cursor
            current_lines = [raw]
        else:
            if not current_lines and stripped:
                start = cursor
            current_lines.append(raw)
        cursor += len(raw)
    flush()
    if not sections and text.strip():
        sections.append(
            KBSection(
                id=str(uuid4()),
                section_index=1,
                title="Section 1",
                summary=_summary(text, 180),
                search_text=normalize_text(text[:600]),
                text=text.strip(),
                char_start=0,
                char_end=len(text),
            )
        )
    return ParsedKB(sections=sections, chunks=_chunk_sections(sections))


def _chunk_sections(sections: list[KBSection]) -> list[KBChunk]:
    chunks: list[KBChunk] = []
    window = 1000
    overlap = 100
    for section in sections:
        cursor = 0
        chunk_index = 1
        while cursor < len(section.text):
            end = min(cursor + window, len(section.text))
            snippet = section.text[cursor:end].strip()
            if snippet:
                chunks.append(
                    KBChunk(
                        id=str(uuid4()),
                        section_id=section.id,
                        section_index=section.section_index,
                        chunk_index=chunk_index,
                        text=snippet,
                        search_text=normalize_text(f"{section.title} {snippet}"),
                        char_start=section.char_start + cursor,
                        char_end=section.char_start + end,
                    )
                )
                chunk_index += 1
            if end >= len(section.text):
                break
            cursor = max(end - overlap, cursor + 1)
    return chunks


def _summary(text: str, limit: int) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[:limit].strip()
