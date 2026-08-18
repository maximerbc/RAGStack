import time

from app.config import Settings
from app.main import create_app
from app.services.index import MemoryChunkIndex
from app.services.openai_service import FakeAIProvider
from app.services.reranker import FakeReranker
from fastapi.testclient import TestClient


def test_health_and_conversation_contracts(tmp_path):
    settings = Settings(app_data_dir=tmp_path, embedding_dimensions=8, reranker_backend="fake")
    app = create_app(settings, FakeAIProvider(), MemoryChunkIndex(), FakeReranker())
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["models"]["reranker"]["provider"] == "fake-overlap"
        conversation = client.post("/api/conversations").json()
        assert conversation["title"] == "New conversation"
        turn = client.post(
            f"/api/conversations/{conversation['id']}/turns",
            json={"question": "What does the evidence say?", "compare": False},
        )
        assert turn.status_code == 202


def test_upload_validation_rejects_fake_pdf(tmp_path):
    settings = Settings(app_data_dir=tmp_path, embedding_dimensions=8, reranker_backend="fake")
    app = create_app(settings, FakeAIProvider(), MemoryChunkIndex(), FakeReranker())
    with TestClient(app) as client:
        response = client.post(
            "/api/documents", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}
        )
        assert response.status_code == 422


def test_markdown_upload_is_ingested_and_searchable_with_fakes(tmp_path):
    settings = Settings(app_data_dir=tmp_path, embedding_dimensions=8, reranker_backend="fake")
    app = create_app(settings, FakeAIProvider(), MemoryChunkIndex(), FakeReranker())
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={
                "file": ("report.md", b"# Revenue\n\nEnterprise revenue grew 27%.", "text/markdown")
            },
        )
        assert response.status_code == 202
        document_id = response.json()["id"]
        for _ in range(30):
            document = client.get("/api/documents").json()[0]
            if document["status"] in {"ready", "failed"}:
                break
            time.sleep(0.05)
        assert document["status"] == "ready", document.get("error")
        assert document["chunk_count"] >= 1

        conversation = client.post("/api/conversations").json()
        turn = client.post(
            f"/api/conversations/{conversation['id']}/turns",
            json={
                "question": "How much did enterprise revenue grow?",
                "document_ids": [document_id],
            },
        ).json()
        saved = client.get(f"/api/turns/{turn['id']}").json()
        assert saved["status"] == "completed"
        assert saved["trace"]["evidence"][0]["document_id"] == document_id


def test_terminal_sse_replays_completion_for_late_subscribers(tmp_path):
    settings = Settings(app_data_dir=tmp_path, embedding_dimensions=8, reranker_backend="fake")
    app = create_app(settings, FakeAIProvider(), MemoryChunkIndex(), FakeReranker())
    with TestClient(app) as client:
        conversation = client.post("/api/conversations").json()
        turn = client.post(
            f"/api/conversations/{conversation['id']}/turns",
            json={"question": "What is available?"},
        ).json()
        with client.stream("GET", f"/api/turns/{turn['id']}/events") as stream:
            payload = "".join(stream.iter_text())
        assert "event: complete" in payload
