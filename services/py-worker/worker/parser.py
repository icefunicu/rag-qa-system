from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from docx import Document as DocxDocument
from pypdf import PdfReader

from worker.chunking import ParsedSegment


TXT_SECTION_PATTERNS = (
    re.compile(r"^\s*(第[0-9零一二三四五六七八九十百千万两〇ＯoOIVXLCDMivxlcdm]+[章节卷篇回幕集].*)$"),
    re.compile(r"^\s*(chapter\s+\d+[^\n]*)$", re.IGNORECASE),
    re.compile(r"^\s*(prologue|epilogue|preface|appendix)\b[^\n]*$", re.IGNORECASE),
)

DOCX_HEADING_STYLE_RE = re.compile(r"heading", re.IGNORECASE)


def parse_document(file_path: Path, file_type: str) -> List[ParsedSegment]:
    normalized = file_type.lower().strip()
    if normalized == "txt":
        return _parse_txt(file_path)
    if normalized == "pdf":
        return _parse_pdf(file_path)
    if normalized == "docx":
        return _parse_docx(file_path)
    raise ValueError(f"unsupported file_type: {file_type}")


def _parse_txt(file_path: Path) -> List[ParsedSegment]:
    raw = _read_text_with_fallback(file_path)
    if not raw.strip():
        return []

    if _contains_headings(raw):
        return _split_by_headings(raw, loc_prefix="text")
    return _split_by_windows(raw, loc_prefix="text")


def _parse_pdf(file_path: Path) -> List[ParsedSegment]:
    reader = PdfReader(str(file_path))
    segments: List[ParsedSegment] = []
    section_index = 1
    cursor = 0

    for page_num, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue

        page_segments = _split_page_or_section_text(
            text=text,
            page_or_loc=f"page:{page_num}",
            next_section_index=section_index,
            char_offset=cursor,
        )
        segments.extend(page_segments)
        section_index += len(page_segments)
        cursor += len(text)

    return segments


def _parse_docx(file_path: Path) -> List[ParsedSegment]:
    doc = DocxDocument(str(file_path))
    segments: List[ParsedSegment] = []
    current_lines: list[str] = []
    current_title = ""
    current_start = 0
    cursor = 0
    section_index = 1

    def flush() -> None:
        nonlocal current_lines, current_title, current_start, section_index
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            current_title = ""
            return
        title = current_title or _fallback_title(text, section_index)
        segments.append(
            ParsedSegment(
                text=text,
                page_or_loc=f"section:{section_index}",
                section_index=section_index,
                section_title=title,
                char_start=current_start,
                char_end=current_start + len(text),
                kind="section",
            )
        )
        section_index += 1
        current_lines = []
        current_title = ""

    for para in doc.paragraphs:
        text = para.text.strip()
        para_len = len(para.text)
        if not text:
            cursor += para_len + 1
            continue

        style_name = getattr(getattr(para, "style", None), "name", "")
        is_heading = bool(style_name and DOCX_HEADING_STYLE_RE.search(style_name))
        matched_heading = _match_heading(text)
        if is_heading or matched_heading:
            flush()
            current_start = cursor
            current_title = matched_heading or text

        if not current_lines:
            current_start = cursor
        current_lines.append(text)
        cursor += para_len + 1

    flush()
    return segments


def _read_text_with_fallback(file_path: Path) -> str:
    raw_bytes = file_path.read_bytes()
    if not raw_bytes:
        return ""

    for encoding in ("utf-8-sig", "utf-16", "utf-16le", "utf-16be", "gb18030", "gbk"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def _contains_headings(text: str) -> bool:
    for line in text.splitlines():
        if _match_heading(line):
            return True
    return False


def _split_page_or_section_text(
    *,
    text: str,
    page_or_loc: str,
    next_section_index: int,
    char_offset: int,
) -> List[ParsedSegment]:
    if _contains_headings(text):
        segments = _split_by_headings(text, loc_prefix=page_or_loc, start_index=next_section_index, char_offset=char_offset)
        return segments

    return [
        ParsedSegment(
            text=text,
            page_or_loc=page_or_loc,
            section_index=next_section_index,
            section_title=_fallback_title(text, next_section_index),
            char_start=char_offset,
            char_end=char_offset + len(text),
            kind="section",
        )
    ]


def _split_by_headings(
    text: str,
    *,
    loc_prefix: str,
    start_index: int = 1,
    char_offset: int = 0,
) -> List[ParsedSegment]:
    segments: List[ParsedSegment] = []
    current_lines: list[str] = []
    current_title = ""
    current_start = char_offset
    cursor = char_offset
    next_index = start_index

    def flush() -> None:
        nonlocal current_lines, current_title, current_start, next_index
        block = "".join(current_lines).strip()
        if not block:
            current_lines = []
            current_title = ""
            return
        title = current_title or _fallback_title(block, next_index)
        page_or_loc = loc_prefix if loc_prefix.startswith("page:") else f"{loc_prefix}:{next_index}"
        segments.append(
            ParsedSegment(
                text=block,
                page_or_loc=page_or_loc,
                section_index=next_index,
                section_title=title,
                char_start=current_start,
                char_end=current_start + len(block),
                kind="section",
            )
        )
        next_index += 1
        current_lines = []
        current_title = ""

    for raw_line in text.splitlines(keepends=True):
        stripped = raw_line.strip()
        heading = _match_heading(stripped)
        if heading:
            flush()
            current_start = cursor
            current_title = heading
            current_lines = [raw_line]
        else:
            if not current_lines and not stripped:
                cursor += len(raw_line)
                continue
            if not current_lines:
                current_start = cursor
            current_lines.append(raw_line)
        cursor += len(raw_line)

    flush()
    return segments


def _split_by_windows(
    text: str,
    *,
    loc_prefix: str,
    start_index: int = 1,
    char_offset: int = 0,
    target_chars: int = 24000,
) -> List[ParsedSegment]:
    segments: List[ParsedSegment] = []
    lines = text.splitlines(keepends=True)
    current_lines: list[str] = []
    current_start = char_offset
    cursor = char_offset
    next_index = start_index

    def flush() -> None:
        nonlocal current_lines, current_start, next_index
        block = "".join(current_lines).strip()
        if not block:
            current_lines = []
            return
        segments.append(
            ParsedSegment(
                text=block,
                page_or_loc=f"{loc_prefix}:{next_index}",
                section_index=next_index,
                section_title=_fallback_title(block, next_index),
                char_start=current_start,
                char_end=current_start + len(block),
                kind="section",
            )
        )
        next_index += 1
        current_lines = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not current_lines and not stripped:
            cursor += len(raw_line)
            continue
        if not current_lines:
            current_start = cursor

        current_lines.append(raw_line)
        cursor += len(raw_line)

        current_text_len = sum(len(item) for item in current_lines)
        if current_text_len >= target_chars:
            flush()

    flush()
    return segments


def _match_heading(line: str) -> str:
    if not line:
        return ""
    for pattern in TXT_SECTION_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return ""


def _fallback_title(text: str, index: int) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if 0 < len(first_line) <= 40:
        return first_line
    return f"section {index}"
