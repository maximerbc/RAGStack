# Evaluation and evidence

[Back to the overview](../README.md)

RAGStack implements evaluation tooling. This repository does not currently publish a representative labeled dataset, measured RAG quality study, or live-provider latency benchmark. Screenshots and deterministic test outputs are not experimental findings.

## Two evaluation paths

**Chat comparison** generates an evidence-backed answer and an LLM-only answer, then judges them with retrieved evidence but no reference answer. The UI labels this a reference-free judge. Its preference is an estimate for that exchange.

**Benchmark suites** run saved questions with optional conversation history, reference answers, and relevant evidence. Supply both a reference answer and relevant evidence for interpretable answer-quality and retrieval scores. The API currently permits incomplete cases; missing labels must not be interpreted as measured poor retrieval.

A run records progress, aggregate metrics, per-case results, and a configuration snapshot containing model IDs, reranker metadata, corpus version, and the RRF constant. It does not freeze every setting or a copy of the corpus/cases. Preserve the full configuration, corpus, and exported cases externally when comparing experiments.

## Case format

JSONL contains one object per line:

```json
{"question":"How much did enterprise revenue grow?","reference_answer":"Enterprise revenue grew 27% year over year.","history":[],"relevant_evidence":[{"document_id":"REPLACE_WITH_UPLOADED_DOCUMENT_ID","page":null}],"tags":["sample"],"notes":"Fictional example; replace the document ID before importing."}
```

The ID is assigned during import if omitted. CSV accepts the same fields; `history`, `relevant_evidence`, and `tags` must contain JSON arrays. Export returns JSONL. Markdown and text documents typically have no page number; use `null` for a document-level relevance label.

Find document IDs in `GET /api/documents` using the API documentation. The [walkthrough](walkthrough.md) shows how to create a first case through the UI.

## Interpret metrics carefully

| Metric | Current implementation and limitation |
| --- | --- |
| Pairwise win rate | Fraction of evaluated cases where the LLM judge prefers RAG; ties are separate. A/B answer order is deterministically shuffled. |
| Correctness / groundedness | LLM-generated scores in [0, 1], averaged across cases; not independent human validation. |
| Retrieval recall, MRR, nDCG | Computed on final evidence citations after expansion, matching document/page labels. Multiple chunks from the same labeled page/document can count as repeated hits. Recall is capped at 1; nDCG can exceed 1 in that situation. These are approximate diagnostics, not standard deduplicated relevance metrics. |
| Citation precision | Fraction of citation occurrences whose evidence ID exists; does not verify that a claim follows from the passage. |
| Citation completeness | Fraction of available evidence IDs cited at least once; does not measure coverage of factual claims. |
| Tokens | Locally estimated using `cl100k_base`; not provider billing usage. |
| Latency | Per-case elapsed evaluation time, including retrieval, both generated answers, and judging; not time to first token. |

## Automated checks

```bash
make test
make lint
make build
make browser
make e2e
```

Backend tests exercise parsing, chunking, retrieval logic, real LanceDB indexing, API contracts, upload/ingestion with fake AI, and terminal SSE replay. Frontend tests cover navigation and app rendering. Browser fixtures intercept API requests; they do not test live provider integration. Tests require no OpenAI credentials or reranker weights. The first tokenizer use may download a tokenization vocabulary.

CI uses Python 3.11 and Node.js 22, clears the API key, selects the fake reranker, and runs these checks. Passing CI establishes these tested behaviors, not production readiness.

## Synthetic performance check

`make perf` builds 50,000 synthetic chunks with eight-dimensional deterministic embeddings and a fake reranker, warms retrieval once, then times one retrieval. It checks for evidence and enforces a two-second threshold.

This is a local regression check, not an end-to-end RAG benchmark: it excludes real embeddings, the MiniLM cross-encoder, generation, network latency, and a representative corpus. Record hardware, dependency versions, and repeated timings before drawing performance conclusions. It is intentionally outside the default CI gate.

## A defensible future comparison

Freeze a representative corpus and labeled questions, preserve model/settings versions, compare retrieval variants on the same cases, and report per-case results plus aggregate uncertainty. Separate retrieval quality, answer quality, judge estimates, cost, and latency. No such experiment is claimed by this cleanup.
