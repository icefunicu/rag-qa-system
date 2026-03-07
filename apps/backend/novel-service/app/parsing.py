from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4


CHAPTER_PATTERN = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百千万零两〇]+章[：:\s].*)$",
    re.MULTILINE,
)
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")
TRANSITION_MARKERS = (
    "随后",
    "然后",
    "不久",
    "与此同时",
    "另一边",
    "次日",
    "第二天",
    "当晚",
    "清晨",
    "傍晚",
    "夜里",
    "离开",
    "来到",
    "回到",
)
STOPWORDS = {
    "我们",
    "他们",
    "自己",
    "没有",
    "一个",
    "不是",
    "这样",
    "那里",
    "这里",
    "这种",
    "那些",
    "因为",
    "如果",
    "什么",
    "时候",
    "已经",
    "还是",
    "这个",
    "那个",
}


@dataclass(frozen=True)
class ChapterUnit:
    id: str
    chapter_index: int
    chapter_number: int
    title: str
    summary: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class SceneUnit:
    id: str
    chapter_id: str
    chapter_index: int
    scene_index: int
    title: str
    summary: str
    search_text: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class PassageUnit:
    id: str
    chapter_id: str
    scene_id: str
    chapter_index: int
    scene_index: int
    passage_index: int
    text: str
    search_text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EventDigest:
    id: str
    chapter_id: str
    scene_id: str
    chapter_index: int
    scene_index: int
    who_text: str
    where_text: str
    what_text: str
    result_text: str
    search_text: str


@dataclass(frozen=True)
class AliasUnit:
    alias: str
    canonical: str
    kind: str
    first_chapter_index: int


@dataclass(frozen=True)
class ParsedNovel:
    chapters: list[ChapterUnit]
    scenes: list[SceneUnit]
    passages: list[PassageUnit]
    event_digests: list[EventDigest]
    aliases: list[AliasUnit]


def read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def parse_novel_text(text: str) -> ParsedNovel:
    chapters = _split_chapters(text)
    scenes: list[SceneUnit] = []
    passages: list[PassageUnit] = []
    event_digests: list[EventDigest] = []

    for chapter in chapters:
        chapter_scenes = _split_scenes(chapter)
        scenes.extend(chapter_scenes)
        for scene in chapter_scenes:
            event_digests.append(_build_event_digest(scene))
            passages.extend(_split_passages(scene))

    aliases = _extract_aliases(chapters, scenes, passages)
    return ParsedNovel(
        chapters=chapters,
        scenes=scenes,
        passages=passages,
        event_digests=event_digests,
        aliases=aliases,
    )


def _split_chapters(text: str) -> list[ChapterUnit]:
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        return [
            ChapterUnit(
                id=str(uuid4()),
                chapter_index=1,
                chapter_number=1,
                title="第1章：正文",
                summary=_summary(text, 220),
                text=text.strip(),
                char_start=0,
                char_end=len(text),
            )
        ]

    chapters: list[ChapterUnit] = []
    for index, match in enumerate(matches, start=1):
        start = match.start()
        end = matches[index].start() if index < len(matches) else len(text)
        block = text[start:end].strip()
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        title = lines[0] if lines else f"第{index}章"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else block
        chapters.append(
            ChapterUnit(
                id=str(uuid4()),
                chapter_index=index,
                chapter_number=_extract_chapter_number(title, fallback=index),
                title=title,
                summary=_summary(body, 220),
                text=body,
                char_start=start,
                char_end=end,
            )
        )
    return chapters


def _split_scenes(chapter: ChapterUnit) -> list[SceneUnit]:
    parts = [part.strip() for part in PARAGRAPH_SPLIT_RE.split(chapter.text) if part.strip()]
    if not parts:
        parts = [chapter.text.strip()]

    scenes: list[SceneUnit] = []
    buffer: list[str] = []
    buffer_start = chapter.char_start
    scene_index = 1
    cursor = chapter.char_start

    for part in parts:
        part_start = cursor
        cursor += len(part) + 2
        candidate = "\n\n".join(buffer + [part]).strip()
        should_flush = False
        if candidate and len(candidate) >= 1600:
            should_flush = True
        elif buffer and any(marker in part for marker in TRANSITION_MARKERS) and len(candidate) >= 600:
            should_flush = True

        if should_flush:
            text = "\n\n".join(buffer).strip()
            if text:
                scenes.append(_make_scene(chapter, scene_index, buffer_start, text))
                scene_index += 1
            buffer = [part]
            buffer_start = part_start
        else:
            if not buffer:
                buffer_start = part_start
            buffer.append(part)

    if buffer:
        scenes.append(_make_scene(chapter, scene_index, buffer_start, "\n\n".join(buffer).strip()))
    return scenes


def _make_scene(chapter: ChapterUnit, scene_index: int, char_start: int, text: str) -> SceneUnit:
    return SceneUnit(
        id=str(uuid4()),
        chapter_id=chapter.id,
        chapter_index=chapter.chapter_index,
        scene_index=scene_index,
        title=f"{chapter.title} / 场景 {scene_index}",
        summary=_summary(text, 160),
        search_text=normalize_text(f"{chapter.title} {text[:600]}"),
        text=text,
        char_start=char_start,
        char_end=char_start + len(text),
    )


def _split_passages(scene: SceneUnit) -> list[PassageUnit]:
    units: list[PassageUnit] = []
    window = 900
    overlap = 120
    cursor = 0
    passage_index = 1
    while cursor < len(scene.text):
        end = min(cursor + window, len(scene.text))
        snippet = scene.text[cursor:end].strip()
        if snippet:
            units.append(
                PassageUnit(
                    id=str(uuid4()),
                    chapter_id=scene.chapter_id,
                    scene_id=scene.id,
                    chapter_index=scene.chapter_index,
                    scene_index=scene.scene_index,
                    passage_index=passage_index,
                    text=snippet,
                    search_text=normalize_text(f"{scene.title} {snippet}"),
                    char_start=scene.char_start + cursor,
                    char_end=scene.char_start + end,
                )
            )
            passage_index += 1
        if end >= len(scene.text):
            break
        cursor = max(end - overlap, cursor + 1)
    return units


def _build_event_digest(scene: SceneUnit) -> EventDigest:
    names = [token for token in NAME_RE.findall(scene.text[:220]) if token not in STOPWORDS][:3]
    who_text = "、".join(names)
    where_match = re.search(r"(?:在|到|进入|回到)([\u4e00-\u9fff]{2,8})", scene.text[:200])
    where_text = where_match.group(1) if where_match else ""
    what_text = _summary(scene.text, 100)
    result_text = _summary(scene.text[-120:], 80)
    search_text = normalize_text(f"{scene.title} {who_text} {where_text} {what_text} {result_text}")
    return EventDigest(
        id=str(uuid4()),
        chapter_id=scene.chapter_id,
        scene_id=scene.id,
        chapter_index=scene.chapter_index,
        scene_index=scene.scene_index,
        who_text=who_text,
        where_text=where_text,
        what_text=what_text,
        result_text=result_text,
        search_text=search_text,
    )


def _extract_aliases(
    chapters: Iterable[ChapterUnit],
    scenes: Iterable[SceneUnit],
    passages: Iterable[PassageUnit],
) -> list[AliasUnit]:
    counter: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for chapter in chapters:
        for token in NAME_RE.findall(chapter.title):
            if token not in STOPWORDS:
                counter[token] += 2
                first_seen.setdefault(token, chapter.chapter_index)
    for scene in scenes:
        for token in NAME_RE.findall(scene.text[:500]):
            if token not in STOPWORDS:
                counter[token] += 1
                first_seen.setdefault(token, scene.chapter_index)
    for passage in passages:
        for token in NAME_RE.findall(passage.text[:300]):
            if token not in STOPWORDS:
                counter[token] += 1
                first_seen.setdefault(token, passage.chapter_index)

    results: list[AliasUnit] = []
    for alias, count in counter.most_common(80):
        if count < 4:
            continue
        results.append(
            AliasUnit(
                alias=alias,
                canonical=alias,
                kind="entity",
                first_chapter_index=first_seen.get(alias, 0),
            )
        )
    return results


def _summary(text: str, limit: int) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[:limit].strip()


def _extract_chapter_number(title: str, *, fallback: int) -> int:
    match = re.search(r"第\s*([0-9]+|[一二三四五六七八九十百千万零两〇]+)\s*章", title)
    if not match:
        return fallback
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _zh_to_int(raw) or fallback


def _zh_to_int(raw: str) -> int:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    current = 0
    number = 0
    for char in raw:
        if char in digits:
            number = digits[char]
            continue
        unit = units.get(char)
        if unit is None:
            continue
        if number == 0:
            number = 1
        if unit == 10000:
            current = (current + number) * unit
            total += current
            current = 0
        else:
            current += number * unit
        number = 0
    return total + current + number
