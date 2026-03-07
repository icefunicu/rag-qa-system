#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
上下文压缩模块

使用 LLM 或提取式算法压缩检索结果，提取与查询最相关的信息，
同时保持信息完整性，减少 LLM 上下文窗口占用。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum

from app.main import LLMGateway, RankedChunk


class CompressionMode(Enum):
    """压缩模式"""
    LLM = "llm"
    EXTRACTIVE = "extractive"


@dataclass(frozen=True)
class CompressedContext:
    """压缩后的上下文"""
    original_text: str
    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    compression_rate: float
    information_retention_rate: float
    mode: CompressionMode
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            object.__setattr__(self, 'metadata', {})


class ContextCompressorInterface(ABC):
    """上下文压缩器接口"""

    @abstractmethod
    def compress(self, query: str, context: str, max_tokens: int) -> CompressedContext:
        """
        压缩上下文

        Args:
            query: 用户查询
            context: 原始上下文
            max_tokens: 最大 token 数

        Returns:
            压缩后的上下文
        """
        pass


class LLMBasedCompressor(ContextCompressorInterface):
    """基于 LLM 的上下文压缩器"""

    def __init__(self, llm_gateway: LLMGateway):
        """
        初始化 LLM 压缩器

        Args:
            llm_gateway: LLM 网关实例
        """
        self.llm_gateway = llm_gateway
        self._compression_prompt_template = """请基于以下查询，从给定的文档片段中提取最关键的信息，生成简洁的摘要。

查询：{query}

文档片段：
{context}

要求：
1. 只保留与查询直接相关的信息
2. 删除冗余、重复或无关的内容
3. 保持关键事实、数据和结论
4. 使用简洁的语言，避免修饰词
5. 保留重要的元数据（如来源、页码等）
6. 输出长度不超过 {max_tokens} 个 token

请输出压缩后的内容："""

    def compress(self, query: str, context: str, max_tokens: int) -> CompressedContext:
        """使用 LLM 压缩上下文"""
        original_tokens = self._count_tokens(context)
        
        prompt = self._compression_prompt_template.format(
            query=query,
            context=context,
            max_tokens=max_tokens
        )
        
        try:
            compressed_text = self._llm_compress(prompt, max_tokens)
        except Exception as e:
            compressed_text = context
        
        compressed_tokens = self._count_tokens(compressed_text)
        
        compression_rate = self._calculate_compression_rate(original_tokens, compressed_tokens)
        retention_rate = self._estimate_information_retention(query, context, compressed_text)
        
        return CompressedContext(
            original_text=context,
            compressed_text=compressed_text,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_rate=compression_rate,
            information_retention_rate=retention_rate,
            mode=CompressionMode.LLM,
            metadata={
                "query": query,
                "max_tokens": max_tokens,
            }
        )

    def _llm_compress(self, prompt: str, max_tokens: int) -> str:
        """调用 LLM 进行压缩"""
        payload = {
            "model": self.llm_gateway._cfg.chat_model,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个专业的文本压缩助手，擅长从文档中提取关键信息，生成简洁准确的摘要。",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        
        data = self.llm_gateway._request_json("/chat/completions", payload)
        
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("LLM compression response format invalid")
        
        if isinstance(content, list):
            pieces = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
            content = "".join(pieces)
        
        return str(content).strip()

    def _count_tokens(self, text: str) -> int:
        """估算 token 数量（简化版本）"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[A-Za-z0-9_]+', text))
        return chinese_chars + english_words

    def _calculate_compression_rate(self, original: int, compressed: int) -> float:
        """计算压缩率"""
        if original == 0:
            return 0.0
        return round((original - compressed) / original, 4)

    def _estimate_information_retention(
        self, query: str, original: str, compressed: str
    ) -> float:
        """估算信息保留率"""
        original_keywords = self._extract_keywords(query, original)
        compressed_keywords = set(compressed.lower().split())
        
        if not original_keywords:
            return 1.0
        
        retained = sum(1 for kw in original_keywords if kw in compressed_keywords)
        return round(retained / len(original_keywords), 4)

    def _extract_keywords(self, query: str, text: str) -> set:
        """提取关键词"""
        stop_words = {
            "的", "了", "是", "在", "和", "与", "及", "等", "个", "什么",
            "如何", "怎么", "怎样", "为什么", "哪些", "哪个", "谁",
            "where", "what", "when", "who", "why", "how", "the", "is", "are",
        }
        
        query_words = set(query.lower().split())
        text_words = set(text.lower().split())
        
        keywords = {
            word for word in query_words
            if word not in stop_words and len(word) >= 2
        }
        
        return keywords


class ExtractiveCompressor(ContextCompressorInterface):
    """基于提取的上下文压缩器（备选方案）"""

    def __init__(self):
        """初始化提取式压缩器"""
        self._sentence_delimiters = re.compile(r'[。！？.!?]')

    def compress(self, query: str, context: str, max_tokens: int) -> CompressedContext:
        """使用提取式方法压缩上下文"""
        original_tokens = self._count_tokens(context)
        
        sentences = self._split_sentences(context)
        scored_sentences = self._score_sentences(query, sentences)
        
        compressed_sentences = self._select_top_sentences(
            scored_sentences, max_tokens
        )
        
        compressed_text = "。".join(compressed_sentences)
        if compressed_text and not compressed_text.endswith("。"):
            compressed_text += "。"
        
        compressed_tokens = self._count_tokens(compressed_text)
        
        compression_rate = self._calculate_compression_rate(original_tokens, compressed_tokens)
        retention_rate = self._estimate_information_retention(query, context, compressed_text)
        
        return CompressedContext(
            original_text=context,
            compressed_text=compressed_text,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_rate=compression_rate,
            information_retention_rate=retention_rate,
            mode=CompressionMode.EXTRACTIVE,
            metadata={
                "query": query,
                "max_tokens": max_tokens,
                "total_sentences": len(sentences),
                "selected_sentences": len(compressed_sentences),
            }
        )

    def _split_sentences(self, text: str) -> List[str]:
        """将文本分割为句子"""
        sentences = self._sentence_delimiters.split(text)
        return [s.strip() for s in sentences if s.strip()]

    def _score_sentences(self, query: str, sentences: List[str]) -> List[tuple]:
        """为每个句子评分"""
        query_keywords = self._extract_keywords(query)
        scored = []
        
        for idx, sentence in enumerate(sentences):
            score = self._calculate_sentence_score(query_keywords, sentence, idx)
            scored.append((idx, sentence, score))
        
        return scored

    def _calculate_sentence_score(
        self, query_keywords: set, sentence: str, position: int
    ) -> float:
        """计算句子得分"""
        sentence_lower = sentence.lower()
        
        keyword_matches = sum(
            1 for kw in query_keywords if kw in sentence_lower
        )
        
        keyword_score = keyword_matches / max(len(query_keywords), 1)
        
        length_penalty = 1.0
        if len(sentence) < 10:
            length_penalty = 0.5
        elif len(sentence) > 200:
            length_penalty = 0.8
        
        position_bonus = 1.0
        if position == 0:
            position_bonus = 1.1
        elif position <= 2:
            position_bonus = 1.05
        
        return keyword_score * length_penalty * position_bonus

    def _select_top_sentences(
        self, scored_sentences: List[tuple], max_tokens: int
    ) -> List[str]:
        """选择得分最高的句子，直到达到 token 限制"""
        sorted_sentences = sorted(scored_sentences, key=lambda x: x[2], reverse=True)
        
        selected = []
        current_tokens = 0
        
        for idx, sentence, score in sorted_sentences:
            sentence_tokens = self._count_tokens(sentence)
            if current_tokens + sentence_tokens <= max_tokens:
                selected.append((idx, sentence, score))
                current_tokens += sentence_tokens
        
        selected.sort(key=lambda x: x[0])
        
        return [sentence for idx, sentence, score in selected]

    def _extract_keywords(self, query: str) -> set:
        """提取查询关键词"""
        stop_words = {
            "的", "了", "是", "在", "和", "与", "及", "等", "个", "什么",
            "如何", "怎么", "怎样", "为什么", "哪些", "哪个", "谁",
            "where", "what", "when", "who", "why", "how", "the", "is", "are",
        }
        
        words = re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9_]+', query.lower())
        
        keywords = {
            word for word in words
            if word not in stop_words and len(word) >= 2
        }
        
        return keywords

    def _count_tokens(self, text: str) -> int:
        """估算 token 数量"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[A-Za-z0-9_]+', text))
        return chinese_chars + english_words

    def _calculate_compression_rate(self, original: int, compressed: int) -> float:
        """计算压缩率"""
        if original == 0:
            return 0.0
        return round((original - compressed) / original, 4)

    def _estimate_information_retention(
        self, query: str, original: str, compressed: str
    ) -> float:
        """估算信息保留率"""
        original_keywords = self._extract_keywords(query)
        compressed_lower = compressed.lower()
        
        if not original_keywords:
            return 1.0
        
        retained = sum(1 for kw in original_keywords if kw in compressed_lower)
        return round(retained / len(original_keywords), 4)


class ContextCompressor:
    """上下文压缩器（统一接口）"""

    def __init__(
        self,
        llm_gateway: Optional[LLMGateway] = None,
        mode: CompressionMode = CompressionMode.LLM,
        max_tokens: int = 3200,
        enabled: bool = True,
    ):
        """
        初始化上下文压缩器

        Args:
            llm_gateway: LLM 网关实例（LLM 模式需要）
            mode: 压缩模式：llm 或 extractive
            max_tokens: 最大 token 数（默认 3200）
            enabled: 是否启用压缩（默认 True）
        """
        self._llm_gateway = llm_gateway
        self._mode = mode
        self._max_tokens = max_tokens
        self._enabled = enabled
        
        if mode == CompressionMode.LLM:
            if llm_gateway is None:
                self._compressor = ExtractiveCompressor()
                self._mode = CompressionMode.EXTRACTIVE
            else:
                self._compressor = LLMBasedCompressor(llm_gateway)
        else:
            self._compressor = ExtractiveCompressor()

    def compress(
        self,
        query: str,
        ranked_chunks: List[RankedChunk],
        max_tokens: Optional[int] = None,
    ) -> CompressedContext:
        """
        压缩检索结果

        Args:
            query: 用户查询
            ranked_chunks: 排序后的检索结果
            max_tokens: 最大 token 数（可选，覆盖默认值）

        Returns:
            压缩后的上下文
        """
        if not self._enabled:
            context_text = self._chunks_to_context(ranked_chunks)
            tokens = self._count_tokens(context_text)
            return CompressedContext(
                original_text=context_text,
                compressed_text=context_text,
                original_tokens=tokens,
                compressed_tokens=tokens,
                compression_rate=0.0,
                information_retention_rate=1.0,
                mode=self._mode,
                metadata={"enabled": False}
            )
        
        context_text = self._chunks_to_context(ranked_chunks)
        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        
        return self._compressor.compress(query, context_text, effective_max_tokens)

    def _chunks_to_context(self, ranked_chunks: List[RankedChunk]) -> str:
        """将检索结果转换为上下文文本"""
        lines = []
        for idx, chunk in enumerate(ranked_chunks, start=1):
            lines.append(
                f"[{idx}] 来源：{chunk.file_name} ({chunk.page_or_loc})\n"
                f"内容：{chunk.text}\n"
            )
        return "\n\n".join(lines)

    def _count_tokens(self, text: str) -> int:
        """估算 token 数量"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[A-Za-z0-9_]+', text))
        return chinese_chars + english_words

    @property
    def mode(self) -> CompressionMode:
        return self._mode

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def enabled(self) -> bool:
        return self._enabled


def get_compressor(
    llm_gateway: Optional[LLMGateway] = None,
    mode: str = "llm",
    max_tokens: int = 3200,
    enabled: bool = True,
) -> ContextCompressor:
    """
    获取压缩器实例

    Args:
        llm_gateway: LLM 网关实例
        mode: 压缩模式："llm" 或 "extractive"
        max_tokens: 最大 token 数
        enabled: 是否启用

    Returns:
        ContextCompressor 实例
    """
    compression_mode = CompressionMode.LLM if mode == "llm" else CompressionMode.EXTRACTIVE
    return ContextCompressor(
        llm_gateway=llm_gateway,
        mode=compression_mode,
        max_tokens=max_tokens,
        enabled=enabled,
    )
