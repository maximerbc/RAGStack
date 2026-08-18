from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.schemas import Chunk
from app.services.index import LanceChunkIndex
from app.services.openai_service import FakeAIProvider
from app.services.reranker import FakeReranker
from app.services.retrieval import RetrievalService


async def run() -> float:
    with tempfile.TemporaryDirectory(prefix="rag-2026-perf-") as temp:
        root = Path(temp)
        settings = Settings(
            app_data_dir=root,
            embedding_dimensions=8,
            adaptive_min_k=2,
            adaptive_max_k=10,
        )
        ai = FakeAIProvider(8)
        index = LanceChunkIndex(root / "lance", dimensions=8)
        texts = [
            f"Enterprise revenue and operating performance for reporting unit {number}."
            if number % 11 == 0
            else f"General product documentation passage number {number}."
            for number in range(50_000)
        ]
        vectors = await ai.embed(texts)
        chunks = [
            Chunk(
                id=f"chunk-{number}",
                document_id="synthetic-doc",
                document_version_id="version-1",
                raw_text=text,
                retrieval_text=f"Document: Synthetic corpus\n{text}",
                title="Synthetic corpus",
                token_count=12,
                vector=vectors[number],
            )
            for number, text in enumerate(texts)
        ]
        index.add(chunks)
        index.activate_version("synthetic-doc", "version-1")
        service = RetrievalService(settings, index, ai, FakeReranker(), lambda _: "synthetic.txt")
        await service.retrieve("enterprise revenue", [])
        started = time.perf_counter()
        trace = await service.retrieve("enterprise revenue", [])
        elapsed = time.perf_counter() - started
        if not trace.evidence:
            raise RuntimeError("Performance test retrieved no evidence")
        return elapsed


def main() -> None:
    elapsed = asyncio.run(run())
    print(f"50,000-chunk warm retrieval: {elapsed:.3f}s")
    if elapsed >= 2:
        raise SystemExit("Performance target missed: expected under 2 seconds")


if __name__ == "__main__":
    main()
