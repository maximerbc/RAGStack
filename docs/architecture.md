# Architecture and engineering choices

[Back to the overview](../README.md)

RAGStack runs as one FastAPI process plus a React UI. Local files, SQLite, and LanceDB keep the infrastructure small enough to inspect and run locally. It is designed for one user, not a shared public service.

## Ingestion

1. The upload route validates size, supported file type, and basic PDF/DOCX signatures. A SHA-256 identity rejects exact duplicates.
2. SQLite records the document, version, and queued job; the original file stays under `APP_DATA_DIR/documents`.
3. A background worker parses the document. Markdown/text and HTML use local parsers; PDF/DOCX conversion uses Docling.
4. Structure-aware chunking retains headings, page metadata when available, and adjacent-chunk IDs. Defaults target 450 tokens, cap chunks at 600 tokens, and overlap by 60 tokens.
5. OpenAI embeds retrieval text; LanceDB stores chunks and vectors. A version becomes active after indexing succeeds, so failed reindexing does not activate incomplete chunks.

## Question to answer

- With conversation history, the rewriter attempts one standalone query; failures fall back to the original question. Without history, the question is used directly.
- Lexical and dense searches run concurrently, each retrieving up to 50 candidates by default. RRF combines their ranks with constant 60 and keeps up to 60 candidates.
- The default MiniLM cross-encoder reranks candidates on CPU. A score-gap heuristic selects 2–10 passages, defaulting to 5 when no sufficiently large gap is found.
- Short passages, tables, and lists can bring adjacent chunks into the evidence, subject to an 8,000-token budget. `selected_k` is the selection before this expansion, so citation count can differ.
- Generation receives the selected evidence and instructions to cite evidence IDs. The server supplies the IDs, filenames, pages, and original-file routes. Unknown IDs in saved chat answers are removed; this is a structural check, not entailment verification.
- Server-sent events deliver retrieval traces, answer deltas, judging, and terminal status. The UI can inspect ranks, reranker scores, query rewriting, and stage timings.

The optional LLM-only answer uses the same question/history without retrieved evidence. Pairwise judging uses deterministically shuffled A/B labels; a single preference does not establish general superiority.

## Interfaces and source map

| Entry point | Responsibility |
| --- | --- |
| `backend/app/main.py` | App factory, injected services, worker lifecycle, built frontend serving |
| `backend/app/api/routes.py` | `/api/documents`, `/api/conversations`, `/api/turns`, `/api/eval-cases`, `/api/benchmarks`, and event streams |
| `backend/app/services/ingestion.py` | Queued document processing and version activation |
| `backend/app/services/retrieval.py` | RRF, adaptive K, expansion, citation IDs, retrieval metrics |
| `backend/app/services/chat.py` | History, streamed generation, comparison, and evaluation |
| `backend/app/services/index.py` | LanceDB implementation and an in-memory test implementation |
| `backend/app/services/reranker.py` | Reranker protocol, MiniLM implementation, deterministic fake |
| `frontend/src/pages/` | The three user-facing screens |

The app factory accepts injected AI, index, and reranker implementations. Tests use these seams to exercise application behavior without paid calls. Public request/response models are defined in `schemas.py`; running FastAPI exposes their OpenAPI specification at `/docs`.

## Configuration and persistence

Copy `.env.example` to `.env`. Environment settings include model IDs, storage paths, file limits, retrieval sizes, evidence budget, and benchmark concurrency. See `backend/app/config.py` for the complete defaults.

`APP_DATA_DIR` defaults to `./data`; `MODEL_CACHE_DIR` defaults to `./.models`. Both are ignored by Git. The embedding dimension must match the selected embedding model (default 1,536). Changing the embedding model or dimensions requires a fresh compatible index and reingestion; there is no automated index migration.

## Tradeoffs and limits

- Local persistence avoids external database setup but does not provide distributed job execution or multi-user access control.
- RRF preserves lexical/dense rank visibility without assuming comparable raw scores. Reranking adds CPU work; no real-workload latency claim is made here.
- Adaptive K and neighbor expansion are heuristics. Their benefit must be measured against fixed-K alternatives on a labeled corpus.
- The reference metrics and citation checks have limitations described in [evaluation](evaluation.md). They are observability tools, not correctness guarantees.
