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
    if re.search(r"(要求|必须|禁止|规范|流程|审批|政策|规则)", question):
        return "policy_extract"
    if re.search(r"(总结|概述|讲了什么|主要内容|摘要)", question):
        return "section_summary"
    if re.search(r"(谁|什么|是否|定义|指什么|在哪里)", question):
        return "exact_match"
    return "cross_doc_answer"


def tokenize_question(question: str) -> list[str]:
    tokens = [token.strip().lower() for token in TOKEN_RE.findall(question) if token.strip()]
    return list(dict.fromkeys(tokens))


def score_text(question: str, target: str) -> float:
    normalized_target = target.lower()
    score = 0.0
    if question.lower() in normalized_target:
        score += 2.5
    for token in tokenize_question(question):
        if token in normalized_target:
            score += 1.0
    return score


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
