from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from worker.chunking import DocType, ParsedSegment, normalize_text


WORD_RE = re.compile(r"\b[a-zA-Z\u4e00-\u9fff]{2,}\b")
SECTION_PATTERNS = (
    re.compile(r"^(#{1,6})\s+(.+)$"),
    re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$"),
    re.compile(r"^(第[0-9零一二三四五六七八九十百千万两〇ＯoOIVXLCDMivxlcdm]+[章节卷篇回幕集])\s*(.+)$"),
    re.compile(r"^(chapter\s+\d+)\s*[:：]?\s*(.+)$", re.IGNORECASE),
    re.compile(r"^(section\s+\d+(?:\.\d+)*)\s*[:：]?\s*(.+)$", re.IGNORECASE),
)


@dataclass(frozen=True)
class EnhancedMetadata:
    keywords: List[str]
    doc_type: DocType
    language: str
    word_count: int
    sentence_count: int
    avg_sentence_length: float
    section_hierarchy: List[Dict[str, str]] = field(default_factory=list)


class MetadataEnhancer:
    CODE_PATTERNS = [
        r"\bdef\s+\w+",
        r"\bclass\s+\w+",
        r"\bfunction\s+\w+",
        r"\bvar\s+\w+",
        r"\bconst\s+\w+",
        r"\bimport\s+\w+",
        r"\bfrom\s+\w+\s+import",
        r"\bpublic\s+class",
        r"\bprivate\s+def",
    ]

    TECHNICAL_TERMS = [
        "api",
        "http",
        "json",
        "database",
        "server",
        "client",
        "authentication",
        "authorization",
        "encryption",
        "deployment",
        "configuration",
        "endpoint",
        "request",
        "response",
    ]

    CONVERSATIONAL_PATTERNS = [
        r"你好",
        r"谢谢",
        r"请问",
        r"\bhello\b",
        r"\bthank\b",
        r"\bplease\b",
        r"\bhow\b",
        r"\bwhat\b",
    ]

    def __init__(self, max_keywords: int = 5):
        self._max_keywords = max_keywords
        self._compiled_code_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.CODE_PATTERNS
        ]
        self._compiled_conv_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.CONVERSATIONAL_PATTERNS
        ]

    def enhance(self, text: str) -> EnhancedMetadata:
        normalized = text or ""
        keywords = self._extract_keywords(normalized)
        doc_type = self._classify_document(normalized)
        language = self._detect_language(normalized)
        word_count = len(normalized.split())
        sentences = self._split_sentences(normalized)
        sentence_count = len(sentences)
        avg_sentence_length = (
            sum(len(sentence.split()) for sentence in sentences) / sentence_count
            if sentence_count > 0
            else 0.0
        )
        section_hierarchy = self._extract_section_hierarchy(normalized)
        return EnhancedMetadata(
            keywords=keywords,
            doc_type=doc_type,
            language=language,
            word_count=word_count,
            sentence_count=sentence_count,
            avg_sentence_length=avg_sentence_length,
            section_hierarchy=section_hierarchy,
        )

    def enhance_segments(
        self,
        segments: Sequence[ParsedSegment],
        *,
        max_chars: int = 120000,
    ) -> EnhancedMetadata:
        sampled = self._sample_segments(segments, max_chars=max_chars)
        return self.enhance(sampled)

    def to_dict(self, metadata: EnhancedMetadata) -> Dict[str, object]:
        return {
            "keywords": metadata.keywords,
            "doc_type": metadata.doc_type.value,
            "language": metadata.language,
            "word_count": metadata.word_count,
            "sentence_count": metadata.sentence_count,
            "avg_sentence_length": round(metadata.avg_sentence_length, 2),
            "section_hierarchy": metadata.section_hierarchy,
        }

    def _sample_segments(self, segments: Sequence[ParsedSegment], *, max_chars: int) -> str:
        if max_chars <= 0:
            max_chars = 120000
        if not segments:
            return ""

        budget = 0
        samples: list[str] = []
        step = max(len(segments) // 8, 1)

        for idx, segment in enumerate(segments):
            include = idx < 4 or idx == len(segments) - 1 or idx % step == 0
            if not include:
                continue

            title = segment.section_title.strip()
            body = segment.text.strip()
            if not body:
                continue

            snippet = body[: min(len(body), max(2000, max_chars // 8))]
            candidate = f"{title}\n{snippet}" if title else snippet
            budget += len(candidate)
            samples.append(candidate)
            if budget >= max_chars:
                break

        if not samples:
            samples.append(segments[0].text[:max_chars])

        return "\n\n".join(samples)[:max_chars]

    def _extract_keywords(self, text: str) -> List[str]:
        words = WORD_RE.findall(text.lower())
        if not words:
            return []

        stop_words = {
            "the",
            "and",
            "that",
            "this",
            "with",
            "from",
            "have",
            "were",
            "will",
            "would",
            "should",
            "about",
            "there",
            "their",
            "因为",
            "所以",
            "一个",
            "我们",
            "他们",
            "已经",
            "没有",
        }
        counter = Counter(word for word in words if word not in stop_words)
        return [word for word, _ in counter.most_common(self._max_keywords)]

    def _classify_document(self, text: str) -> DocType:
        code_score = sum(1 for pattern in self._compiled_code_patterns if pattern.search(text))
        conversational_score = sum(1 for pattern in self._compiled_conv_patterns if pattern.search(text))
        technical_score = sum(1 for term in self.TECHNICAL_TERMS if term in text.lower())
        scores = {
            DocType.CODE: code_score * 3,
            DocType.CONVERSATIONAL: conversational_score * 3,
            DocType.TECHNICAL: technical_score,
            DocType.GENERAL: 0,
        }
        best_type = max(scores, key=scores.get)
        return best_type if scores[best_type] >= 3 else DocType.GENERAL

    def _detect_language(self, text: str) -> str:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(text)
        if total_chars == 0:
            return "unknown"

        ratio = chinese_chars / total_chars
        if ratio > 0.3:
            return "zh"
        if ratio > 0.1:
            return "zh-en"
        return "en"

    def _split_sentences(self, text: str) -> List[str]:
        return [item.strip() for item in re.split(r"[。！？!?]", text) if item.strip()]

    def _extract_section_hierarchy(self, text: str) -> List[Dict[str, str]]:
        sections: List[Dict[str, str]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for pattern in SECTION_PATTERNS:
                match = pattern.match(stripped)
                if not match:
                    continue
                marker = match.group(1).strip()
                title = match.group(2).strip()
                sections.append(
                    {
                        "level": str(self._calculate_section_level(marker)),
                        "title": title,
                        "marker": marker,
                    }
                )
                break
        return sections

    def _calculate_section_level(self, marker: str) -> int:
        if marker.startswith("#"):
            return len(marker)
        if re.match(r"\d+(?:\.\d+)*", marker):
            return len(marker.split("."))
        if marker.lower().startswith("chapter"):
            return 1
        if marker.lower().startswith("section"):
            return 2
        return 1
