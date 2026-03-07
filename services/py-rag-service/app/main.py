from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, Sequence
from uuid import UUID

from app.query_planner import QueryPlan, PlanTimer
from app.guardrails import validate_question, GuardrailResult

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchAny, ScoredPoint

from .hybrid_retriever import HybridRetriever, RetrievalResult
from .logger import setup_logger
from .query_cache import QueryCache
from .intent_classifier import IntentClassifier, get_classifier, IntentType
from .query_rewriter import QueryRewriter, MultiQueryRetriever
from .scope_chunk_retriever import ScopeChunkRetriever
from .exceptions import RAGServiceError, LLMError, RetrievalError, ValidationError
from .metrics import metrics_collector, QueryMetrics
from .retrieval_tracker import get_tracker, track_retrieval, get_retrieval_quality_stats

logger = setup_logger(
    name=__name__,
    level=os.getenv("LOG_LEVEL", "INFO"),
    service_name="py-rag-service",
)


COMMON_KNOWLEDGE_PREFIX = "【常识补充】"
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434/v1"
DEFAULT_FALLBACK_EMBEDDING_DIM = 256
API_KEY_OPTIONAL_PROVIDERS = {"custom", "ollama"}

CHAT_PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "ollama": DEFAULT_OLLAMA_BASE_URL,
}
EMBEDDING_PROVIDER_BASE_URLS = dict(CHAT_PROVIDER_BASE_URLS)
EMBEDDING_PROVIDER_BASE_URLS["gemini"] = "https://generativelanguage.googleapis.com/v1beta"
DIMENSION_AWARE_EMBEDDING_PROVIDERS = {"openai", "qwen"}

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
EVIDENCE_DUMP_RE = re.compile(r"\[\d+\]\s*file=", re.IGNORECASE)


class Scope(BaseModel):
    mode: Literal["single", "multi"]
    corpus_ids: List[str] = Field(min_length=1)
    document_ids: List[str] = Field(default_factory=list)
    allow_common_knowledge: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "Scope":
        if self.mode == "single" and len(self.corpus_ids) != 1:
            raise ValueError("scope.mode=single requires exactly one corpus_id")
        if self.mode == "multi" and len(self.corpus_ids) < 2:
            raise ValueError("scope.mode=multi requires at least two corpus_ids")

        corpus_seen: set[str] = set()
        for corpus_id in self.corpus_ids:
            trimmed = corpus_id.strip()
            if not trimmed:
                raise ValueError("scope.corpus_ids must not contain empty values")
            _validate_uuid(trimmed, "scope.corpus_ids")
            if trimmed in corpus_seen:
                raise ValueError(f"scope.corpus_ids contains duplicate value: {trimmed}")
            corpus_seen.add(trimmed)

        document_seen: set[str] = set()
        for document_id in self.document_ids:
            trimmed = document_id.strip()
            if not trimmed:
                raise ValueError("scope.document_ids must not contain empty values")
            _validate_uuid(trimmed, "scope.document_ids")
            if trimmed in document_seen:
                raise ValueError(f"scope.document_ids contains duplicate value: {trimmed}")
            document_seen.add(trimmed)

        return self


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    scope: Scope


class StreamQueryRequest(BaseModel):
    """流式查询请求（与传统请求相同）"""
    question: str = Field(min_length=1, max_length=8000)
    scope: Scope


class StreamQueryParams(BaseModel):
    """流式查询 URL 参数"""
    question: str = Field(min_length=1, max_length=8000)
    scope_json: str = Field(..., description="JSON encoded Scope object")


class AnswerSentence(BaseModel):
    text: str
    evidence_type: Literal["source", "common_knowledge"]
    citation_ids: List[str]
    confidence: float


class Citation(BaseModel):
    citation_id: str
    file_name: str
    page_or_loc: str
    chunk_id: str
    snippet: str
    section_title: Optional[str] = None


class QueryResponse(BaseModel):
    answer_sentences: List[AnswerSentence]
    citations: List[Citation]
    evidence_coverage: Optional[float] = None
    answer_mode: Optional[str] = None
    debug_bundle: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ServiceConfig:
    postgres_dsn: str
    qdrant_url: str
    qdrant_collection: str
    embedding_dim: int
    retrieval_top_n: int
    rerank_top_k: int
    source_sentence_limit: int
    evidence_min_score: float
    common_knowledge_max_ratio: float
    embedding_provider: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    chat_provider: str
    chat_base_url: str
    chat_api_key: str
    chat_model: str
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_retry_delay_milliseconds: int
    hybrid_dense_weight: float
    hybrid_sparse_weight: float
    reranker_model: str
    query_cache_enabled: bool
    query_cache_ttl_hours: int
    query_cache_max_size: int
    sparse_retrieval_enabled: bool
    sparse_cache_ttl_seconds: int
    sparse_cache_max_scopes: int
    section_top_k: int = 8
    section_expand_chunk_limit: int = 6
    evidence_coverage_threshold: float = 0.35
    multi_query_enabled: bool = False
    multi_query_max_variants: int = 3
    multi_query_timeout_ms: int = 500


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    document_id: str
    corpus_id: str
    file_name: str
    page_or_loc: str
    text: str
    vector_score: float
    lexical_score: float
    final_score: float
    section_id: str = ""
    section_title: str = ""
    point_type: str = "chunk"


def _resolve_provider_base_url(
    provider: str,
    explicit_base_url: str,
    base_urls: dict[str, str],
) -> str:
    normalized = provider.strip().lower()
    explicit = explicit_base_url.strip()
    if explicit:
        return _normalize_provider_base_url(normalized, explicit)
    if normalized == "custom":
        return ""
    if normalized == "ollama":
        return _normalize_provider_base_url(
            normalized,
            os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        )
    return _normalize_provider_base_url(
        normalized,
        base_urls.get(normalized, base_urls["openai"]),
    )


def _normalize_provider_base_url(provider: str, base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return ""
    if provider == "ollama" and not normalized.endswith("/v1"):
        return f"{normalized}/v1"
    return normalized


def _provider_requires_api_key(provider: str) -> bool:
    return provider.strip().lower() not in API_KEY_OPTIONAL_PROVIDERS


class LLMGateway:
    def __init__(self, cfg: ServiceConfig):
        self._cfg = cfg
        self._embedding_base_url = _resolve_provider_base_url(
            cfg.embedding_provider,
            cfg.embedding_base_url,
            EMBEDDING_PROVIDER_BASE_URLS,
        )
        self._chat_base_url = _resolve_provider_base_url(
            cfg.chat_provider,
            cfg.chat_base_url,
            CHAT_PROVIDER_BASE_URLS,
        )
        self._client = httpx.Client(timeout=cfg.llm_timeout_seconds)

    @property
    def embedding_enabled(self) -> bool:
        has_auth = bool(self._cfg.embedding_api_key) or not _provider_requires_api_key(self._cfg.embedding_provider)
        return bool(has_auth and self._cfg.embedding_model and self._embedding_base_url)

    @property
    def chat_enabled(self) -> bool:
        has_auth = bool(self._cfg.chat_api_key) or not _provider_requires_api_key(self._cfg.chat_provider)
        return bool(has_auth and self._cfg.chat_model and self._chat_base_url)

    def embed(self, text: str) -> List[float]:
        if not self.embedding_enabled:
            return hash_embedding(text, self._cfg.embedding_dim)

        if self._cfg.embedding_provider == "gemini":
            return self._request_gemini_embedding(text, task_type="RETRIEVAL_QUERY")

        payload = {
            "model": self._cfg.embedding_model,
            "input": text,
        }
        if self._cfg.embedding_provider in DIMENSION_AWARE_EMBEDDING_PROVIDERS and self._cfg.embedding_dim > 0:
            payload["dimensions"] = self._cfg.embedding_dim

        data = self._request_openai_compatible_json(
            base_url=self._embedding_base_url,
            api_key=self._cfg.embedding_api_key,
            path="/embeddings",
            payload=payload,
        )
        try:
            embedding = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("embedding response format invalid") from exc

        if not isinstance(embedding, list) or len(embedding) == 0:
            raise RuntimeError("embedding response contains empty vector")

        try:
            return [float(v) for v in embedding]
        except (TypeError, ValueError) as exc:
            raise RuntimeError("embedding response contains non-numeric vector values") from exc

    def generate_summary(self, question: str, evidence: Sequence[RankedChunk]) -> str:
        if not self.chat_enabled or len(evidence) == 0:
            return ""

        evidence_lines = []
        for idx, chunk in enumerate(evidence, start=1):
            evidence_lines.append(
                f"[{idx}] file={chunk.file_name} loc={chunk.page_or_loc}\n{compact_snippet(chunk.text, limit=260)}"
            )

        payload = {
            "model": self._cfg.chat_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是企业知识库问答助手。"
                        "必须严格基于给定证据回答，不可虚构。"
                        "输出中文，最多两句，不要输出引用编号。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n\n"
                        f"证据：\n{chr(10).join(evidence_lines)}\n\n"
                        "请给出简洁答案。"
                    ),
                },
            ],
        }
        data = self._request_openai_compatible_json(
            base_url=self._chat_base_url,
            api_key=self._cfg.chat_api_key,
            path="/chat/completions",
            payload=payload,
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("chat response format invalid") from exc

        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    pieces.append(str(item["text"]))
            merged = "".join(pieces).strip()
        else:
            merged = str(content).strip()

        if not merged:
            raise RuntimeError("chat response content is empty")

        return merged

    def _request_gemini_embedding(self, text: str, task_type: str) -> List[float]:
        model = self._cfg.embedding_model.strip()
        model_path = model if model.startswith("models/") else f"models/{model}"
        payload: dict[str, Any] = {
            "model": model_path,
            "content": {
                "parts": [{"text": text}],
            },
            "task_type": task_type,
        }
        if self._cfg.embedding_dim > 0:
            payload["output_dimensionality"] = self._cfg.embedding_dim

        data = self._request_provider_json(
            url=f"{self._embedding_base_url}/{model_path}:embedContent",
            headers={
                "x-goog-api-key": self._cfg.embedding_api_key,
                "Content-Type": "application/json",
            },
            payload=payload,
        )

        vector_raw: Optional[Any] = None
        embedding = data.get("embedding")
        if isinstance(embedding, dict):
            vector_raw = embedding.get("values")
        if vector_raw is None:
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0]
                if isinstance(first, dict):
                    vector_raw = first.get("values")

        if not isinstance(vector_raw, list) or len(vector_raw) == 0:
            raise RuntimeError("embedding response format invalid")

        try:
            numeric = [float(v) for v in vector_raw]
        except (TypeError, ValueError) as exc:
            raise RuntimeError("embedding response contains non-numeric vector values") from exc
        return _normalize_vector(numeric)

    def _request_openai_compatible_json(
        self,
        *,
        base_url: str,
        api_key: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not base_url:
            raise RuntimeError("provider base URL is required")

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        return self._request_provider_json(
            url=f"{base_url}{path}",
            headers=headers,
            payload=payload,
        )

    def _request_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_openai_compatible_json(
            base_url=self._chat_base_url,
            api_key=self._cfg.chat_api_key,
            path=path,
            payload=payload,
        )

    def _request_provider_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {
            **headers,
        }

        attempts = self._cfg.llm_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                resp = self._client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    self._sleep_between_retries()
                    continue
                raise RuntimeError(f"llm request failed: {exc}") from exc

            if resp.status_code >= 500 and attempt < attempts:
                self._sleep_between_retries()
                continue

            if resp.status_code >= 400:
                body = (resp.text or "").strip().replace("\n", " ")
                if len(body) > 300:
                    body = body[:300] + "..."
                raise RuntimeError(f"provider request rejected: status={resp.status_code} body={body}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError("provider response is not valid json") from exc

            if not isinstance(data, dict):
                raise RuntimeError("provider response json is not an object")
            return data

        raise RuntimeError("provider request exhausted retries")

    def _sleep_between_retries(self) -> None:
        delay_ms = self._cfg.llm_retry_delay_milliseconds
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    def close(self) -> None:
        self._client.close()


class RAGEngine:
    def __init__(self, cfg: ServiceConfig):
        self._cfg = cfg
        self._client = QdrantClient(url=cfg.qdrant_url)
        self._llm = LLMGateway(cfg)
        self._hybrid_retriever = HybridRetriever(
            dense_weight=cfg.hybrid_dense_weight,
            sparse_weight=cfg.hybrid_sparse_weight,
        )
        self._intent_classifier = get_classifier()
        self._query_rewriter = QueryRewriter(llm_client=None)
        self._multi_query_retriever: Optional[MultiQueryRetriever] = None
        if cfg.multi_query_enabled:
            self._multi_query_retriever = MultiQueryRetriever(
                base_retriever=self._hybrid_retriever,
                query_rewriter=self._query_rewriter,
                max_variants=cfg.multi_query_max_variants,
                timeout_ms=cfg.multi_query_timeout_ms,
            )
        self._last_retrieval_count = 0
        self._last_rerank_scores: list[float] = []
        self._last_intent: Optional[Dict] = None
        self._query_cache: Optional[QueryCache] = None
        if cfg.query_cache_enabled:
            self._query_cache = QueryCache(
                max_size=cfg.query_cache_max_size,
                ttl_hours=cfg.query_cache_ttl_hours,
            )
        self._scope_chunk_retriever: Optional[ScopeChunkRetriever] = None
        if cfg.sparse_retrieval_enabled:
            self._scope_chunk_retriever = ScopeChunkRetriever(
                cfg.postgres_dsn,
                ttl_seconds=cfg.sparse_cache_ttl_seconds,
                max_scopes=cfg.sparse_cache_max_scopes,
            )

    def close(self) -> None:
        self._llm.close()
        if self._scope_chunk_retriever is not None:
            self._scope_chunk_retriever.close()
        close_qdrant = getattr(self._client, "close", None)
        if callable(close_qdrant):
            close_qdrant()

    def query(self, question: str, scope: Scope, debug: bool = False) -> QueryResponse:
        start_time = time.time()
        query_id = None
        plan = QueryPlan()
        timer = PlanTimer()

        try:
            query_id = get_tracker().generate_query_id()
        except Exception:
            pass

        metrics_start = metrics_collector.start_request()


        # ── IT-023: 意图分类（记录到 QueryPlan）──
        timer.start()
        intent_result = self._intent_classifier.classify_and_get_strategy(question)
        self._last_intent = intent_result
        plan.intent = intent_result["intent"]
        plan.intent_confidence = intent_result.get("confidence", 0.0)
        plan.intent_reason = intent_result.get("reason", "")
        plan.timing_intent_ms = timer.elapsed_ms()

        logger.info(
            f"Intent classification result",
            extra={
                "query_id": query_id,
                "extra_fields": {
                    "intent": intent_result["intent"],
                    "confidence": intent_result["confidence"],
                    "reason": intent_result["reason"],
                },
                "intent_info": {
                    "intent": intent_result["intent"],
                    "confidence": intent_result["confidence"],
                    "reason": intent_result["reason"],
                },
            },
        )

        # ── IT-024: 根据意图选择检索策略 ──
        strategy = intent_result["strategy"]
        effective_top_n = strategy.get("top_k", self._cfg.retrieval_top_n)
        effective_rerank_top_k = strategy.get("rerank_top_k", self._cfg.rerank_top_k)
        effective_dense_weight = strategy.get("dense_weight", self._cfg.hybrid_dense_weight)
        effective_sparse_weight = strategy.get("sparse_weight", self._cfg.hybrid_sparse_weight)

        plan.retrieval_top_k = effective_top_n
        plan.rerank_top_k = effective_rerank_top_k
        plan.dense_weight = effective_dense_weight
        plan.sparse_weight = effective_sparse_weight
        plan.retrieval_profile = self._build_retrieval_profile(question, intent_result["intent"])
        plan.multi_query_enabled = bool(
            self._multi_query_retriever is not None and self._cfg.multi_query_enabled
        )

        revision = "scope:unknown"
        if self._scope_chunk_retriever is not None:
            revision = self._scope_chunk_retriever.scope_revision(scope)
        cache_key = self._build_cache_key(
            question,
            scope,
            debug=debug,
            retrieval_profile=plan.retrieval_profile,
            revision=revision,
        )
        if self._query_cache is not None:
            cached_result = self._query_cache.get(cache_key)
            if cached_result is not None:
                metrics_collector.record_cache_hit()
                metrics_collector.end_request(metrics_start)
                plan.cache_hit = True
                metrics_collector.record_query(QueryMetrics(
                    latency_seconds=(time.time() - start_time),
                    cache_hit=True,
                    retrieval_count=0,
                    status="success",
                    intent=intent_result.get("intent", "unknown"),
                    intent_confidence=intent_result.get("confidence", 0.0),
                    query_id=query_id,
                ))
                return cached_result
        metrics_collector.record_cache_miss()

        logger.info(
            f"Routing to retrieval strategy based on intent",
            extra={
                "query_id": query_id,
                "extra_fields": {
                    "intent": intent_result["intent"],
                    "top_k": effective_top_n,
                    "rerank_top_k": effective_rerank_top_k,
                    "dense_weight": effective_dense_weight,
                    "sparse_weight": effective_sparse_weight,
                },
                "retrieval_stats": {
                    "top_k": effective_top_n,
                    "rerank_top_k": effective_rerank_top_k,
                    "dense_weight": effective_dense_weight,
                },
            },
        )

        query_filter = build_scope_filter(scope, point_type="chunk")
        section_filter = build_scope_filter(scope, point_type="section_summary")

        multi_query_used = False
        multi_query_variants = 0
        dense_results: list[RetrievalResult] = []
        sparse_results: list[RetrievalResult] = []
        section_sparse_results = []
        section_dense_results: list[RetrievalResult] = []
        timer.start()

        # ── IT-024: 检索阶段 ──
        if plan.retrieval_profile in {"chapter_summary", "relation_multi_hop", "theme"}:
            section_sparse_results = self._retrieve_section_candidates(question, scope, self._cfg.section_top_k)
            section_dense_results = self._retrieve_dense_section_results(question, section_filter, self._cfg.section_top_k)
            section_ids = self._select_section_ids(section_sparse_results, section_dense_results)
            sparse_results = self._retrieve_sparse_results(question, scope, effective_top_n, section_ids=section_ids)
            if not sparse_results and section_ids and self._scope_chunk_retriever is not None:
                sparse_results = self._scope_chunk_retriever.expand_sections(
                    scope,
                    section_ids,
                    top_k=max(effective_top_n, self._cfg.section_expand_chunk_limit * len(section_ids)),
                )
            retrieval_results = self._merge_section_chunk_results(
                sparse_results,
                section_sparse_results,
                section_dense_results,
            )
            plan.retrieval_mode = "section_first"
            plan.candidate_counts = {
                "section_sparse": len(section_sparse_results),
                "section_dense": len(section_dense_results),
                "chunk_sparse": len(sparse_results),
            }
        elif self._multi_query_retriever is not None and self._cfg.multi_query_enabled:
            multi_query_used = True
            plan.retrieval_mode = "dense_multi_query"
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            ranked_points = loop.run_until_complete(
                self._multi_query_retriever.retrieve(
                    question=question,
                    top_k=effective_rerank_top_k,
                    query_filter=query_filter,
                )
            )

            multi_query_variants = getattr(self._multi_query_retriever, '_last_variant_count', 0)
            if multi_query_variants > 0:
                metrics_collector.record_multi_query_usage(multi_query_variants)

            sparse_results = self._retrieve_sparse_results(question, scope, effective_top_n)
            dense_results = [
                coerced
                for coerced in (self._coerce_retrieval_result(item) for item in ranked_points)
                if coerced is not None
            ]
            plan.candidate_counts = {
                "chunk_sparse": len(sparse_results),
                "chunk_dense": len(dense_results),
            }
        else:
            sparse_results = self._retrieve_sparse_results(question, scope, effective_top_n)
            dense_results = self._retrieve_dense_results(question, query_filter, effective_top_n)
            plan.candidate_counts = {
                "chunk_sparse": len(sparse_results),
                "chunk_dense": len(dense_results),
            }

        if plan.retrieval_mode != "section_first":
            if dense_results and sparse_results:
                plan.retrieval_mode = "hybrid_dense_sparse" if plan.retrieval_mode != "dense_multi_query" else plan.retrieval_mode
                retrieval_results = self._hybrid_retriever.hybrid_search(
                    dense_results,
                    sparse_results,
                    top_k=max(effective_top_n, effective_rerank_top_k),
                )
            elif dense_results:
                retrieval_results = dense_results
                plan.retrieval_mode = "dense"
            else:
                plan.retrieval_mode = "sparse"
                retrieval_results = sparse_results

        ranked = self._rank_retrieval_results(
            question,
            retrieval_results,
            effective_rerank_top_k,
            effective_dense_weight,
        )
        plan.timing_retrieval_ms = timer.elapsed_ms()
        self._last_retrieval_count = len(ranked)
        plan.rerank_scores = [item.final_score for item in ranked]
        plan.top_score = ranked[0].final_score if ranked else 0.0

        # ── IT-026: no-evidence / refusal / weak-evidence 路径 ──
        if False and not ranked:
            self._last_rerank_scores = []
            plan.evidence_sufficient = False
            plan.answer_strategy = "no_evidence"
            if not scope.allow_common_knowledge:
                # 严格拒答模式
                plan.answer_strategy = "refusal"
                response = build_refusal_response()
            else:
                response = build_no_evidence_response()
        elif False:
            self._last_rerank_scores = [item.final_score for item in ranked]

            best = ranked[0]
            if best.final_score < self._cfg.evidence_min_score:
                plan.evidence_sufficient = False
                plan.answer_strategy = "weak_evidence"
                response = build_weak_evidence_response(best)
            else:
                source_limit = min(self._cfg.source_sentence_limit, len(ranked))
                selected = ranked[:source_limit]

                citations: list[Citation] = []
                for idx, chunk in enumerate(selected, start=1):
                    citation_id = f"c{idx}"
                    citations.append(
                        Citation(
                            citation_id=citation_id,
                            file_name=chunk.file_name,
                            page_or_loc=chunk.page_or_loc,
                            chunk_id=chunk.chunk_id,
                            snippet=compact_snippet(chunk.text, limit=220),
                        )
                    )

                # ── IT-024: LLM 摘要生成 ──
                timer.start()
                answer_sentences: list[AnswerSentence] = []
                summary = ""
                try:
                    summary = self._llm.generate_summary(question, selected)
                except Exception:
                    summary = ""
                summary = sanitize_summary(summary)
                plan.timing_generation_ms = timer.elapsed_ms()

                if summary:
                    plan.answer_strategy = "llm_summary"
                    answer_sentences.append(
                        AnswerSentence(
                            text=summary,
                            evidence_type="source",
                            citation_ids=[item.citation_id for item in citations],
                            confidence=clip_confidence(best.final_score),
                        )
                    )
                else:
                    plan.answer_strategy = "fallback_snippet"
                    fallback_selected = selected[: min(2, len(selected))]
                    for idx, chunk in enumerate(fallback_selected, start=1):
                        citation_id = f"c{idx}"
                        snippet = compact_snippet(chunk.text, limit=220)
                        answer_sentences.append(
                            AnswerSentence(
                                text=f"根据资料可知：{snippet}",
                                evidence_type="source",
                                citation_ids=[citation_id],
                                confidence=clip_confidence(chunk.final_score),
                            )
                        )

                max_common = max_common_sentences(len(answer_sentences), self._cfg.common_knowledge_max_ratio)
                if scope.allow_common_knowledge and max_common > 0:
                    answer_sentences.append(
                        AnswerSentence(
                            text=f"{COMMON_KNOWLEDGE_PREFIX}以下内容为模型补充推断，请结合原文证据核验。",
                            evidence_type="common_knowledge",
                            citation_ids=[],
                            confidence=0.3,
                        )
                    )

                # ── IT-025: claim-to-citation 对齐校验 ──
                valid_citation_ids = {c.citation_id for c in citations}
                for sentence in answer_sentences:
                    if sentence.evidence_type == "source":
                        # 过滤掉不存在的 citation_id
                        valid_refs = [cid for cid in sentence.citation_ids if cid in valid_citation_ids]
                        if not valid_refs and sentence.citation_ids:
                            # 所有引用都无效 → 降级为 common_knowledge
                            sentence.citation_ids = []
                            sentence.evidence_type = "common_knowledge"
                            sentence.text = f"{COMMON_KNOWLEDGE_PREFIX}{sentence.text}"
                        else:
                            sentence.citation_ids = valid_refs

                plan.citation_count = len(citations)
                plan.citation_ids = [c.citation_id for c in citations]
                response = QueryResponse(answer_sentences=answer_sentences, citations=citations)

        response, document_refs = self._build_grounded_response(
            question=question,
            scope=scope,
            ranked=ranked,
            retrieval_profile=plan.retrieval_profile,
            plan=plan,
        )
        if debug:
            response.debug_bundle = plan.to_dict()

        if self._query_cache is not None:
            self._query_cache.set(cache_key, response, document_refs=document_refs)

        latency = time.time() - start_time
        plan.timing_total_ms = latency * 1000
        metrics_collector.end_request(metrics_start)

        avg_rerank_score = sum(self._last_rerank_scores) / len(self._last_rerank_scores) if self._last_rerank_scores else 0.0

        metrics_collector.record_query(QueryMetrics(
            latency_seconds=latency,
            cache_hit=False,
            retrieval_count=len(ranked),
            rerank_score_avg=avg_rerank_score,
            status="success",
            intent=intent_result.get("intent", "unknown"),
            intent_confidence=intent_result.get("confidence", 0.0),
            multi_query_used=multi_query_used,
            multi_query_variants=multi_query_variants,
            query_id=query_id,
        ))

        logger.info(
            f"RAG query completed",
            extra={
                "query_id": query_id,
                "extra_fields": {
                    "answer_sentences": len(response.answer_sentences),
                    "citations": len(response.citations),
                    "retrieval_count": len(ranked),
                    "avg_rerank_score": round(avg_rerank_score, 4),
                    "latency_ms": round(latency * 1000, 2),
                    "answer_strategy": plan.answer_strategy,
                },
                "retrieval_stats": {
                    "retrieved_docs": len(ranked),
                    "avg_score": round(avg_rerank_score, 4),
                    "top_score": round(self._last_rerank_scores[0], 4) if self._last_rerank_scores else 0.0,
                },
            },
        )

        try:
            track_retrieval(
                question=question,
                intent=intent_result.get("intent", "unknown"),
                intent_confidence=intent_result.get("confidence", 0.0),
                retrieval_count=len(ranked),
                rerank_scores=self._last_rerank_scores,
                cache_hit=False,
                multi_query_used=multi_query_used,
                latency_ms=latency * 1000,
                multi_query_variants=multi_query_variants,
            )
        except Exception as e:
            logger.warning(f"Failed to track retrieval: {e}")

        # ── IT-027: debug bundle ──
        if debug:
            response.debug_bundle = plan.to_dict()

        return response

    def _build_retrieval_profile(self, question: str, intent: str) -> str:
        lowered = question.lower()
        if re.search(r"(第.{0,8}[章节卷篇]|chapter\s+\d+)", lowered) and re.search(r"(讲了什么|内容|概要|概述|summary|what happened)", lowered):
            return "chapter_summary"
        if re.search(r"(关系|联系|之间|多跳|chain|relationship)", lowered):
            return "relation_multi_hop"
        if re.search(r"(氛围|主题|风格|基调|象征|评价|特点|theme|tone)", lowered):
            return "theme"
        if intent == "factual" or re.search(r"(是谁|是什么|在哪|何时|who|what|where|when)", lowered):
            return "entity_factual"
        return "chunk_hybrid"

    def _select_section_ids(self, sparse_sections: Sequence[Any], dense_sections: Sequence[RetrievalResult]) -> list[str]:
        scores: dict[str, float] = {}
        for section in sparse_sections:
            section_id = getattr(section, "section_id", "")
            if section_id:
                scores[section_id] = max(scores.get(section_id, 0.0), float(getattr(section, "score", 0.0)))
        for section in dense_sections:
            if section.section_id:
                scores[section.section_id] = max(scores.get(section.section_id, 0.0), float(section.score))
        return [section_id for section_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[: self._cfg.section_top_k]]

    def _retrieve_section_candidates(self, question: str, scope: Scope, top_k: int):
        if self._scope_chunk_retriever is None:
            return []
        try:
            return self._scope_chunk_retriever.search_sections(question, scope, top_k=top_k)
        except Exception as exc:
            logger.warning(f"section sparse retrieval unavailable: {exc}")
            return []

    def _retrieve_dense_section_results(
        self,
        question: str,
        query_filter: Filter,
        top_k: int,
    ) -> list[RetrievalResult]:
        try:
            query_vector = self._llm.embed(question)
            query_result = self._client.query_points(
                collection_name=self._cfg.qdrant_collection,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.warning(f"section dense retrieval unavailable: {exc}")
            return []

        results: list[RetrievalResult] = []
        for point in query_result.points:
            payload = point.payload or {}
            results.append(
                RetrievalResult(
                    chunk_id=str(point.id),
                    document_id=str(payload.get("document_id", "")),
                    corpus_id=str(payload.get("corpus_id", "")),
                    file_name=str(payload.get("file_name", "unknown")),
                    page_or_loc=str(payload.get("page_or_loc", "loc:unknown")),
                    text=str(payload.get("text", "")),
                    score=float(point.score or 0.0),
                    retrieval_type="dense_section",
                    section_id=str(payload.get("section_id", "")),
                    section_title=str(payload.get("section_title", "")),
                    point_type=str(payload.get("point_type", "section_summary")),
                )
            )
        return results

    def _merge_section_chunk_results(
        self,
        chunks: Sequence[RetrievalResult],
        sparse_sections: Sequence[Any],
        dense_sections: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        section_scores: dict[str, float] = {}
        for section in sparse_sections:
            section_id = getattr(section, "section_id", "")
            if section_id:
                section_scores[section_id] = max(section_scores.get(section_id, 0.0), float(getattr(section, "score", 0.0)))
        for section in dense_sections:
            if section.section_id:
                section_scores[section.section_id] = max(section_scores.get(section.section_id, 0.0), float(section.score))

        merged: list[RetrievalResult] = []
        for chunk in chunks:
            merged.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    corpus_id=chunk.corpus_id,
                    file_name=chunk.file_name,
                    page_or_loc=chunk.page_or_loc,
                    text=chunk.text,
                    score=chunk.score + (section_scores.get(chunk.section_id, 0.0) * 0.35),
                    retrieval_type="section_hybrid",
                    section_id=chunk.section_id,
                    section_title=chunk.section_title,
                    point_type=chunk.point_type,
                )
            )
        return merged

    def _build_grounded_response(
        self,
        *,
        question: str,
        scope: Scope,
        ranked: Sequence[RankedChunk],
        retrieval_profile: str,
        plan: QueryPlan,
    ) -> tuple[QueryResponse, list[str]]:
        if not ranked:
            plan.evidence_sufficient = False
            plan.answer_strategy = "refusal" if not scope.allow_common_knowledge else "no_evidence"
            plan.answer_mode = "refusal"
            plan.evidence_coverage = 0.0
            response = build_refusal_response() if not scope.allow_common_knowledge else build_no_evidence_response()
            response.evidence_coverage = 0.0
            response.answer_mode = plan.answer_mode
            return response, []

        answer_mode = "extractive" if retrieval_profile == "entity_factual" else ("multi_hop_grounded" if retrieval_profile == "relation_multi_hop" else "grounded_summary")
        citation_limit = 2 if answer_mode == "extractive" else min(3, self._cfg.source_sentence_limit)
        selected = list(ranked[: max(citation_limit, 1)])
        evidence_coverage = self._score_evidence_coverage(selected)
        plan.evidence_coverage = evidence_coverage
        plan.answer_mode = answer_mode

        best = selected[0]
        if best.final_score < self._cfg.evidence_min_score or evidence_coverage < self._cfg.evidence_coverage_threshold:
            plan.evidence_sufficient = False
            plan.answer_strategy = "weak_evidence"
            plan.answer_mode = "refusal"
            response = build_refusal_response() if not scope.allow_common_knowledge else build_weak_evidence_response(best)
            response.evidence_coverage = evidence_coverage
            response.answer_mode = plan.answer_mode
            return response, [best.document_id]

        if retrieval_profile == "relation_multi_hop" and len({chunk.section_id or chunk.chunk_id for chunk in selected[:2]}) < 2:
            plan.evidence_sufficient = False
            plan.answer_strategy = "refusal"
            plan.answer_mode = "refusal"
            response = build_refusal_response()
            response.evidence_coverage = evidence_coverage
            response.answer_mode = plan.answer_mode
            return response, list({chunk.document_id for chunk in selected})

        if retrieval_profile in {"chapter_summary", "theme"} and len(selected) < 2:
            plan.evidence_sufficient = False
            plan.answer_strategy = "refusal"
            plan.answer_mode = "refusal"
            response = build_refusal_response()
            response.evidence_coverage = evidence_coverage
            response.answer_mode = plan.answer_mode
            return response, list({chunk.document_id for chunk in selected})

        citations = [
            Citation(
                citation_id=f"c{idx}",
                file_name=chunk.file_name,
                page_or_loc=chunk.page_or_loc,
                chunk_id=chunk.chunk_id,
                snippet=compact_snippet(chunk.text, limit=220),
                section_title=chunk.section_title or None,
            )
            for idx, chunk in enumerate(selected, start=1)
        ]

        if answer_mode == "extractive":
            text = compact_snippet(selected[0].text, limit=180)
            answer_sentences = [
                AnswerSentence(
                    text=text,
                    evidence_type="source",
                    citation_ids=[citations[0].citation_id],
                    confidence=clip_confidence(selected[0].final_score),
                )
            ]
            plan.answer_strategy = "extractive"
        else:
            summary = ""
            try:
                summary = sanitize_summary(self._llm.generate_summary(question, selected))
            except Exception:
                summary = ""
            if summary:
                answer_sentences = [
                    AnswerSentence(
                        text=summary,
                        evidence_type="source",
                        citation_ids=[citation.citation_id for citation in citations],
                        confidence=clip_confidence(selected[0].final_score),
                    )
                ]
                plan.answer_strategy = "llm_summary"
            else:
                answer_sentences = [
                    AnswerSentence(
                        text=compact_snippet(chunk.text, limit=180),
                        evidence_type="source",
                        citation_ids=[citations[idx].citation_id],
                        confidence=clip_confidence(chunk.final_score),
                    )
                    for idx, chunk in enumerate(selected[:2])
                ]
                plan.answer_strategy = "fallback_snippet"

        plan.citation_count = len(citations)
        plan.citation_ids = [citation.citation_id for citation in citations]
        response = QueryResponse(
            answer_sentences=answer_sentences,
            citations=citations,
            evidence_coverage=evidence_coverage,
            answer_mode=plan.answer_mode,
        )
        return response, list({chunk.document_id for chunk in selected})

    def _score_evidence_coverage(self, chunks: Sequence[RankedChunk]) -> float:
        if not chunks:
            return 0.0
        lexical = sum(chunk.lexical_score for chunk in chunks) / len(chunks)
        final = sum(chunk.final_score for chunk in chunks) / len(chunks)
        section_bonus = min(len({chunk.section_id or chunk.chunk_id for chunk in chunks}) / max(len(chunks), 1), 1.0) * 0.2
        return min(1.0, round((lexical * 0.5) + (final * 0.5) + section_bonus, 4))

    def _build_cache_key(
        self,
        question: str,
        scope: Scope,
        *,
        debug: bool,
        retrieval_profile: str,
        revision: str,
    ) -> str:
        scope_str = f"{scope.mode}|{','.join(sorted(scope.corpus_ids))}|{','.join(sorted(scope.document_ids))}|{scope.allow_common_knowledge}"
        return "|".join(
            [
                question.strip(),
                scope_str,
                retrieval_profile,
                revision,
                "debug" if debug else "nodebug",
            ]
        )

    def _retrieve_dense_results(
        self,
        question: str,
        query_filter: Filter,
        top_k: int,
    ) -> list[RetrievalResult]:
        try:
            query_vector = self._llm.embed(question)
            query_result = self._client.query_points(
                collection_name=self._cfg.qdrant_collection,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.warning(f"dense retrieval unavailable, fallback to sparse retrieval: {exc}")
            return []

        dense_results: list[RetrievalResult] = []
        for point in query_result.points:
            payload = point.payload or {}
            text = str(payload.get("text", "")).strip()
            if not text:
                continue
            dense_results.append(
                RetrievalResult(
                    chunk_id=str(point.id),
                    document_id=str(payload.get("document_id", "")),
                    corpus_id=str(payload.get("corpus_id", "")),
                    file_name=str(payload.get("file_name", "unknown")),
                    page_or_loc=str(payload.get("page_or_loc", "loc:unknown")),
                    text=text,
                    score=float(point.score or 0.0),
                    retrieval_type="dense",
                    section_id=str(payload.get("section_id", "")),
                    section_title=str(payload.get("section_title", "")),
                    point_type=str(payload.get("point_type", "chunk")),
                )
            )
        return dense_results

    def _retrieve_sparse_results(
        self,
        question: str,
        scope: Scope,
        top_k: int,
        section_ids: Optional[Sequence[str]] = None,
    ) -> list[RetrievalResult]:
        if self._scope_chunk_retriever is None:
            return []
        try:
            return self._scope_chunk_retriever.search(question, scope, top_k=top_k, section_ids=section_ids)
        except Exception as exc:
            logger.warning(f"sparse retrieval unavailable, fallback to dense retrieval: {exc}")
            return []

    def _rank_retrieval_results(
        self,
        question: str,
        results: Sequence[RetrievalResult],
        top_k: int,
        base_weight: float,
    ) -> list[RankedChunk]:
        if not results:
            return []

        bounded_weight = min(max(base_weight, 0.0), 1.0)
        lexical_weight = 1.0 - bounded_weight
        raw_scores = [float(item.score) for item in results]
        min_score = min(raw_scores)
        max_score = max(raw_scores)
        score_span = max_score - min_score
        question_tokens = tokenize(question)

        ranked: list[RankedChunk] = []
        for item in results:
            base_score = float(item.score)
            if score_span <= 1e-9:
                normalized_score = 1.0 if base_score > 0 else 0.0
            else:
                normalized_score = (base_score - min_score) / score_span
            lexical = lexical_overlap(question_tokens, item.text)
            final_score = (normalized_score * bounded_weight) + (lexical * lexical_weight)
            ranked.append(
                RankedChunk(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    corpus_id=item.corpus_id,
                    file_name=item.file_name,
                    page_or_loc=item.page_or_loc,
                    text=item.text,
                    vector_score=normalized_score,
                    lexical_score=lexical,
                    final_score=final_score,
                    section_id=item.section_id,
                    section_title=item.section_title,
                    point_type=item.point_type,
                )
            )

        ranked.sort(key=lambda chunk: chunk.final_score, reverse=True)
        return ranked[:top_k]

    def _coerce_retrieval_result(self, item: Any) -> RetrievalResult | None:
        if isinstance(item, RetrievalResult):
            return item

        payload = getattr(item, "payload", {}) or {}
        text = getattr(item, "text", "") or payload.get("text", "")
        if not text:
            return None

        chunk_id = getattr(item, "chunk_id", "") or getattr(item, "id", "")
        document_id = getattr(item, "document_id", "") or payload.get("document_id", "")
        corpus_id = getattr(item, "corpus_id", "") or payload.get("corpus_id", "")
        file_name = getattr(item, "file_name", "") or payload.get("file_name", "unknown")
        page_or_loc = getattr(item, "page_or_loc", "") or payload.get("page_or_loc", "loc:unknown")
        section_id = getattr(item, "section_id", "") or payload.get("section_id", "")
        section_title = getattr(item, "section_title", "") or payload.get("section_title", "")
        point_type = getattr(item, "point_type", "") or payload.get("point_type", "chunk")

        return RetrievalResult(
            chunk_id=str(chunk_id),
            document_id=str(document_id),
            corpus_id=str(corpus_id),
            file_name=str(file_name),
            page_or_loc=str(page_or_loc),
            text=str(text),
            score=float(getattr(item, "score", 0.0)),
            retrieval_type=str(getattr(item, "retrieval_type", "dense")),
            section_id=str(section_id),
            section_title=str(section_title),
            point_type=str(point_type),
        )

    def _convert_to_ranked_chunks(self, question: str, points, dense_weight: float) -> list[RankedChunk]:
        lexical_weight = 1.0 - dense_weight
        question_tokens = tokenize(question)
        ranked: list[RankedChunk] = []

        for point in points:
            payload = getattr(point, 'payload', {}) or {}
            text = str(payload.get('text', '')).strip()
            if not text:
                continue

            lexical = lexical_overlap(question_tokens, text)
            vector_score = float(getattr(point, 'score', 0.0))
            final_score = (vector_score * dense_weight) + (lexical * lexical_weight)

            ranked.append(
                RankedChunk(
                    chunk_id=str(getattr(point, 'id', '')),
                    document_id=str(payload.get('document_id', '')),
                    corpus_id=str(payload.get('corpus_id', '')),
                    file_name=str(payload.get('file_name', 'unknown')),
                    page_or_loc=str(payload.get('page_or_loc', 'loc:unknown')),
                    text=text,
                    vector_score=vector_score,
                    lexical_score=lexical,
                    final_score=final_score,
                    section_id=str(payload.get('section_id', '')),
                    section_title=str(payload.get('section_title', '')),
                    point_type=str(payload.get('point_type', 'chunk')),
                )
            )

        ranked.sort(key=lambda item: item.final_score, reverse=True)
        return ranked

    @property
    def cache_stats(self) -> Optional[Dict[str, Any]]:
        if self._query_cache is None:
            return None
        return self._query_cache.stats

    async def query_stream(self, question: str, scope: Scope) -> AsyncGenerator[str, None]:
        """流式查询：逐句发送 answer_sentences
        
        SSE 格式:
        - data: {"type": "sentence", "data": {...}}\n\n
        - data: {"type": "citation", "data": {...}}\n\n
        - data: {"type": "done"}\n\n
        - data: {"type": "error", "message": "..."}}\n\n
        """
        try:
            yield self._format_sse("sentence", {"text": "正在识别问题意图...", "evidence_type": "source", "citation_ids": [], "confidence": 0.5})
            
            # 意图识别步骤
            intent_result = self._intent_classifier.classify_and_get_strategy(question)
            self._last_intent = intent_result
            
            logger.info(
                f"Intent classification result (stream)",
                extra={
                    "extra_fields": {
                        "intent": intent_result["intent"],
                        "confidence": intent_result["confidence"],
                        "reason": intent_result["reason"],
                    }
                },
            )
            
            # 根据意图调整检索策略
            strategy = intent_result["strategy"]
            effective_top_n = strategy.get("top_k", self._cfg.retrieval_top_n)
            effective_rerank_top_k = strategy.get("rerank_top_k", self._cfg.rerank_top_k)
            effective_dense_weight = strategy.get("dense_weight", self._cfg.hybrid_dense_weight)
            
            yield self._format_sse("sentence", {"text": f"正在基于意图 [{intent_result['intent']}] 检索相关知识...", "evidence_type": "source", "citation_ids": [], "confidence": 0.5})
            
            query_filter = build_scope_filter(scope)
            dense_results = self._retrieve_dense_results(question, query_filter, effective_top_n)
            sparse_results = self._retrieve_sparse_results(question, scope, effective_top_n)
            if dense_results and sparse_results:
                retrieval_results = self._hybrid_retriever.hybrid_search(
                    dense_results,
                    sparse_results,
                    top_k=max(effective_top_n, effective_rerank_top_k),
                )
            elif dense_results:
                retrieval_results = dense_results
            else:
                retrieval_results = sparse_results

            ranked = self._rank_retrieval_results(
                question,
                retrieval_results,
                effective_rerank_top_k,
                effective_dense_weight,
            )
            if not ranked:
                response = build_no_evidence_response()
                for sentence in response.answer_sentences:
                    yield self._format_sse("sentence", sentence.model_dump())
                yield self._format_sse("done")
                return

            best = ranked[0]
            if best.final_score < self._cfg.evidence_min_score:
                response = build_weak_evidence_response(best)
                for sentence in response.answer_sentences:
                    yield self._format_sse("sentence", sentence.model_dump())
                for citation in response.citations:
                    yield self._format_sse("citation", citation.model_dump())
                yield self._format_sse("done")
                return

            source_limit = min(self._cfg.source_sentence_limit, len(ranked))
            selected = ranked[:source_limit]

            citations: list[Citation] = []
            for idx, chunk in enumerate(selected, start=1):
                citation_id = f"c{idx}"
                citations.append(
                    Citation(
                        citation_id=citation_id,
                        file_name=chunk.file_name,
                        page_or_loc=chunk.page_or_loc,
                        chunk_id=chunk.chunk_id,
                        snippet=compact_snippet(chunk.text, limit=220),
                    )
                )

            for citation in citations:
                yield self._format_sse("citation", citation.model_dump())

            answer_sentences: list[AnswerSentence] = []
            summary = ""
            try:
                summary = self._llm.generate_summary(question, selected)
            except Exception:
                summary = ""
            summary = sanitize_summary(summary)
            if summary:
                sentence = AnswerSentence(
                    text=summary,
                    evidence_type="source",
                    citation_ids=[item.citation_id for item in citations],
                    confidence=clip_confidence(best.final_score),
                )
                answer_sentences.append(sentence)
                yield self._format_sse("sentence", sentence.model_dump())
            else:
                fallback_selected = selected[: min(2, len(selected))]
                for idx, chunk in enumerate(fallback_selected, start=1):
                    citation_id = f"c{idx}"
                    snippet = compact_snippet(chunk.text, limit=220)
                    sentence = AnswerSentence(
                        text=f"根据资料可知：{snippet}",
                        evidence_type="source",
                        citation_ids=[citation_id],
                        confidence=clip_confidence(chunk.final_score),
                    )
                    answer_sentences.append(sentence)
                    yield self._format_sse("sentence", sentence.model_dump())

            max_common = max_common_sentences(len(answer_sentences), self._cfg.common_knowledge_max_ratio)
            if scope.allow_common_knowledge and max_common > 0:
                sentence = AnswerSentence(
                    text=f"{COMMON_KNOWLEDGE_PREFIX}以下内容为模型补充推断，请结合原文证据核验。",
                    evidence_type="common_knowledge",
                    citation_ids=[],
                    confidence=0.3,
                )
                answer_sentences.append(sentence)
                yield self._format_sse("sentence", sentence.model_dump())

            yield self._format_sse("done")

        except Exception as exc:
            yield self._format_sse("error", None, str(exc))

    async def query_stream(self, question: str, scope: Scope) -> AsyncGenerator[str, None]:
        """流式查询：复用标准 query 路径，逐条输出 citation 与 answer_sentences。"""
        try:
            response = self.query(question, scope, debug=False)
            for citation in response.citations:
                yield self._format_sse("citation", citation.model_dump())
            for sentence in response.answer_sentences:
                yield self._format_sse("sentence", sentence.model_dump())
            yield self._format_sse("done")
        except Exception as exc:
            yield self._format_sse("error", None, str(exc))

    def _format_sse(self, event_type: str, data: Any = None, error_message: str = None) -> str:
        """格式化 SSE 消息"""
        payload: dict[str, Any] = {"type": event_type}
        if data is not None:
            payload["data"] = data
        if error_message is not None:
            payload["message"] = error_message
        return f"data: {json.dumps(payload)}\n\n"


def getenv_int(name: str, fallback: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def getenv_float(name: str, fallback: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def build_service_config() -> ServiceConfig:
    llm_timeout_seconds = getenv_float("LLM_TIMEOUT_SECONDS", 30)
    if llm_timeout_seconds <= 0:
        llm_timeout_seconds = 30

    llm_max_retries = getenv_int("LLM_MAX_RETRIES", 2)
    if llm_max_retries < 0:
        llm_max_retries = 0

    llm_retry_delay_milliseconds = getenv_int("LLM_RETRY_DELAY_MILLISECONDS", 600)
    if llm_retry_delay_milliseconds < 0:
        llm_retry_delay_milliseconds = 0

    hybrid_dense_weight = getenv_float("HYBRID_SEARCH_DENSE_WEIGHT", 0.7)
    if not (0.0 <= hybrid_dense_weight <= 1.0):
        hybrid_dense_weight = 0.7

    hybrid_sparse_weight = getenv_float("HYBRID_SEARCH_SPARSE_WEIGHT", 0.3)
    if not (0.0 <= hybrid_sparse_weight <= 1.0):
        hybrid_sparse_weight = 0.3

    weight_sum = hybrid_dense_weight + hybrid_sparse_weight
    if weight_sum <= 0:
        hybrid_dense_weight = 0.7
        hybrid_sparse_weight = 0.3
    else:
        hybrid_dense_weight = hybrid_dense_weight / weight_sum
        hybrid_sparse_weight = hybrid_sparse_weight / weight_sum

    reranker_model = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2").strip()
    if not reranker_model:
        reranker_model = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    query_cache_enabled_raw = os.getenv("QUERY_CACHE_ENABLED", "true").strip().lower()
    query_cache_enabled = query_cache_enabled_raw in ("true", "1", "yes", "on")

    multi_query_enabled_raw = os.getenv("MULTI_QUERY_ENABLED", "false").strip().lower()
    multi_query_enabled = multi_query_enabled_raw in ("true", "1", "yes", "on")

    multi_query_max_variants = getenv_int("MULTI_QUERY_MAX_VARIANTS", 3)
    if multi_query_max_variants < 1:
        multi_query_max_variants = 3

    multi_query_timeout_ms = getenv_int("MULTI_QUERY_TIMEOUT_MS", 500)
    if multi_query_timeout_ms < 100:
        multi_query_timeout_ms = 500

    sparse_retrieval_enabled_raw = os.getenv("SPARSE_RETRIEVAL_ENABLED", "true").strip().lower()
    sparse_retrieval_enabled = sparse_retrieval_enabled_raw in ("true", "1", "yes", "on")
    section_top_k = max(getenv_int("SECTION_TOP_K", 8), 1)
    section_expand_chunk_limit = max(getenv_int("SECTION_EXPAND_CHUNK_LIMIT", 6), 1)
    evidence_coverage_threshold = getenv_float("RAG_EVIDENCE_COVERAGE_THRESHOLD", 0.45)

    return ServiceConfig(
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgres://rag:rag@postgres:5432/rag?sslmode=disable"),
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "rag_chunks"),
        embedding_dim=max(getenv_int("EMBEDDING_DIM", 0), 0),
        retrieval_top_n=max(getenv_int("RAG_RETRIEVAL_TOP_N", 24), 1),
        rerank_top_k=max(getenv_int("RAG_RERANK_TOP_K", 8), 1),
        source_sentence_limit=max(getenv_int("RAG_SOURCE_SENTENCE_LIMIT", 6), 1),
        evidence_min_score=getenv_float("RAG_EVIDENCE_MIN_SCORE", 0.05),
        common_knowledge_max_ratio=getenv_float("RAG_COMMON_KNOWLEDGE_MAX_RATIO", 0.15),
        embedding_provider=(os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower() or "openai"),
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL", "").strip(),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "").strip(),
        chat_provider=(os.getenv("CHAT_PROVIDER", "openai").strip().lower() or "openai"),
        chat_base_url=os.getenv("CHAT_BASE_URL", "").strip(),
        chat_api_key=os.getenv("CHAT_API_KEY", "").strip(),
        chat_model=os.getenv("CHAT_MODEL", "").strip(),
        llm_timeout_seconds=llm_timeout_seconds,
        llm_max_retries=llm_max_retries,
        llm_retry_delay_milliseconds=llm_retry_delay_milliseconds,
        hybrid_dense_weight=hybrid_dense_weight,
        hybrid_sparse_weight=hybrid_sparse_weight,
        reranker_model=reranker_model,
        query_cache_enabled=query_cache_enabled,
        query_cache_ttl_hours=max(getenv_int("QUERY_CACHE_TTL_HOURS", 24), 1),
        query_cache_max_size=max(getenv_int("QUERY_CACHE_MAX_SIZE", 10000), 1),
        sparse_retrieval_enabled=sparse_retrieval_enabled,
        sparse_cache_ttl_seconds=max(getenv_int("SPARSE_CACHE_TTL_SECONDS", 600), 1),
        sparse_cache_max_scopes=max(getenv_int("SPARSE_CACHE_MAX_SCOPES", 16), 1),
        section_top_k=section_top_k,
        section_expand_chunk_limit=section_expand_chunk_limit,
        evidence_coverage_threshold=evidence_coverage_threshold,
        multi_query_enabled=multi_query_enabled,
        multi_query_max_variants=multi_query_max_variants,
        multi_query_timeout_ms=multi_query_timeout_ms,
    )


def _validate_uuid(raw: str, field_name: str) -> None:
    try:
        UUID(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains invalid uuid: {raw}") from exc


def hash_embedding(text: str, dim: int) -> List[float]:
    if dim <= 0:
        dim = DEFAULT_FALLBACK_EMBEDDING_DIM
    seed = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    values: List[float] = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for item in block:
            values.append((item / 127.5) - 1.0)
            if len(values) >= dim:
                break
        counter += 1

    norm = sum(value * value for value in values) ** 0.5
    if norm == 0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _normalize_vector(values: List[float]) -> List[float]:
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0:
        return values
    return [value / norm for value in values]


def build_scope_filter(scope: Scope, point_type: Optional[str] = None) -> Filter:
    must: list[FieldCondition] = [
        FieldCondition(key="corpus_id", match=MatchAny(any=scope.corpus_ids)),
    ]
    if scope.document_ids:
        must.append(FieldCondition(key="document_id", match=MatchAny(any=scope.document_ids)))
    if point_type:
        must.append(FieldCondition(key="point_type", match=MatchAny(any=[point_type])))
    return Filter(must=must)


def rerank_points(
    question: str,
    points: Sequence[ScoredPoint],
    top_k: int,
    dense_weight: float = 0.7,
) -> list[RankedChunk]:
    """
    重排序检索结果
    
    Args:
        question: 用户问题
        points: Qdrant 返回的检索结果
        top_k: 返回前 k 个结果
        dense_weight: 向量检索权重（默认 0.7），词法检索权重为 1.0 - dense_weight
    """
    question_tokens = tokenize(question)
    ranked: list[RankedChunk] = []
    lexical_weight = 1.0 - dense_weight

    for point in points:
        payload = point.payload or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            continue

        lexical = lexical_overlap(question_tokens, text)
        vector_score = float(point.score or 0.0)
        final_score = (vector_score * dense_weight) + (lexical * lexical_weight)

        ranked.append(
            RankedChunk(
                chunk_id=str(point.id),
                document_id=str(payload.get("document_id", "")),
                corpus_id=str(payload.get("corpus_id", "")),
                file_name=str(payload.get("file_name", "unknown")),
                page_or_loc=str(payload.get("page_or_loc", "loc:unknown")),
                text=text,
                vector_score=vector_score,
                lexical_score=lexical,
                final_score=final_score,
            )
        )

    ranked.sort(key=lambda item: item.final_score, reverse=True)
    return ranked[:top_k]


def tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


def lexical_overlap(question_tokens: set[str], source_text: str) -> float:
    if not question_tokens:
        return 0.0

    source_tokens = tokenize(source_text)
    if not source_tokens:
        return 0.0

    matched = sum(1 for token in question_tokens if token in source_tokens)
    return matched / float(len(question_tokens))


def compact_snippet(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def sanitize_summary(summary: str) -> str:
    cleaned = " ".join(summary.split()).strip()
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if EVIDENCE_DUMP_RE.search(cleaned):
        return ""
    if "file=" in lowered and "loc=" in lowered:
        return ""
    if "text:" in lowered and cleaned.count("[") >= 1:
        return ""
    return cleaned


def clip_confidence(score: float) -> float:
    if score < 0.05:
        return 0.05
    if score > 0.99:
        return 0.99
    return round(score, 4)


def max_common_sentences(source_count: int, ratio: float) -> int:
    if source_count <= 0 or ratio <= 0 or ratio >= 1:
        return 0
    return int((ratio * source_count) / (1 - ratio))


def build_no_evidence_response() -> QueryResponse:
    return QueryResponse(
        answer_sentences=[
            AnswerSentence(
                text=f"{COMMON_KNOWLEDGE_PREFIX}未检索到可用文档证据，请调整提问范围或补充资料。",
                evidence_type="common_knowledge",
                citation_ids=[],
                confidence=0.0,
            )
        ],
        citations=[],
        evidence_coverage=0.0,
        answer_mode="no_evidence",
    )


def build_weak_evidence_response(best: RankedChunk) -> QueryResponse:
    citation = Citation(
        citation_id="c1",
        file_name=best.file_name,
        page_or_loc=best.page_or_loc,
        chunk_id=best.chunk_id,
        snippet=compact_snippet(best.text, limit=220),
        section_title=best.section_title or None,
    )

    sentence = AnswerSentence(
        text=f"证据相关性偏低，建议优先查看《{best.file_name}》{best.page_or_loc}原文后再确认结论。",
        evidence_type="source",
        citation_ids=[citation.citation_id],
        confidence=0.2,
    )
    return QueryResponse(
        answer_sentences=[sentence],
        citations=[citation],
        evidence_coverage=0.0,
        answer_mode="weak_evidence",
    )


def build_refusal_response() -> QueryResponse:
    """IT-026: 严格拒答——当 allow_common_knowledge=false 且无证据时。"""
    return QueryResponse(
        answer_sentences=[
            AnswerSentence(
                text="抱歉，在当前资料范围内未找到与问题相关的可靠证据，无法作答。请尝试扩大检索范围或补充相关文档。",
                evidence_type="common_knowledge",
                citation_ids=[],
                confidence=0.0,
            )
        ],
        citations=[],
        evidence_coverage=0.0,
        answer_mode="refusal",
    )


def build_engine() -> RAGEngine:
    return RAGEngine(build_service_config())


def _describe_provider_status(provider: str, model: str, api_key: str, base_url: str) -> str:
    normalized = provider.strip().lower()
    if not model.strip():
        return "not_configured"
    if not base_url.strip():
        return "misconfigured"
    if _provider_requires_api_key(normalized) and not api_key.strip():
        return "not_configured"
    return "configured"


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    start = time.time()
    try:
        app.state.engine = build_engine()
        logger.info(
            "RAG engine warmed up during startup",
            extra={"extra_fields": {"duration_ms": round((time.time() - start) * 1000, 2)}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"RAG engine warmup failed, falling back to lazy initialization: {exc}",
            extra={"extra_fields": {"duration_ms": round((time.time() - start) * 1000, 2)}},
        )
    try:
        yield
    finally:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            engine.close()


app = FastAPI(title="py-rag-service", version="0.3.0", lifespan=app_lifespan)


def get_or_create_engine() -> RAGEngine:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        app.state.engine = build_engine()
    return app.state.engine


@app.exception_handler(RAGServiceError)
async def rag_service_error_handler(request: Request, exc: RAGServiceError):
    """统一处理 RAG 服务自定义异常"""
    logger.error(
        f"RAG service error: {exc.code}",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "extra_fields": {
                "error_code": exc.code,
                "error_detail": exc.detail,
                "path": request.url.path,
                **exc.extra_info,
            },
        },
        exc_info=True if exc.status_code >= 500 else False,
    )
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """统一处理所有未捕获的异常"""
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "extra_fields": {
                "error_type": type(exc).__name__,
                "path": request.url.path,
                "method": request.method,
            },
        },
        exc_info=True,
    )
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "code": "INTERNAL_ERROR",
        },
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有 HTTP 请求的日志"""
    import time
    from uuid import uuid4

    request_id = str(uuid4())
    start_time = time.time()

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000

    logger.info(
        f"{request.method} {request.url.path} completed",
        extra={
            "request_id": request_id,
            "duration_ms": round(duration_ms, 2),
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "client": request.client.host if request.client else "unknown",
            },
        },
    )

    return response


@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """
    请求超时中间件
    默认超时 60 秒，可通过环境变量 RAG_REQUEST_TIMEOUT 调整
    """
    import asyncio
    from datetime import timedelta
    
    timeout_seconds = int(os.getenv("RAG_REQUEST_TIMEOUT", "60"))
    
    try:
        # 使用 asyncio.wait_for 实现超时控制
        response = await asyncio.wait_for(call_next(request), timeout=timeout_seconds)
        return response
    except asyncio.TimeoutError:
        logger.error(
            f"Request timeout after {timeout_seconds}s",
            extra={
                "extra_fields": {
                    "path": request.url.path,
                    "method": request.method,
                    "timeout_seconds": timeout_seconds,
                },
            },
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=504,  # Gateway Timeout
            content={
                "error": "Request timeout",
                "code": "REQUEST_TIMEOUT",
                "detail": f"Request exceeded {timeout_seconds}s timeout",
            },
        )


@app.get("/healthz")
def healthz(depth: str = Query(default="basic", description="health depth: basic or full")) -> dict:
    if depth == "basic":
        logger.debug("Basic health check requested")
        return {"status": "ok", "service": "py-rag-service"}

    logger.info("Full health check requested")
    checks: dict[str, str] = {}
    overall_status = "ok"

    try:
        cfg = build_service_config()
        qdrant_client = QdrantClient(url=cfg.qdrant_url, timeout=2)
        qdrant_client.get_collections()
        checks["qdrant"] = "ok"
        qdrant_client.close()
    except Exception as e:
        checks["qdrant"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Health check: Qdrant connection failed: {e}")

    try:
        cfg = build_service_config()
        checks["embedding_api"] = _describe_provider_status(
            cfg.embedding_provider,
            cfg.embedding_model,
            cfg.embedding_api_key,
            _resolve_provider_base_url(
                cfg.embedding_provider,
                cfg.embedding_base_url,
                EMBEDDING_PROVIDER_BASE_URLS,
            ),
        )
        checks["chat_api"] = _describe_provider_status(
            cfg.chat_provider,
            cfg.chat_model,
            cfg.chat_api_key,
            _resolve_provider_base_url(
                cfg.chat_provider,
                cfg.chat_base_url,
                CHAT_PROVIDER_BASE_URLS,
            ),
        )
    except Exception as e:
        checks["embedding_api"] = "unhealthy"
        checks["chat_api"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Health check: provider config check failed: {e}")

    try:
        cache_host = os.getenv("QUERY_CACHE_REDIS_HOST")
        if cache_host:
            import redis

            r = redis.Redis(host=cache_host, port=6379, db=0, socket_timeout=2)
            r.ping()
            checks["redis_cache"] = "ok"
        else:
            checks["redis_cache"] = "not_configured"
    except Exception as e:
        checks["redis_cache"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Health check: Redis cache check failed: {e}")

    return {
        "status": overall_status,
        "service": "py-rag-service",
        "checks": checks,
    }


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/metrics/cache")
def cache_metrics() -> dict:
    if not hasattr(app.state, "engine"):
        return {"enabled": False, "available": False}
    
    engine = app.state.engine
    if not hasattr(engine, "cache_stats") or engine.cache_stats is None:
        return {"enabled": False, "available": False}
    
    stats = engine.cache_stats
    return {
        "enabled": True,
        "available": True,
        "size": stats.get("size", 0),
        "max_size": stats.get("max_size", 0),
        "hits": stats.get("hits", 0),
        "misses": stats.get("misses", 0),
        "hit_rate": stats.get("hit_rate", 0.0),
    }


@app.get("/metrics/retrieval-quality")
def retrieval_quality_stats(days: int = Query(default=7, description="统计天数")):
    """获取检索质量统计"""
    try:
        stats = get_retrieval_quality_stats(days=days)
        return {
            "success": True,
            "days": days,
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Failed to get retrieval quality stats: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@app.get("/metrics/summary")
def metrics_summary():
    """IT-038: 指标摘要接口——前端友好的聚合指标。"""
    # 缓存指标
    cache_info = {"available": False}
    try:
        if hasattr(app.state, "engine"):
            stats = app.state.engine.cache_stats()
            cache_info = {
                "available": True,
                "size": stats.get("size", 0),
                "max_size": stats.get("max_size", 0),
                "hit_rate": stats.get("hit_rate", 0.0),
            }
    except Exception:
        pass

    # 检索质量指标
    quality_info = {}
    try:
        quality_info = get_retrieval_quality_stats(days=7)
    except Exception:
        pass

    return {
        "cache": cache_info,
        "retrieval_quality_7d": quality_info,
        "service": "py-rag-service",
    }


@app.get("/metrics/retrieval-quality/report")
def retrieval_quality_report():
    """导出检索质量报告"""
    try:
        from .retrieval_tracker import get_tracker
        tracker = get_tracker()
        report_path = tracker.export_report()
        return {
            "success": True,
            "report_path": report_path,
        }
    except Exception as e:
        logger.error(f"Failed to export retrieval quality report: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@app.post("/v1/rag/query", response_model=QueryResponse)
def rag_query(
    payload: QueryRequest,
    debug: bool = Query(default=False, description="启用 debug bundle，在响应中附加检索决策详情"),
) -> QueryResponse:
    question = payload.question.strip()
    if not question:
        logger.warning("RAG query with empty question")
        raise ValidationError("question must not be blank")

    # IT-039: Prompt injection 防护
    is_valid, error_msg, guardrail_result = validate_question(question)
    if not is_valid:
        logger.warning(
            f"RAG query blocked by guardrails",
            extra={
                "extra_fields": {
                    "reason": error_msg,
                    "risk_level": guardrail_result.risk_level if guardrail_result else "unknown",
                    "matched_rules": guardrail_result.matched_rules if guardrail_result else [],
                }
            },
        )
        return QueryResponse(
            answer_sentences=[
                AnswerSentence(
                    text="抱歉，您的输入包含不安全的内容模式，无法处理。请重新表述您的问题。",
                    evidence_type="common_knowledge",
                    citation_ids=[],
                    confidence=0.0,
                )
            ],
            citations=[],
        )

    try:
        engine = get_or_create_engine()
        logger.info(
            f"Processing RAG query",
            extra={
                "extra_fields": {
                    "question_length": len(question),
                    "scope_mode": payload.scope.mode,
                    "corpus_count": len(payload.scope.corpus_ids),
                    "debug": debug,
                }
            },
        )
        result = engine.query(question, payload.scope, debug=debug)
        logger.info(
            "RAG query completed",
            extra={
                "extra_fields": {
                    "answer_sentences": len(result.answer_sentences),
                    "citations": len(result.citations),
                    "has_debug_bundle": result.debug_bundle is not None,
                }
            },
        )
        return result
    except Exception as exc:
        logger.error(
            f"RAG query failed: {exc}",
            extra={
                "extra_fields": {
                    "error_type": type(exc).__name__,
                }
            },
            exc_info=True,
        )
        # 返回友好的错误信息，而不是抛出异常
        return QueryResponse(
            answer_sentences=[
                AnswerSentence(
                    text=f"{COMMON_KNOWLEDGE_PREFIX}当前检索服务暂不可用，请稍后重试。",
                    evidence_type="common_knowledge",
                    citation_ids=[],
                    confidence=0.1,
                )
            ],
            citations=[],
        )


@app.get("/v1/rag/query/stream")
async def rag_query_stream(
    question: str = Query(..., min_length=1, max_length=8000, description="查询问题"),
    scope_json: str = Query(..., description="JSON encoded Scope object"),
) -> StreamingResponse:
    """SSE 流式查询端点
    
    使用方法:
    curl -N "http://localhost:8000/v1/rag/query/stream?question=测试&scope_json={...}"
    
    SSE 事件格式:
    - data: {"type": "sentence", "data": {...}}  答案句子
    - data: {"type": "citation", "data": {...}}  引用文献
    - data: {"type": "done"}                     流式结束
    - data: {"type": "error", "message": "..."}  错误信息
    """
    import asyncio
    from anyio import BrokenResourceError
    
    try:
        scope_dict = json.loads(scope_json)
        scope = Scope(**scope_dict)
    except (json.JSONDecodeError, ValueError) as exc:
        async def error_stream() -> AsyncGenerator[str, None]:
            yield f'data: {{"type": "error", "message": "Invalid scope_json: {str(exc)}"}}\n\n'
            yield 'data: {"type": "done"}\n\n'
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    engine = get_or_create_engine()
    
    async def generate() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流"""
        try:
            async for event in engine.query_stream(question.strip(), scope):
                yield event
                await asyncio.sleep(0)
        except BrokenResourceError:
            pass
        except Exception as exc:
            yield f'data: {{"type": "error", "message": "{str(exc)}"}}\n\n'
            yield 'data: {"type": "done"}\n\n'
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/rag/query/stream")
async def rag_query_stream_post(payload: StreamQueryRequest) -> StreamingResponse:
    """SSE 流式查询端点（POST 方式）
    
    使用方法:
    curl -N -X POST "http://localhost:8000/v1/rag/query/stream" \\
      -H "Content-Type: application/json" \\
      -d '{"question": "测试", "scope": {...}}'
    
    SSE 事件格式:
    - data: {"type": "sentence", "data": {...}}  答案句子
    - data: {"type": "citation", "data": {...}}  引用文献
    - data: {"type": "done"}                     流式结束
    - data: {"type": "error", "message": "..."}  错误信息
    """
    import asyncio
    from anyio import BrokenResourceError
    
    question = payload.question.strip()
    if not question:
        async def error_stream() -> AsyncGenerator[str, None]:
            yield 'data: {"type": "error", "message": "question must not be blank"}\n\n'
            yield 'data: {"type": "done"}\n\n'
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    engine = get_or_create_engine()
    
    async def generate() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流"""
        try:
            async for event in engine.query_stream(question, payload.scope):
                yield event
                await asyncio.sleep(0)
        except BrokenResourceError:
            pass
        except Exception as exc:
            yield f'data: {{"type": "error", "message": "{str(exc)}"}}\n\n'
            yield 'data: {"type": "done"}\n\n'
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
