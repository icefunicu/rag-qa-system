from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class QueryPlan:
    intent: str = "unknown"
    intent_confidence: float = 0.0
    intent_reason: str = ""

    rewrite_variants: List[str] = field(default_factory=list)
    multi_query_enabled: bool = False

    retrieval_mode: str = "hybrid"
    retrieval_profile: str = "chunk_hybrid"
    retrieval_top_k: int = 0
    dense_weight: float = 0.7
    sparse_weight: float = 0.3
    candidate_counts: Dict[str, int] = field(default_factory=dict)

    rerank_top_k: int = 0
    rerank_scores: List[float] = field(default_factory=list)

    compression_mode: str = "none"
    compression_rate: float = 0.0

    answer_strategy: str = "llm_summary"
    answer_mode: str = "grounded_summary"
    citation_count: int = 0
    citation_ids: List[str] = field(default_factory=list)

    evidence_sufficient: bool = True
    evidence_coverage: float = 0.0
    top_score: float = 0.0
    cache_hit: bool = False

    timing_intent_ms: float = 0.0
    timing_retrieval_ms: float = 0.0
    timing_rerank_ms: float = 0.0
    timing_compression_ms: float = 0.0
    timing_generation_ms: float = 0.0
    timing_total_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": {
                "type": self.intent,
                "confidence": round(self.intent_confidence, 4),
                "reason": self.intent_reason,
            },
            "rewrite": {
                "variants": self.rewrite_variants,
                "multi_query_enabled": self.multi_query_enabled,
            },
            "retrieval": {
                "mode": self.retrieval_mode,
                "profile": self.retrieval_profile,
                "top_k": self.retrieval_top_k,
                "dense_weight": round(self.dense_weight, 4),
                "sparse_weight": round(self.sparse_weight, 4),
                "candidate_counts": self.candidate_counts,
            },
            "rerank": {
                "top_k": self.rerank_top_k,
                "scores": [round(score, 4) for score in self.rerank_scores],
            },
            "compression": {
                "mode": self.compression_mode,
                "rate": round(self.compression_rate, 4),
            },
            "answer": {
                "strategy": self.answer_strategy,
                "mode": self.answer_mode,
                "citation_count": self.citation_count,
                "citation_ids": self.citation_ids,
                "evidence_sufficient": self.evidence_sufficient,
                "evidence_coverage": round(self.evidence_coverage, 4),
                "top_score": round(self.top_score, 4),
            },
            "timing_ms": {
                "intent": round(self.timing_intent_ms, 2),
                "retrieval": round(self.timing_retrieval_ms, 2),
                "rerank": round(self.timing_rerank_ms, 2),
                "compression": round(self.timing_compression_ms, 2),
                "generation": round(self.timing_generation_ms, 2),
                "total": round(self.timing_total_ms, 2),
            },
            "cache_hit": self.cache_hit,
        }


class PlanTimer:
    def __init__(self):
        self._start: float = 0.0

    def start(self) -> "PlanTimer":
        self._start = time.time()
        return self

    def elapsed_ms(self) -> float:
        return (time.time() - self._start) * 1000
