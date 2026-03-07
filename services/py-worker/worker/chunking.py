from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, Iterable, Iterator, List, Sequence, Tuple

from .jieba_compat import load_jieba


class DocType(str, Enum):
    TECHNICAL = "technical_docs"
    GENERAL = "general_text"
    CONVERSATIONAL = "conversational"
    CODE = "code"


CHUNK_SIZES: Dict[DocType, int] = {
    DocType.TECHNICAL: 512,
    DocType.GENERAL: 1024,
    DocType.CONVERSATIONAL: 256,
    DocType.CODE: 384,
}

OVERLAP_RATIO = 0.1
WHITESPACE_RE = re.compile(r"\s+")
ALNUM_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)
CJK_BLOCK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class ParsedSegment:
    text: str
    page_or_loc: str
    section_index: int = 0
    section_title: str = ""
    char_start: int = 0
    char_end: int = 0
    kind: str = "body"


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    text: str
    page_or_loc: str
    token_count: int
    section_index: int = 0
    section_title: str = ""
    normalized_text: str = ""
    search_terms: Tuple[str, ...] = ()
    char_count: int = 0


def get_chunk_size(doc_type: DocType = DocType.GENERAL) -> int:
    return CHUNK_SIZES.get(doc_type, CHUNK_SIZES[DocType.GENERAL])


def get_overlap_size(chunk_size: int) -> int:
    return int(chunk_size * OVERLAP_RATIO)


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip().lower()


def build_search_terms(text: str, *, title: str = "", max_terms: int = 64) -> Tuple[str, ...]:
    if max_terms <= 0:
        return ()

    seen: set[str] = set()
    terms: list[str] = []

    def add(candidate: str) -> None:
        normalized = normalize_text(candidate)
        if len(normalized) < 2 or normalized in seen:
            return
        seen.add(normalized)
        terms.append(normalized)

    title_text = normalize_text(title)
    body_text = normalize_text(text)

    if title_text:
        add(title_text)
        for token in _iter_index_tokens(title_text):
            add(token)

    for token in _iter_index_tokens(body_text):
        add(token)
        if len(terms) >= max_terms:
            break

    return tuple(terms[:max_terms])


def chunk_segments(
    segments: Iterable[ParsedSegment],
    chunk_tokens: int = 800,
    overlap_tokens: int = 120,
    doc_type: DocType = DocType.GENERAL,
) -> List[Chunk]:
    del doc_type
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be > 0")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("overlap_tokens must be in [0, chunk_tokens)")

    result: List[Chunk] = []
    next_index = 0
    step = chunk_tokens - overlap_tokens
    jieba = load_jieba()

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        window: Deque[tuple[int, int]] = deque()
        total_tokens = 0
        last_emitted_last_token = 0

        for span in _iter_token_offsets(jieba, text):
            window.append(span)
            total_tokens += 1
            if len(window) < chunk_tokens:
                continue

            result.append(
                _make_chunk(
                    next_index,
                    _slice_window(text, window),
                    seg,
                    len(window),
                )
            )
            next_index += 1
            last_emitted_last_token = total_tokens
            _pop_left(window, step)

        if window and last_emitted_last_token < total_tokens:
            result.append(
                _make_chunk(
                    next_index,
                    _slice_window(text, window),
                    seg,
                    len(window),
                )
            )
            next_index += 1

    return [chunk for chunk in result if chunk.text]


def chunk_segments_by_chars(
    segments: Iterable[ParsedSegment],
    chunk_chars: int = 4096,
    overlap_chars: int = 256,
) -> List[Chunk]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be > 0")
    if overlap_chars < 0 or overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars must be in [0, chunk_chars)")

    result: List[Chunk] = []
    next_index = 0
    step = chunk_chars - overlap_chars

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        start = 0
        while start < len(text):
            end = min(start + chunk_chars, len(text))
            piece = text[start:end].strip()
            if piece:
                result.append(
                    _make_chunk(
                        next_index,
                        piece,
                        seg,
                        len(piece),
                    )
                )
                next_index += 1
            if end >= len(text):
                break
            start += step

    return result


def chunk_by_structure(
    text: str,
    doc_type: DocType,
    page_or_loc: str = "loc:unknown",
) -> List[Chunk]:
    chunk_size = get_chunk_size(doc_type)
    overlap_size = get_overlap_size(chunk_size)

    if doc_type == DocType.CODE:
        segments = _split_code_by_structure(text)
    else:
        segments = _split_text_by_paragraphs(text)

    parsed_segments = [
        ParsedSegment(text=seg, page_or_loc=page_or_loc) for seg in segments if seg.strip()
    ]

    return chunk_segments(
        parsed_segments,
        chunk_tokens=chunk_size,
        overlap_tokens=overlap_size,
        doc_type=doc_type,
    )


def _make_chunk(index: int, text: str, seg: ParsedSegment, token_count: int) -> Chunk:
    normalized = normalize_text(text)
    return Chunk(
        chunk_index=index,
        text=text,
        page_or_loc=seg.page_or_loc,
        token_count=token_count,
        section_index=seg.section_index,
        section_title=seg.section_title,
        normalized_text=normalized,
        search_terms=build_search_terms(text, title=seg.section_title),
        char_count=len(text),
    )


def _iter_index_tokens(text: str) -> Iterator[str]:
    for token in ALNUM_TOKEN_RE.findall(text):
        yield token

    for block in CJK_BLOCK_RE.findall(text):
        length = len(block)
        if length <= 12:
            yield block
        upper = min(length, 10)
        for size in (2, 3, 4):
            if size > upper:
                continue
            for idx in range(0, upper - size + 1):
                yield block[idx : idx + size]


def _iter_token_offsets(jieba_module, text: str) -> Iterator[tuple[int, int]]:
    tokenize = getattr(jieba_module, "tokenize", None)
    if callable(tokenize):
        for item in tokenize(text):
            if not isinstance(item, tuple) or len(item) < 3:
                continue
            start = item[1]
            end = item[2]
            if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                continue
            yield (start, end)
        return

    cursor = 0
    for token in jieba_module.cut(text):
        token_text = str(token)
        if not token_text:
            continue
        start = text.find(token_text, cursor)
        if start < 0:
            start = text.find(token_text)
        if start < 0:
            continue
        end = start + len(token_text)
        yield (start, end)
        cursor = end


def _slice_window(text: str, window: Deque[tuple[int, int]]) -> str:
    return text[window[0][0] : window[-1][1]].strip()


def _pop_left(window: Deque[tuple[int, int]], count: int) -> None:
    for _ in range(min(count, len(window))):
        window.popleft()


def _split_code_by_structure(code: str) -> List[str]:
    parts = re.split(r"(?=(?:^|\n)(?:def |class |async def ))", code)
    return [part for part in parts if part.strip()]


def _split_text_by_paragraphs(text: str) -> List[str]:
    paragraphs = []
    current = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)

    if current:
        paragraphs.append("\n".join(current))

    return paragraphs if paragraphs else [text]
