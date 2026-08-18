import pytest
from app.config import Settings
from app.schemas import Chunk, RankedChunk
from app.services.index import MemoryChunkIndex
from app.services.openai_service import FakeAIProvider
from app.services.reranker import FakeReranker, Reranker
from app.services.retrieval import (
    RetrievalService,
    adaptive_k,
    reciprocal_rank_fusion,
    validate_citation_ids,
)


def chunk(chunk_id: str, text: str, vector=None) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id="doc",
        document_version_id="v1",
        raw_text=text,
        retrieval_text=f"Document: Report\n{text}",
        title="Report",
        token_count=20,
        vector=vector or [0.1] * 8,
    )


def test_rrf_preserves_independent_ranks_and_deduplicates():
    a, b, c = chunk("a", "alpha"), chunk("b", "beta"), chunk("c", "gamma")
    fused = reciprocal_rank_fusion([a, b], [b, c], constant=60)
    assert [item.chunk.id for item in fused] == ["b", "a", "c"]
    assert fused[0].lexical_rank == 2
    assert fused[0].dense_rank == 1


def test_adaptive_k_uses_large_gap_and_default_fallback():
    ranked = [
        RankedChunk(chunk=chunk(str(i), "text"), reranker_score=score)
        for i, score in enumerate([0.96, 0.92, 0.89, 0.48, 0.45, 0.42])
    ]
    assert adaptive_k(ranked, 2, 6, 5, 0.08) == 3
    flat = [
        RankedChunk(chunk=chunk(str(i), "text"), reranker_score=0.9 - i * 0.01) for i in range(8)
    ]
    assert adaptive_k(flat, 2, 8, 5, 0.08) == 5


def test_fake_reranker_satisfies_model_agnostic_contract():
    reranker = FakeReranker()
    assert isinstance(reranker, Reranker)
    ranked = reranker.rerank(
        "enterprise revenue",
        [
            RankedChunk(chunk=chunk("a", "enterprise revenue")),
            RankedChunk(chunk=chunk("b", "weather")),
        ],
    )
    assert ranked[0].chunk.id == "a"
    assert reranker.metadata()["model"] == "deterministic-v1"


@pytest.mark.asyncio
async def test_conversational_retrieval_rewrites_followup_and_returns_trace(tmp_path):
    index = MemoryChunkIndex()
    ai = FakeAIProvider()
    item = chunk("a", "NVIDIA revenue in fiscal 2025", [0.1] * 8)
    index.add([item])
    index.activate_version("doc", "v1")
    settings = Settings(app_data_dir=tmp_path, embedding_dimensions=8, adaptive_min_k=1)
    service = RetrievalService(settings, index, ai, FakeReranker(), lambda _: "report.pdf")
    trace = await service.retrieve(
        "And the year before?", [{"role": "user", "content": "What was NVIDIA revenue?"}]
    )
    assert "NVIDIA" in trace.rewritten_query
    assert trace.original_query == "And the year before?"
    assert trace.evidence[0].document_name == "report.pdf"
    assert validate_citation_ids("Answer [E1] and [E9]", trace.evidence) == ["E9"]
