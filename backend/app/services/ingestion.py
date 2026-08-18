from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import uuid
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.events import EventBus
from app.schemas import utc_now
from app.services.chunking import StructureAwareChunker
from app.services.index import ChunkIndex
from app.services.openai_service import AIProvider
from app.services.parser import DocumentParser


class IngestionWorker:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        bus: EventBus,
        parser: DocumentParser,
        chunker: StructureAwareChunker,
        index: ChunkIndex,
        ai: AIProvider,
    ):
        self.settings = settings
        self.db = db
        self.bus = bus
        self.parser = parser
        self.chunker = chunker
        self.index = index
        self.ai = ai
        self._stopping = False

    async def run_forever(self) -> None:
        while not self._stopping:
            job = self.db.one(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            )
            if not job:
                await asyncio.sleep(0.4)
                continue
            await self._process(job)

    def stop(self) -> None:
        self._stopping = True

    async def _process(self, job: dict) -> None:
        job_id, document_id = job["id"], job["subject_id"]
        channel = f"job:{job_id}"
        self.db.execute(
            "UPDATE jobs SET status='processing', progress=.05, updated_at=? WHERE id=?",
            (utc_now(), job_id),
        )
        self.db.execute(
            "UPDATE documents SET status='processing', updated_at=? WHERE id=?",
            (utc_now(), document_id),
        )
        try:
            version = self.db.one(
                "SELECT * FROM document_versions WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
                (document_id,),
            )
            document = self.db.one("SELECT * FROM documents WHERE id=?", (document_id,))
            if not version or not document:
                raise ValueError("Document or version no longer exists")
            await self.bus.publish(channel, "progress", {"progress": 0.1, "stage": "parsing"})
            title, blocks = await asyncio.to_thread(self.parser.parse, Path(version["path"]))
            chunks = self.chunker.chunk(
                document_id, version["id"], title or document["name"], blocks
            )
            await self.bus.publish(channel, "progress", {"progress": 0.35, "stage": "embedding"})
            vectors = await self.ai.embed([chunk.retrieval_text for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.vector = vector
            await self.bus.publish(channel, "progress", {"progress": 0.75, "stage": "indexing"})
            await asyncio.to_thread(self.index.add, chunks)
            previous_version = document.get("active_version_id")
            await asyncio.to_thread(self.index.activate_version, document_id, version["id"])
            now = utc_now()
            try:
                self.db.transaction(
                    [
                        (
                            "UPDATE document_versions SET status='ready' WHERE id=?",
                            (version["id"],),
                        ),
                        (
                            "UPDATE documents SET status='ready', chunk_count=?, active_version_id=?, error=NULL, updated_at=? WHERE id=?",
                            (len(chunks), version["id"], now, document_id),
                        ),
                        (
                            "UPDATE jobs SET status='completed', progress=1, updated_at=? WHERE id=?",
                            (now, job_id),
                        ),
                    ]
                )
            except Exception:
                if previous_version:
                    await asyncio.to_thread(
                        self.index.activate_version,
                        document_id,
                        previous_version,
                    )
                raise
            self.db.bump_corpus_version()
            await self.bus.publish(
                channel, "complete", {"document_id": document_id, "chunk_count": len(chunks)}
            )
        except Exception as exc:
            message = str(exc)
            self.db.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (message, utc_now(), job_id),
            )
            self.db.execute(
                "UPDATE documents SET status='failed', error=?, updated_at=? WHERE id=?",
                (message, utc_now(), document_id),
            )
            await self.bus.publish(channel, "failed", {"message": message, "retryable": True})


def document_identity(content: bytes) -> tuple[str, str]:
    return str(uuid.uuid4()), hashlib.sha256(content).hexdigest()


def safe_filename(name: str) -> str:
    clean = Path(name).name.replace("\x00", "").strip()
    if not clean or clean in {".", ".."}:
        raise ValueError("Invalid filename")
    return clean[:200]


def detected_media_type(name: str, supplied: str | None) -> str:
    extension = Path(name).suffix.lower()
    allowed = {".pdf", ".docx", ".md", ".txt", ".html", ".htm"}
    if extension not in allowed:
        raise ValueError("Supported types are PDF, DOCX, Markdown, TXT, and HTML")
    return supplied or mimetypes.guess_type(name)[0] or "application/octet-stream"
