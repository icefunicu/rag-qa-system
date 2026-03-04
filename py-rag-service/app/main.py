from __future__ import annotations

from typing import List, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator


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
        if any(not item.strip() for item in self.corpus_ids):
            raise ValueError("scope.corpus_ids must not contain empty values")
        if any(not item.strip() for item in self.document_ids):
            raise ValueError("scope.document_ids must not contain empty values")
        return self


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    scope: Scope


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


class QueryResponse(BaseModel):
    answer_sentences: List[AnswerSentence]
    citations: List[Citation]


app = FastAPI(title="py-rag-service", version="0.1.0")


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "service": "py-rag-service"}


@app.post("/v1/rag/query", response_model=QueryResponse)
def rag_query(payload: QueryRequest) -> QueryResponse:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="question must not be blank")

    sentence = AnswerSentence(
        text="非资料证据：RAG 检索链路将在后续阶段接入，当前返回占位回答。",
        evidence_type="common_knowledge",
        citation_ids=[],
        confidence=0.1,
    )
    return QueryResponse(answer_sentences=[sentence], citations=[])

