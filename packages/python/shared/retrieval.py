from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class EvidencePath:
    structure_hit: bool = False
    fts_rank: int | None = None
    vector_rank: int | None = None
    final_rank: int | None = None
    final_score: float = 0.0


@dataclass(frozen=True)
class EvidenceBlock:
    unit_id: str
    document_id: str
    document_title: str
    section_title: str
    chapter_title: str = ""
    scene_index: int = 0
    char_range: str = ""
    quote: str = ""
    raw_text: str = ""
    corpus_id: str = ""
    corpus_type: str = ""
    service_type: str = ""
    evidence_kind: str = "text"
    source_kind: str = "text"
    page_number: int | None = None
    asset_id: str = ""
    thumbnail_url: str = ""
    signal_scores: dict[str, float] = field(default_factory=dict)
    evidence_path: EvidencePath = field(default_factory=EvidencePath)

    def as_dict(self) -> dict[str, object]:
        """Serialize one evidence block to a JSON-friendly mapping."""
        payload = asdict(self)
        payload["evidence_path"] = asdict(self.evidence_path)
        return payload


@dataclass(frozen=True)
class RetrievalStats:
    original_query: str = ""
    rewritten_query: str = ""
    focus_query: str = ""
    rewrite_tags: list[str] = field(default_factory=list)
    expansion_terms: list[str] = field(default_factory=list)
    degraded_signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structure_candidates: int = 0
    fts_candidates: int = 0
    vector_candidates: int = 0
    fused_candidates: int = 0
    reranked_candidates: int = 0
    selected_candidates: int = 0
    retrieval_ms: float = 0.0
    rerank_applied: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalResult:
    items: list[EvidenceBlock]
    stats: RetrievalStats

    def as_dict(self) -> dict[str, object]:
        return {
            "items": [item.as_dict() for item in self.items],
            "retrieval": self.stats.as_dict(),
        }


def weighted_rrf(
    ranked_lists: dict[str, Iterable[str]],
    *,
    weights: dict[str, float],
    base_k: int = 60,
) -> dict[str, float]:
    """Return weighted reciprocal-rank-fusion scores.

    Input:
    - ranked_lists: Mapping of signal name to ordered unit IDs.
    - weights: Per-signal fusion weight.
    - base_k: RRF denominator offset.

    Output:
    - Mapping of unit ID to fused score.

    Failure:
    - Never raises for normal iterable input.
    """
    scores: dict[str, float] = {}
    for signal, items in ranked_lists.items():
        weight = float(weights.get(signal, 1.0))
        for rank, item in enumerate(items, start=1):
            if not item:
                continue
            scores[item] = scores.get(item, 0.0) + (weight / float(base_k + rank))
    return scores
