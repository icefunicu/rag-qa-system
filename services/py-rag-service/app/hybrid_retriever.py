from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Sequence

from rank_bm25 import BM25Okapi

from app.config import RAGOptimizationConfig
from app.jieba_compat import load_jieba


jieba = load_jieba()


@dataclass(frozen=True)
class RetrievalResult:
    """检索结果"""

    chunk_id: str
    document_id: str
    corpus_id: str
    file_name: str
    page_or_loc: str
    text: str
    score: float
    retrieval_type: str  # "dense", "sparse", or "hybrid"
    section_id: str = ""
    section_title: str = ""
    point_type: str = "chunk"


class HybridRetriever:
    """混合检索器：结合稠密向量检索和稀疏 BM25 检索"""

    def __init__(
        self,
        dense_weight: float | None = None,
        sparse_weight: float | None = None,
        config: RAGOptimizationConfig | None = None,
    ):
        """
        初始化混合检索器

        Args:
            dense_weight: 稠密检索权重，默认从配置加载 (0.7)
            sparse_weight: 稀疏检索权重，默认从配置加载 (0.3)
            config: 配置对象，若提供则从中读取权重

        Raises:
            ValueError: 当权重和不等于 1.0 时
        """
        if config is not None:
            self._dense_weight = config.hybrid_search_dense_weight
            self._sparse_weight = config.hybrid_search_sparse_weight
        else:
            if dense_weight is None:
                dense_weight = 0.7
            if sparse_weight is None:
                sparse_weight = 0.3
            
            if abs(dense_weight + sparse_weight - 1.0) > 0.01:
                raise ValueError("dense_weight + sparse_weight must equal 1.0")
            
            self._dense_weight = dense_weight
            self._sparse_weight = sparse_weight
        
        self._bm25_index: BM25Okapi | None = None
        self._documents: List[Dict] = []

    def build_bm25_index(self, documents: Sequence[Dict]) -> None:
        """
        构建 BM25 索引

        Args:
            documents: 文档列表，每个文档包含 text 字段
        """
        self._documents = list(documents)
        texts = [doc.get("text", "") for doc in self._documents]
        tokenized_docs = [self._tokenize(text) for text in texts]
        self._bm25_index = BM25Okapi(tokenized_docs)

    def sparse_search(
        self, query: str, top_k: int = 24
    ) -> List[RetrievalResult]:
        """
        执行稀疏检索（BM25）

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        if self._bm25_index is None:
            return []

        query_tokens = self._tokenize(query)
        scores = self._bm25_index.get_scores(query_tokens)

        results = []
        for idx, score in enumerate(scores):
            if score > 0:
                doc = self._documents[idx]
                results.append(
                    RetrievalResult(
                        chunk_id=doc.get("chunk_id", ""),
                        document_id=doc.get("document_id", ""),
                        corpus_id=doc.get("corpus_id", ""),
                        file_name=doc.get("file_name", "unknown"),
                        page_or_loc=doc.get("page_or_loc", "loc:unknown"),
                        text=doc.get("text", ""),
                        score=float(score),
                        retrieval_type="sparse",
                        section_id=doc.get("section_id", ""),
                        section_title=doc.get("section_title", ""),
                        point_type=doc.get("point_type", "chunk"),
                    )
                )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def dense_search(
        self,
        qdrant_client,
        collection_name: str,
        query_vector: List[float],
        query_filter=None,
        top_k: int = 24,
    ) -> List[RetrievalResult]:
        """
        执行稠密检索（向量相似度）

        Args:
            qdrant_client: Qdrant 客户端
            collection_name: 集合名称
            query_vector: 查询向量
            query_filter: Qdrant 过滤器
            top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        query_result = qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        results = []
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
                    retrieval_type="dense",
                    section_id=str(payload.get("section_id", "")),
                    section_title=str(payload.get("section_title", "")),
                    point_type=str(payload.get("point_type", "chunk")),
                )
            )

        return results

    def hybrid_search(
        self,
        dense_results: List[RetrievalResult],
        sparse_results: List[RetrievalResult],
        top_k: int = 24,
    ) -> List[RetrievalResult]:
        """
        使用倒数排名融合（RRF）合并稠密和稀疏检索结果

        Args:
            dense_results: 稠密检索结果
            sparse_results: 稀疏检索结果
            top_k: 返回结果数量

        Returns:
            融合后的检索结果
        """
        rrf_k = 60

        score_map: Dict[str, float] = {}
        result_map: Dict[str, RetrievalResult] = {}

        for rank, result in enumerate(dense_results, start=1):
            rrf_score = 1.0 / (rank + rrf_k)
            weighted_score = rrf_score * self._dense_weight
            score_map[result.chunk_id] = score_map.get(result.chunk_id, 0.0) + weighted_score
            result_map[result.chunk_id] = result

        for rank, result in enumerate(sparse_results, start=1):
            rrf_score = 1.0 / (rank + rrf_k)
            weighted_score = rrf_score * self._sparse_weight
            score_map[result.chunk_id] = score_map.get(result.chunk_id, 0.0) + weighted_score

            if result.chunk_id not in result_map:
                result_map[result.chunk_id] = result

        merged_results = []
        for chunk_id, final_score in score_map.items():
            result = result_map[chunk_id]
            merged_results.append(
                RetrievalResult(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    corpus_id=result.corpus_id,
                    file_name=result.file_name,
                    page_or_loc=result.page_or_loc,
                    text=result.text,
                    score=final_score,
                    retrieval_type="hybrid",
                    section_id=result.section_id,
                    section_title=result.section_title,
                    point_type=result.point_type,
                )
            )

        merged_results.sort(key=lambda x: x.score, reverse=True)
        return merged_results[:top_k]

    def search(
        self,
        query: str,
        qdrant_client=None,
        collection_name: str | None = None,
        query_vector: List[float] | None = None,
        query_filter=None,
        top_k: int = 24,
        mode: Literal["dense", "sparse", "hybrid"] = "hybrid",
    ) -> List[RetrievalResult]:
        """
        统一检索接口，支持三种检索模式

        Args:
            query: 查询文本
            qdrant_client: Qdrant 客户端（稠密检索需要）
            collection_name: Qdrant 集合名称（稠密检索需要）
            query_vector: 查询向量（稠密检索需要）
            query_filter: Qdrant 过滤器（稠密检索需要）
            top_k: 返回结果数量
            mode: 检索模式：dense（稠密）、sparse（稀疏）、hybrid（混合）

        Returns:
            检索结果列表

        Raises:
            ValueError: 当模式为 hybrid 或 dense 但缺少必要参数时
        """
        if mode == "sparse":
            return self.sparse_search(query, top_k)
        
        if mode == "dense":
            if qdrant_client is None or collection_name is None or query_vector is None:
                raise ValueError(
                    "dense mode requires qdrant_client, collection_name, and query_vector"
                )
            return self.dense_search(
                qdrant_client, collection_name, query_vector, query_filter, top_k
            )
        
        if mode == "hybrid":
            if qdrant_client is None or collection_name is None or query_vector is None:
                raise ValueError(
                    "hybrid mode requires qdrant_client, collection_name, and query_vector"
                )
            
            dense_results = self.dense_search(
                qdrant_client, collection_name, query_vector, query_filter, top_k
            )
            sparse_results = self.sparse_search(query, top_k)
            
            return self.hybrid_search(dense_results, sparse_results, top_k)
        
        raise ValueError(f"Invalid mode: {mode}")

    def _tokenize(self, text: str) -> List[str]:
        """使用 jieba 进行中文优化分词"""
        # 使用全模式或精确模式皆可，这里结合 cut_for_search 以提高 BM25 的召回率
        return list(jieba.cut_for_search(text))

    @property
    def dense_weight(self) -> float:
        return self._dense_weight

    @property
    def sparse_weight(self) -> float:
        return self._sparse_weight
