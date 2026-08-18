from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RAG 2026"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_data_dir: Path = Path("./data")
    openai_api_key: str | None = None
    openai_generation_model: str = "gpt-5.6-luna"
    openai_rewrite_model: str = "gpt-5.6-luna"
    openai_judge_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    reranker_backend: str = "minilm"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    model_cache_dir: Path = Path("./.models")
    max_file_mb: int = 50
    max_pdf_pages: int = 500
    target_chunk_tokens: int = 450
    max_chunk_tokens: int = 600
    overlap_tokens: int = 60
    lexical_k: int = 50
    dense_k: int = 50
    fused_k: int = 60
    rrf_constant: int = 60
    adaptive_min_k: int = 2
    adaptive_max_k: int = 10
    adaptive_default_k: int = 5
    adaptive_gap: float = 0.08
    evidence_token_budget: int = 8000
    benchmark_concurrency: int = 2
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "rag.sqlite3"

    @property
    def index_path(self) -> Path:
        return self.app_data_dir / "lancedb"

    @property
    def upload_path(self) -> Path:
        return self.app_data_dir / "documents"

    def ensure_directories(self) -> None:
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
