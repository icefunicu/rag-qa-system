from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,8}")


@dataclass(frozen=True)
class Citation:
    unit_id: str
    document_id: str
    section_title: str
    char_range: str
    quote: str


def detect_strategy(question: str) -> str:
    if re.search(r"第\s*[0-9一二三四五六七八九十百千万零两〇]+\s*章", question) and re.search(r"(讲了什么|内容|概述|总结|剧情)", question):
        return "chapter_summary"
    if re.search(r"(为什么|为何|怎么导致|因果|前因后果)", question):
        return "plot_causal"
    if re.search(r"(成长|变化|关系|转变|发展轨迹)", question):
        return "character_arc"
    if re.search(r"(主题|设定|世界观|氛围|基调|作用)", question):
        return "setting_theme"
    if re.search(r"(发生了什么|什么剧情|结尾|末尾|后来怎样)", question):
        return "plot_event"
    if re.search(r"(是谁|是什么|什么人|什么组织|什么地方|何人)", question):
        return "entity_detail"
    return "plot_event"


def tokenize_question(question: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(question):
        normalized = token.strip().lower()
        if not normalized:
            continue
        tokens.append(normalized)
        if len(normalized) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
            for index in range(len(normalized) - 1):
                tokens.append(normalized[index : index + 2])
    return list(dict.fromkeys(tokens))


def score_text(question: str, target: str, *, weight_exact: float = 2.5) -> float:
    normalized_target = target.lower()
    score = 0.0
    if question.lower() in normalized_target:
        score += weight_exact
    for token in tokenize_question(question):
        if token in normalized_target:
            score += 1.0
    return score


def extract_entity_hint(question: str) -> str:
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9·]{2,16})(是谁|是什么|什么人|什么组织|什么地方)", question)
    if not match:
        return ""
    return match.group(1).strip()


def compact_quote(text: str, limit: int = 180) -> str:
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return compact[:limit].strip()


def build_refusal_response(*, strategy: str, reason: str) -> dict[str, Any]:
    return {
        "answer": "当前证据不足，无法给出可靠回答。",
        "strategy_used": strategy,
        "evidence_status": "insufficient",
        "grounding_score": 0.0,
        "refusal_reason": reason,
        "citations": [],
    }
