from __future__ import annotations

import hashlib
import os
import time
from typing import List, Sequence

import httpx

from worker.config import WorkerConfig


DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434/v1"
DEFAULT_FALLBACK_EMBEDDING_DIM = 256
PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
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
    "ollama": DEFAULT_OLLAMA_BASE_URL,
}

API_KEY_OPTIONAL_PROVIDERS = {"custom", "ollama"}
DIMENSION_AWARE_PROVIDERS = {"openai", "qwen"}


def resolve_provider_base_url(provider: str, explicit_base_url: str) -> str:
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
        PROVIDER_BASE_URLS.get(normalized, PROVIDER_BASE_URLS["openai"]),
    )


def provider_requires_api_key(provider: str) -> bool:
    return provider.strip().lower() not in API_KEY_OPTIONAL_PROVIDERS


def _normalize_provider_base_url(provider: str, base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return ""
    if provider == "ollama" and not normalized.endswith("/v1"):
        return f"{normalized}/v1"
    return normalized


class EmbeddingClient:
    def __init__(self, cfg: WorkerConfig):
        self._cfg = cfg
        self._base_url = resolve_provider_base_url(cfg.embedding_provider, cfg.embedding_base_url)
        self._client = httpx.Client(timeout=cfg.embedding_timeout_seconds)

    @property
    def enabled(self) -> bool:
        has_auth = bool(self._cfg.embedding_api_key) or not provider_requires_api_key(self._cfg.embedding_provider)
        return bool(has_auth and self._cfg.embedding_model and self._base_url)

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        normalized = [text.strip() for text in texts]
        if not normalized:
            raise ValueError("texts must not be empty")
        if any(not text for text in normalized):
            raise ValueError("texts must not contain empty items")

        if not self.enabled:
            return [hash_embedding(text, self._cfg.embedding_dim) for text in normalized]

        provider = self._cfg.embedding_provider
        if provider == "ollama":
            return self._request_ollama_embeddings(normalized)
        if provider == "gemini":
            return [self._request_gemini_embedding(text) for text in normalized]

        return self._request_openai_compatible_embeddings(normalized)

    def _request_ollama_embeddings(self, texts: Sequence[str]) -> List[List[float]]:
        url = _to_ollama_embed_url(self._base_url)
        payload: dict[str, object] = {
            "model": self._cfg.embedding_model,
            "input": list(texts),
            "truncate": True,
        }
        if self._cfg.embedding_dim > 0:
            payload["dimensions"] = self._cfg.embedding_dim
        if self._cfg.embedding_keep_alive:
            payload["keep_alive"] = self._cfg.embedding_keep_alive

        data = self._post_json(url, {"Content-Type": "application/json"}, payload)
        vectors_raw = data.get("embeddings")
        if not isinstance(vectors_raw, list) or len(vectors_raw) != len(texts):
            raise RuntimeError("embedding response format invalid")

        return [_coerce_vector(vector_raw) for vector_raw in vectors_raw]

    def _request_openai_compatible_embeddings(self, texts: Sequence[str]) -> List[List[float]]:
        url = f"{self._base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
        }
        if self._cfg.embedding_api_key:
            headers["Authorization"] = f"Bearer {self._cfg.embedding_api_key}"
        payload: dict[str, object] = {
            "model": self._cfg.embedding_model,
            "input": list(texts),
        }
        if self._cfg.embedding_provider in DIMENSION_AWARE_PROVIDERS and self._cfg.embedding_dim > 0:
            payload["dimensions"] = self._cfg.embedding_dim

        data = self._post_json(url, headers, payload)
        items_raw = data.get("data")
        if not isinstance(items_raw, list) or len(items_raw) != len(texts):
            raise RuntimeError("embedding response format invalid")

        ordered_items = sorted(
            items_raw,
            key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0,
        )
        vectors: List[List[float]] = []
        for item in ordered_items:
            if not isinstance(item, dict):
                raise RuntimeError("embedding response format invalid")
            vectors.append(_coerce_vector(item.get("embedding")))
        return vectors

    def _request_gemini_embedding(self, text: str) -> List[float]:
        model = self._cfg.embedding_model.strip()
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = f"{self._base_url}/{model_path}:embedContent"
        headers = {
            "x-goog-api-key": self._cfg.embedding_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_path,
            "content": {
                "parts": [{"text": text}],
            },
            "task_type": "RETRIEVAL_DOCUMENT",
        }
        if self._cfg.embedding_dim > 0:
            payload["output_dimensionality"] = self._cfg.embedding_dim

        data = self._post_json(url, headers, payload)
        vector_raw = None

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

    def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, object]) -> dict[str, object]:
        attempts = self._cfg.llm_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                resp = self._client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    self._sleep_between_retries()
                    continue
                raise RuntimeError(f"embedding request failed: {exc}") from exc

            if resp.status_code >= 500 and attempt < attempts:
                self._sleep_between_retries()
                continue

            if resp.status_code >= 400:
                body = (resp.text or "").strip().replace("\n", " ")
                if len(body) > 300:
                    body = body[:300] + "..."
                raise RuntimeError(f"embedding request rejected: status={resp.status_code} body={body}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError("embedding response format invalid") from exc
            if not isinstance(data, dict):
                raise RuntimeError("embedding response format invalid")
            return data

        raise RuntimeError("embedding request exhausted retries")

    def _sleep_between_retries(self) -> None:
        delay_ms = self._cfg.llm_retry_delay_milliseconds
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)


def hash_embedding(text: str, dim: int) -> List[float]:
    # Deterministic fallback embedding when no external model is configured.
    if dim <= 0:
        dim = DEFAULT_FALLBACK_EMBEDDING_DIM
    seed = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    values: List[float] = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for b in block:
            values.append((b / 127.5) - 1.0)
            if len(values) >= dim:
                break
        counter += 1

    norm = sum(v * v for v in values) ** 0.5
    if norm == 0:
        return [0.0 for _ in values]
    return [v / norm for v in values]


def _normalize_vector(values: List[float]) -> List[float]:
    norm = sum(v * v for v in values) ** 0.5
    if norm == 0:
        return values
    return [v / norm for v in values]


def _to_ollama_embed_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3] + "/api/embed"
    return normalized + "/api/embed"


def _coerce_vector(vector_raw: object) -> List[float]:
    if not isinstance(vector_raw, list) or len(vector_raw) == 0:
        raise RuntimeError("embedding response contains empty vector")

    try:
        return [float(v) for v in vector_raw]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("embedding response contains non-numeric vector values") from exc
