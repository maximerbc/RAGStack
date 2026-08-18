from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable

from app.config import Settings
from app.schemas import Chunk, EvidenceCitation, RankedChunk, RetrievalTrace
from app.services.index import ChunkIndex
from app.services.openai_service import AIProvider
from app.services.reranker import Reranker


def reciprocal_rank_fusion(
    lexical: list[Chunk], dense: list[Chunk], constant: int = 60, limit: int = 60
) -> list[RankedChunk]:
    fused: dict[str, RankedChunk] = {}
    for rank, chunk in enumerate(lexical, start=1):
        item = fused.setdefault(chunk.id, RankedChunk(chunk=chunk))
        item.lexical_rank = rank
        item.rrf_score += 1 / (constant + rank)
    for rank, chunk in enumerate(dense, start=1):
        item = fused.setdefault(chunk.id, RankedChunk(chunk=chunk))
        item.dense_rank = rank
        item.rrf_score += 1 / (constant + rank)
    return sorted(fused.values(), key=lambda item: (-item.rrf_score, item.chunk.id))[:limit]


def adaptive_k(
    ranked: list[RankedChunk],
    minimum: int = 2,
    maximum: int = 10,
    default: int = 5,
    gap: float = 0.08,
) -> int:
    if not ranked:
        return 0
    upper = min(maximum, len(ranked))
    if upper <= minimum:
        return upper
    best_position, best_gap = min(default, upper), 0.0
    for position in range(minimum, upper):
        score_gap = ranked[position - 1].reranker_score - ranked[position].reranker_score
        if score_gap > best_gap:
            best_position, best_gap = position, score_gap
    return best_position if best_gap >= gap else min(default, upper)


def validate_citation_ids(answer: str, evidence: list[EvidenceCitation]) -> list[str]:
    import re

    valid = {item.evidence_id for item in evidence}
    used = re.findall(r"\[(E\d+)\]", answer)
    return sorted(set(used) - valid)


class RetrievalService:
    def __init__(
        self,
        settings: Settings,
        index: ChunkIndex,
        ai: AIProvider,
        reranker: Reranker,
        document_name: Callable[[str], str],
    ):
        self.settings = settings
        self.index = index
        self.ai = ai
        self.reranker = reranker
        self.document_name = document_name

    async def retrieve(
        self,
        question: str,
        history: list[dict[str, str]],
        document_ids: list[str] | None = None,
    ) -> RetrievalTrace:
        timings: dict[str, float] = {}
        started = time.perf_counter()
        rewritten = await self.ai.rewrite(question, history)
        timings["rewrite"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        query_vector = (await self.ai.embed([rewritten]))[0]
        timings["embedding"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        lexical, dense = await asyncio.gather(
            asyncio.to_thread(
                self.index.lexical_search,
                rewritten,
                self.settings.lexical_k,
                document_ids,
            ),
            asyncio.to_thread(
                self.index.dense_search,
                query_vector,
                self.settings.dense_k,
                document_ids,
            ),
        )
        fused = reciprocal_rank_fusion(
            lexical, dense, self.settings.rrf_constant, self.settings.fused_k
        )
        timings["retrieve_and_fuse"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        reranked = await asyncio.to_thread(self.reranker.rerank, rewritten, fused)
        timings["rerank"] = (time.perf_counter() - started) * 1000
        selected_k = adaptive_k(
            reranked,
            self.settings.adaptive_min_k,
            self.settings.adaptive_max_k,
            self.settings.adaptive_default_k,
            self.settings.adaptive_gap,
        )
        expanded = self._expand(reranked[:selected_k])
        citations = [
            EvidenceCitation(
                evidence_id=f"E{number}",
                chunk_id=item.chunk.id,
                document_id=item.chunk.document_id,
                document_name=self.document_name(item.chunk.document_id),
                page=item.chunk.page,
                excerpt=item.chunk.raw_text[:800],
            )
            for number, item in enumerate(expanded, start=1)
        ]
        return RetrievalTrace(
            original_query=question,
            rewritten_query=rewritten,
            candidates=reranked,
            selected_k=selected_k,
            evidence=citations,
            timings_ms=timings,
        )

    def _expand(self, selected: list[RankedChunk]) -> list[RankedChunk]:
        output: list[RankedChunk] = []
        seen: set[str] = set()
        budget = 0
        for ranked in selected:
            related: list[RankedChunk] = [ranked]
            chunk = ranked.chunk
            context_poor = chunk.token_count < 120 or chunk.content_type in {"table", "list"}
            if context_poor:
                for chunk_id in (chunk.previous_id, chunk.next_id):
                    neighbor = self.index.get(chunk_id) if chunk_id else None
                    if neighbor and neighbor.document_id == chunk.document_id:
                        related.append(
                            RankedChunk(
                                chunk=neighbor,
                                reranker_score=ranked.reranker_score,
                                rrf_score=ranked.rrf_score,
                                expanded=True,
                            )
                        )
            for item in related:
                if item.chunk.id in seen:
                    continue
                if budget + item.chunk.token_count > self.settings.evidence_token_budget:
                    continue
                seen.add(item.chunk.id)
                budget += item.chunk.token_count
                output.append(item)
        return output

    @staticmethod
    def evidence_prompt(trace: RetrievalTrace, index: ChunkIndex) -> str:
        parts: list[str] = []
        for citation in trace.evidence:
            chunk = index.get(citation.chunk_id)
            if chunk:
                location = f", page {citation.page}" if citation.page else ""
                parts.append(
                    f"[{citation.evidence_id}] Source: {citation.document_name}{location}\n{chunk.raw_text}"
                )
        return "\n\n".join(parts)


def retrieval_metrics(trace: RetrievalTrace, relevant: list[dict]) -> dict[str, float]:
    if not relevant:
        return {"recall_at_k": 0.0, "mrr": 0.0, "ndcg": 0.0}
    relevant_pairs = {(str(item.get("document_id", "")), item.get("page")) for item in relevant}
    hits: list[int] = []
    for rank, citation in enumerate(trace.evidence, start=1):
        pair = (citation.document_id, citation.page)
        doc_wildcard = (citation.document_id, None)
        if pair in relevant_pairs or doc_wildcard in relevant_pairs:
            hits.append(rank)
    recall = min(1.0, len(hits) / max(1, len(relevant_pairs)))
    mrr = 1 / hits[0] if hits else 0.0
    dcg = sum(1 / math.log2(rank + 1) for rank in hits)
    ideal = sum(
        1 / math.log2(rank + 1)
        for rank in range(1, min(len(relevant_pairs), len(trace.evidence)) + 1)
    )
    return {"recall_at_k": recall, "mrr": mrr, "ndcg": dcg / ideal if ideal else 0.0}
