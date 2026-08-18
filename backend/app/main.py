from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, get_settings
from app.db import Database
from app.events import EventBus
from app.services.benchmark import BenchmarkService
from app.services.chat import ChatService
from app.services.chunking import StructureAwareChunker
from app.services.index import ChunkIndex, LanceChunkIndex
from app.services.ingestion import IngestionWorker
from app.services.openai_service import AIProvider, OpenAIProvider
from app.services.parser import DocumentParser
from app.services.reranker import Reranker, build_reranker
from app.services.retrieval import RetrievalService


@dataclass
class Services:
    settings: Settings
    db: Database
    bus: EventBus
    index: ChunkIndex
    ai: AIProvider
    reranker: Reranker
    retrieval: RetrievalService
    chat: ChatService
    ingestion: IngestionWorker
    benchmarks: BenchmarkService


def create_app(
    settings: Settings | None = None,
    ai: AIProvider | None = None,
    index: ChunkIndex | None = None,
    reranker: Reranker | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    db = Database(settings.db_path)
    bus = EventBus()
    index = index or LanceChunkIndex(settings.index_path, settings.embedding_dimensions)
    ai = ai or OpenAIProvider(settings)
    reranker = reranker or build_reranker(
        settings.reranker_backend,
        settings.reranker_model,
        settings.model_cache_dir,
    )

    def document_name(document_id: str) -> str:
        row = db.one("SELECT name FROM documents WHERE id=?", (document_id,))
        return row["name"] if row else "Unknown document"

    retrieval = RetrievalService(settings, index, ai, reranker, document_name)
    chat = ChatService(db, ai, retrieval)
    ingestion = IngestionWorker(
        settings,
        db,
        bus,
        DocumentParser(settings.max_pdf_pages),
        StructureAwareChunker(
            settings.target_chunk_tokens, settings.max_chunk_tokens, settings.overlap_tokens
        ),
        index,
        ai,
    )
    benchmarks = BenchmarkService(db, bus, chat, settings.benchmark_concurrency)
    services = Services(
        settings, db, bus, index, ai, reranker, retrieval, chat, ingestion, benchmarks
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = asyncio.create_task(ingestion.run_forever())
        yield
        ingestion.stop()
        worker.cancel()

    app = FastAPI(title="RAG 2026 API", version="0.1.0", lifespan=lifespan)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str):
            requested = dist / path
            return FileResponse(requested if requested.is_file() else dist / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
