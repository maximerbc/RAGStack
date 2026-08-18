from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class Chunk(BaseModel):
    id: str
    document_id: str
    document_version_id: str
    raw_text: str
    retrieval_text: str
    title: str
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = None
    parent_id: str | None = None
    previous_id: str | None = None
    next_id: str | None = None
    content_type: str = "text"
    token_count: int = 0
    vector: list[float] | None = Field(default=None, exclude=True)


class RankedChunk(BaseModel):
    chunk: Chunk
    lexical_rank: int | None = None
    dense_rank: int | None = None
    rrf_score: float = 0.0
    reranker_score: float = 0.0
    expanded: bool = False


class EvidenceCitation(BaseModel):
    evidence_id: str
    chunk_id: str
    document_id: str
    document_name: str
    page: int | None = None
    excerpt: str


class RetrievalTrace(BaseModel):
    original_query: str
    rewritten_query: str
    candidates: list[RankedChunk] = Field(default_factory=list)
    selected_k: int = 0
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class Document(BaseModel):
    id: str
    name: str
    sha256: str
    media_type: str
    status: Literal["queued", "processing", "ready", "failed", "deleting"]
    size_bytes: int
    chunk_count: int = 0
    active_version_id: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class Conversation(BaseModel):
    id: str
    title: str = "New conversation"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class Turn(BaseModel):
    id: str
    conversation_id: str
    question: str
    rag_answer: str | None = None
    baseline_answer: str | None = None
    judge: dict[str, Any] | None = None
    trace: RetrievalTrace | None = None
    status: str = "queued"
    created_at: str = Field(default_factory=utc_now)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    compare: bool = False
    document_ids: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    question: str
    history: list[dict[str, str]] = Field(default_factory=list)
    reference_answer: str = ""
    relevant_evidence: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: str = Field(default_factory=utc_now)


class BenchmarkRun(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    total_cases: int = 0
    completed_cases: int = 0
    metrics: dict[str, Any] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None


class StreamEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
