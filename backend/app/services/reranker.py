from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.schemas import RankedChunk


@runtime_checkable
class Reranker(Protocol):
    name: str
    model_id: str

    def rerank(self, query: str, candidates: list[RankedChunk]) -> list[RankedChunk]: ...

    def metadata(self) -> dict[str, object]: ...


class MiniLMCrossEncoderReranker:
    name = "sentence-transformers-cross-encoder"

    def __init__(
        self,
        model_id: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
        cache_dir: Path | str = Path(".models"),
    ):
        self.model_id = model_id
        self.cache_dir = Path(cache_dir)
        self._model = None

    def _load(self):
        if self._model is None:
            cache_root = str(self.cache_dir.resolve())
            os.environ.setdefault("HF_HOME", cache_root)
            os.environ.setdefault("XDG_CACHE_HOME", cache_root)
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            from sentence_transformers import CrossEncoder

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = CrossEncoder(
                self.model_id,
                device="cpu",
                cache_folder=str(self.cache_dir.resolve()),
            )
        return self._model

    def rerank(self, query: str, candidates: list[RankedChunk]) -> list[RankedChunk]:
        if not candidates:
            return []
        pairs = [(query, candidate.chunk.retrieval_text) for candidate in candidates]
        logits = self._load().predict(pairs, batch_size=16, show_progress_bar=False)
        for candidate, logit in zip(candidates, logits, strict=True):
            value = float(logit)
            candidate.reranker_score = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))
        return sorted(candidates, key=lambda item: item.reranker_score, reverse=True)

    def metadata(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "model": self.model_id,
            "device": "cpu",
            "loaded": self._model is not None,
        }


class FakeReranker:
    """Deterministic reranker for tests and contract validation."""

    name = "fake-overlap"
    model_id = "deterministic-v1"

    def rerank(self, query: str, candidates: list[RankedChunk]) -> list[RankedChunk]:
        terms = {term.lower() for term in query.split() if term}
        for candidate in candidates:
            words = set(candidate.chunk.retrieval_text.lower().split())
            candidate.reranker_score = len(terms & words) / max(1, len(terms))
        return sorted(candidates, key=lambda item: (-item.reranker_score, item.chunk.id))

    def metadata(self) -> dict[str, object]:
        return {"provider": self.name, "model": self.model_id, "device": "none", "loaded": True}


def build_reranker(
    backend: str, model_id: str, cache_dir: Path | str = Path(".models")
) -> Reranker:
    if backend == "fake":
        return FakeReranker()
    if backend == "minilm":
        return MiniLMCrossEncoderReranker(model_id, cache_dir)
    raise ValueError(f"Unknown reranker backend: {backend}")


def download_default_model() -> None:
    from app.config import get_settings

    settings = get_settings()
    MiniLMCrossEncoderReranker(settings.reranker_model, settings.model_cache_dir)._load()
    print("Default reranker is cached and ready.")
