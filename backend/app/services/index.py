from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

from app.schemas import Chunk


class ChunkIndex(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def activate_version(self, document_id: str, version_id: str) -> None: ...
    def delete_document(self, document_id: str) -> None: ...
    def lexical_search(
        self, query: str, limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]: ...
    def dense_search(
        self, vector: list[float], limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]: ...
    def get(self, chunk_id: str) -> Chunk | None: ...


class LanceChunkIndex:
    TABLE = "chunks"

    def __init__(self, path: Path, dimensions: int = 1536):
        import lancedb

        self.db = lancedb.connect(path)
        self.dimensions = dimensions
        self._lock = threading.RLock()

    def _records(self, chunks: list[Chunk]) -> list[dict[str, Any]]:
        records = []
        for chunk in chunks:
            item = chunk.model_dump()
            item["heading_path"] = " > ".join(chunk.heading_path)
            item["vector"] = chunk.vector or [0.0] * self.dimensions
            item["is_active"] = False
            records.append(item)
        return records

    def _table_exists(self) -> bool:
        return self.TABLE in (self.db.list_tables().tables or [])

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        with self._lock:
            records = self._records(chunks)
            if not self._table_exists():
                table = self.db.create_table(self.TABLE, data=records)
            else:
                table = self.db.open_table(self.TABLE)
                table.add(records)
            from lancedb.index import FTS

            table.create_index("retrieval_text", config=FTS(language="English"), replace=True)

    def activate_version(self, document_id: str, version_id: str) -> None:
        if not self._table_exists():
            return
        with self._lock:
            table = self.db.open_table(self.TABLE)
            safe_doc = document_id.replace("'", "''")
            safe_ver = version_id.replace("'", "''")
            table.update(where=f"document_id = '{safe_doc}'", values={"is_active": False})
            table.update(where=f"document_version_id = '{safe_ver}'", values={"is_active": True})

    def delete_document(self, document_id: str) -> None:
        if self._table_exists():
            safe = document_id.replace("'", "''")
            self.db.open_table(self.TABLE).delete(f"document_id = '{safe}'")

    @staticmethod
    def _chunk(row: dict[str, Any]) -> Chunk:
        row = {
            key: value
            for key, value in row.items()
            if not key.startswith("_") and key != "is_active"
        }
        row["heading_path"] = (
            row.get("heading_path", "").split(" > ") if row.get("heading_path") else []
        )
        return Chunk.model_validate(row)

    @staticmethod
    def _active_filter(document_ids: list[str] | None = None) -> str:
        predicate = "is_active = true"
        if document_ids:
            safe = [item.replace("'", "''") for item in document_ids]
            predicate += " AND document_id IN (" + ",".join(f"'{item}'" for item in safe) + ")"
        return predicate

    def lexical_search(
        self, query: str, limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]:
        if not self._table_exists():
            return []
        rows = (
            self.db.open_table(self.TABLE)
            .search(query, query_type="fts", fts_columns="retrieval_text")
            .where(self._active_filter(document_ids))
            .limit(limit)
            .to_list()
        )
        return [self._chunk(row) for row in rows]

    def dense_search(
        self, vector: list[float], limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]:
        if not self._table_exists():
            return []
        rows = (
            self.db.open_table(self.TABLE)
            .search(vector, vector_column_name="vector")
            .where(self._active_filter(document_ids))
            .limit(limit)
            .to_list()
        )
        return [self._chunk(row) for row in rows]

    def get(self, chunk_id: str) -> Chunk | None:
        if not self._table_exists():
            return None
        safe = chunk_id.replace("'", "''")
        rows = self.db.open_table(self.TABLE).search().where(f"id = '{safe}'").limit(1).to_list()
        return self._chunk(rows[0]) if rows else None


class MemoryChunkIndex:
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}
        self.active_versions: dict[str, str] = {}

    def add(self, chunks: list[Chunk]) -> None:
        self.chunks.update({chunk.id: chunk for chunk in chunks})

    def activate_version(self, document_id: str, version_id: str) -> None:
        self.active_versions[document_id] = version_id

    def delete_document(self, document_id: str) -> None:
        self.chunks = {
            key: value for key, value in self.chunks.items() if value.document_id != document_id
        }

    def _active(self, document_ids: list[str] | None = None) -> list[Chunk]:
        return [
            chunk
            for chunk in self.chunks.values()
            if self.active_versions.get(chunk.document_id) == chunk.document_version_id
            and (not document_ids or chunk.document_id in document_ids)
        ]

    def lexical_search(
        self, query: str, limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]:
        terms = set(query.lower().split())
        return sorted(
            self._active(document_ids),
            key=lambda c: -len(terms & set(c.retrieval_text.lower().split())),
        )[:limit]

    def dense_search(
        self, vector: list[float], limit: int, document_ids: list[str] | None = None
    ) -> list[Chunk]:
        def similarity(chunk: Chunk) -> float:
            return sum(a * b for a, b in zip(vector, chunk.vector or [], strict=False))

        return sorted(self._active(document_ids), key=similarity, reverse=True)[:limit]

    def get(self, chunk_id: str) -> Chunk | None:
        return self.chunks.get(chunk_id)
