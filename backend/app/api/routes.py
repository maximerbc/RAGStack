from __future__ import annotations

import asyncio
import csv
import io
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from app.schemas import BenchmarkRun, ChatRequest, Conversation, Document, EvalCase, Turn, utc_now
from app.services.ingestion import detected_media_type, document_identity, safe_filename

router = APIRouter(prefix="/api")


def state(request: Request):
    return request.app.state.services


def document_from_row(row: dict[str, Any]) -> Document:
    return Document.model_validate(row)


def turn_from_row(db, row: dict[str, Any]) -> Turn:
    return Turn(
        id=row["id"],
        conversation_id=row["conversation_id"],
        question=row["question"],
        rag_answer=row["rag_answer"],
        baseline_answer=row["baseline_answer"],
        judge=db.loads(row["judge_json"]),
        trace=db.loads(row["trace_json"]),
        status=row["status"],
        created_at=row["created_at"],
    )


@router.get("/health")
async def health(request: Request):
    services = state(request)
    settings = services.settings
    documents = services.db.one("SELECT COUNT(*) count FROM documents WHERE status='ready'")
    return {
        "status": "ready",
        "api_key_configured": bool(settings.openai_api_key),
        "corpus_version": services.db.corpus_version(),
        "documents_ready": documents["count"] if documents else 0,
        "models": {
            "generation": settings.openai_generation_model,
            "rewrite": settings.openai_rewrite_model,
            "judge": settings.openai_judge_model,
            "embedding": settings.openai_embedding_model,
            "reranker": services.reranker.metadata(),
        },
        "retrieval": {
            "lexical_k": settings.lexical_k,
            "dense_k": settings.dense_k,
            "fused_k": settings.fused_k,
            "rrf_constant": settings.rrf_constant,
            "adaptive_k": [settings.adaptive_min_k, settings.adaptive_max_k],
        },
    }


@router.get("/documents", response_model=list[Document])
async def list_documents(request: Request):
    return [
        document_from_row(row)
        for row in state(request).db.all("SELECT * FROM documents ORDER BY created_at DESC")
    ]


@router.post("/documents", response_model=Document, status_code=202)
async def upload_document(request: Request, file: UploadFile = File(...)):
    services = state(request)
    settings = services.settings
    name = safe_filename(file.filename or "")
    media_type = detected_media_type(name, file.content_type)
    content = await file.read(settings.max_file_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds the {settings.max_file_mb} MB limit")
    if not content:
        raise HTTPException(422, "The uploaded file is empty")
    if name.lower().endswith(".pdf") and not content.startswith(b"%PDF"):
        raise HTTPException(422, "The file extension is PDF but its signature is invalid")
    if name.lower().endswith(".docx") and not content.startswith(b"PK"):
        raise HTTPException(422, "The file extension is DOCX but its signature is invalid")
    document_id, sha256 = document_identity(content)
    duplicate = services.db.one("SELECT * FROM documents WHERE sha256=?", (sha256,))
    if duplicate:
        raise HTTPException(409, f"An identical document already exists: {duplicate['name']}")
    version_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    target_dir = settings.upload_path / document_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    target.write_bytes(content)
    now = utc_now()
    services.db.transaction(
        [
            (
                "INSERT INTO documents(id,name,sha256,media_type,status,size_bytes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (document_id, name, sha256, media_type, "queued", len(content), now, now),
            ),
            (
                "INSERT INTO document_versions(id,document_id,path,status,created_at) VALUES(?,?,?,?,?)",
                (version_id, document_id, str(target), "queued", now),
            ),
            (
                "INSERT INTO jobs(id,kind,subject_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (job_id, "ingest", document_id, "queued", now, now),
            ),
        ]
    )
    return document_from_row(services.db.one("SELECT * FROM documents WHERE id=?", (document_id,)))


@router.get("/documents/{document_id}/file")
async def document_file(request: Request, document_id: str):
    row = state(request).db.one(
        "SELECT v.path,d.media_type,d.name FROM documents d JOIN document_versions v ON v.id=d.active_version_id WHERE d.id=?",
        (document_id,),
    )
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "Document not found")
    return FileResponse(
        row["path"],
        media_type=row["media_type"],
        filename=row["name"],
        content_disposition_type="inline",
    )


@router.post("/documents/{document_id}/retry", status_code=202)
async def retry_document(request: Request, document_id: str):
    services = state(request)
    if not services.db.one("SELECT id FROM documents WHERE id=?", (document_id,)):
        raise HTTPException(404, "Document not found")
    job_id, now = str(uuid.uuid4()), utc_now()
    services.db.transaction(
        [
            (
                "UPDATE documents SET status='queued', error=NULL, updated_at=? WHERE id=?",
                (now, document_id),
            ),
            (
                "INSERT INTO jobs(id,kind,subject_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (job_id, "ingest", document_id, "queued", now, now),
            ),
        ]
    )
    return {"job_id": job_id}


@router.post("/documents/{document_id}/reindex", status_code=202)
async def reindex_document(request: Request, document_id: str):
    services = state(request)
    current = services.db.one(
        "SELECT v.path FROM documents d JOIN document_versions v ON v.id=d.active_version_id WHERE d.id=?",
        (document_id,),
    )
    if not current:
        return await retry_document(request, document_id)
    version_id, job_id, now = str(uuid.uuid4()), str(uuid.uuid4()), utc_now()
    services.db.transaction(
        [
            (
                "INSERT INTO document_versions(id,document_id,path,status,created_at) VALUES(?,?,?,?,?)",
                (version_id, document_id, current["path"], "queued", now),
            ),
            (
                "UPDATE documents SET status='queued', error=NULL, updated_at=? WHERE id=?",
                (now, document_id),
            ),
            (
                "INSERT INTO jobs(id,kind,subject_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (job_id, "ingest", document_id, "queued", now, now),
            ),
        ]
    )
    return {"job_id": job_id, "version_id": version_id}


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(request: Request, document_id: str):
    services = state(request)
    row = services.db.one("SELECT id FROM documents WHERE id=?", (document_id,))
    if not row:
        raise HTTPException(404, "Document not found")
    await asyncio.to_thread(services.index.delete_document, document_id)
    services.db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    target = services.settings.upload_path / document_id
    if target.exists():
        shutil.rmtree(target)
    services.db.bump_corpus_version()


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str):
    services = state(request)

    def terminal():
        row = services.db.one("SELECT status,error FROM jobs WHERE id=?", (job_id,))
        if row and row["status"] in {"completed", "failed"}:
            return {
                "type": "complete" if row["status"] == "completed" else "failed",
                "data": {"job_id": job_id, "message": row["error"]},
            }
        return None

    return StreamingResponse(
        services.bus.stream(f"job:{job_id}", terminal), media_type="text/event-stream"
    )


@router.get("/conversations", response_model=list[Conversation])
async def conversations(request: Request):
    return [
        Conversation.model_validate(row)
        for row in state(request).db.all("SELECT * FROM conversations ORDER BY updated_at DESC")
    ]


@router.post("/conversations", response_model=Conversation)
async def create_conversation(request: Request):
    services = state(request)
    conversation = Conversation(id=str(uuid.uuid4()))
    services.db.execute(
        "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
        (conversation.id, conversation.title, conversation.created_at, conversation.updated_at),
    )
    return conversation


@router.get("/conversations/{conversation_id}/turns", response_model=list[Turn])
async def conversation_turns(request: Request, conversation_id: str):
    services = state(request)
    rows = services.db.all(
        "SELECT * FROM turns WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
    )
    return [turn_from_row(services.db, row) for row in rows]


@router.post("/conversations/{conversation_id}/turns", response_model=Turn, status_code=202)
async def create_turn(
    request: Request, conversation_id: str, payload: ChatRequest, background: BackgroundTasks
):
    services = state(request)
    if not services.db.one("SELECT id FROM conversations WHERE id=?", (conversation_id,)):
        raise HTTPException(404, "Conversation not found")
    turn = Turn(id=str(uuid.uuid4()), conversation_id=conversation_id, question=payload.question)
    services.db.execute(
        "INSERT INTO turns(id,conversation_id,question,status,created_at) VALUES(?,?,?,?,?)",
        (turn.id, conversation_id, turn.question, turn.status, turn.created_at),
    )

    async def emit(event_type: str, data: dict[str, Any]):
        await services.bus.publish(f"turn:{turn.id}", event_type, data)

    background.add_task(
        services.chat.run_turn,
        turn.id,
        payload.compare,
        emit,
        payload.document_ids,
    )
    return turn


@router.get("/turns/{turn_id}", response_model=Turn)
async def get_turn(request: Request, turn_id: str):
    services = state(request)
    row = services.db.one("SELECT * FROM turns WHERE id=?", (turn_id,))
    if not row:
        raise HTTPException(404, "Turn not found")
    return turn_from_row(services.db, row)


@router.get("/turns/{turn_id}/events")
async def turn_events(request: Request, turn_id: str):
    services = state(request)

    def terminal():
        row = services.db.one("SELECT status FROM turns WHERE id=?", (turn_id,))
        if row and row["status"] in {"completed", "failed"}:
            return {
                "type": "complete" if row["status"] == "completed" else "failed",
                "data": {"turn_id": turn_id},
            }
        return None

    return StreamingResponse(
        services.bus.stream(f"turn:{turn_id}", terminal), media_type="text/event-stream"
    )


@router.get("/eval-cases", response_model=list[EvalCase])
async def eval_cases(request: Request):
    db = state(request).db
    return [
        EvalCase.model_validate(db.loads(row["payload_json"]))
        for row in db.all("SELECT payload_json FROM eval_cases ORDER BY created_at")
    ]


@router.post("/eval-cases", response_model=EvalCase)
async def create_eval_case(request: Request, payload: dict[str, Any]):
    services = state(request)
    if not payload.get("id"):
        payload["id"] = str(uuid.uuid4())
    case = EvalCase.model_validate(payload)
    services.db.execute(
        "INSERT OR REPLACE INTO eval_cases(id,payload_json,created_at,updated_at) VALUES(?,?,?,?)",
        (case.id, services.db.dumps(case.model_dump()), case.created_at, utc_now()),
    )
    return case


@router.delete("/eval-cases/{case_id}", status_code=204)
async def delete_eval_case(request: Request, case_id: str):
    state(request).db.execute("DELETE FROM eval_cases WHERE id=?", (case_id,))


@router.post("/eval-cases/import")
async def import_eval_cases(request: Request, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8-sig")
    if (file.filename or "").lower().endswith(".jsonl"):
        records = [json.loads(line) for line in content.splitlines() if line.strip()]
    elif (file.filename or "").lower().endswith(".csv"):
        records = list(csv.DictReader(io.StringIO(content)))
        for record in records:
            for field in ("history", "relevant_evidence", "tags"):
                record[field] = json.loads(record.get(field) or "[]")
    else:
        raise HTTPException(422, "Import must be CSV or JSONL")
    imported = []
    for record in records:
        record.setdefault("id", str(uuid.uuid4()))
        imported.append(await create_eval_case(request, record))
    return {"imported": len(imported)}


@router.get("/eval-cases/export")
async def export_eval_cases(request: Request):
    db = state(request).db
    records = [
        db.loads(row["payload_json"], {})
        for row in db.all("SELECT payload_json FROM eval_cases ORDER BY created_at")
    ]
    content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    return PlainTextResponse(
        content + ("\n" if content else ""),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=rag-2026-eval-cases.jsonl"},
    )


@router.post("/benchmarks", response_model=BenchmarkRun, status_code=202)
async def start_benchmark(request: Request, background: BackgroundTasks):
    services = state(request)
    total = services.db.one("SELECT COUNT(*) count FROM eval_cases")["count"]
    if not total:
        raise HTTPException(422, "Create or import at least one evaluation case")
    snapshot = {
        "corpus_version": services.db.corpus_version(),
        "generation_model": services.settings.openai_generation_model,
        "embedding_model": services.settings.openai_embedding_model,
        "rewrite_model": services.settings.openai_rewrite_model,
        "judge_model": services.settings.openai_judge_model,
        "reranker": services.reranker.metadata(),
        "rrf_constant": services.settings.rrf_constant,
    }
    run = BenchmarkRun(id=str(uuid.uuid4()), total_cases=total, config_snapshot=snapshot)
    services.db.execute(
        "INSERT INTO benchmark_runs(id,status,total_cases,metrics_json,config_json,created_at) VALUES(?,?,?,?,?,?)",
        (
            run.id,
            run.status,
            total,
            services.db.dumps({}),
            services.db.dumps(snapshot),
            run.created_at,
        ),
    )
    background.add_task(services.benchmarks.run, run.id)
    return run


@router.get("/benchmarks")
async def list_benchmarks(request: Request):
    db = state(request).db
    rows = db.all("SELECT * FROM benchmark_runs ORDER BY created_at DESC")
    for row in rows:
        row["metrics"] = db.loads(row.pop("metrics_json"), {})
        row["config_snapshot"] = db.loads(row.pop("config_json"), {})
        row["results"] = db.loads(row.pop("results_json"), [])
    return rows


@router.get("/benchmarks/{run_id}/events")
async def benchmark_events(request: Request, run_id: str):
    services = state(request)

    def terminal():
        row = services.db.one(
            "SELECT status,metrics_json FROM benchmark_runs WHERE id=?", (run_id,)
        )
        if row and row["status"] in {"completed", "failed", "cancelled"}:
            return {
                "type": "complete" if row["status"] == "completed" else row["status"],
                "data": {"metrics": services.db.loads(row["metrics_json"], {})},
            }
        return None

    return StreamingResponse(
        services.bus.stream(f"benchmark:{run_id}", terminal),
        media_type="text/event-stream",
    )


@router.post("/benchmarks/{run_id}/cancel", status_code=202)
async def cancel_benchmark(request: Request, run_id: str):
    state(request).db.execute("UPDATE benchmark_runs SET cancel_requested=1 WHERE id=?", (run_id,))
    return {"status": "cancelling"}
