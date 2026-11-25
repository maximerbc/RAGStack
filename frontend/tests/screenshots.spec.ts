import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

// Fictional fixtures for documentation only. Scores and timings are illustrative.
const documentId = 'sample-document'
const question = 'How much did enterprise revenue grow?'
const excerpt = 'Enterprise revenue grew 27% year over year. Total annual revenue was $12.4 million, compared with $10.0 million in the previous year.'
const cases = [{ id: 'sample-case', question, reference_answer: 'Enterprise revenue grew 27% year over year.', history: [], relevant_evidence: [{ document_id: documentId, page: null }], tags: ['sample'], notes: 'Fictional example' }]
const trace = {
  original_query: question, rewritten_query: question, selected_k: 2,
  timings_ms: { rewrite: 0, embedding: 38, retrieve_and_fuse: 12, rerank: 24 },
  evidence: [{ evidence_id: 'E1', chunk_id: 'revenue', document_id: documentId, document_name: 'sample-report.md', excerpt }],
  candidates: [
    { chunk: { id: 'revenue', title: 'Northstar Analytics — Revenue', raw_text: excerpt }, lexical_rank: 1, dense_rank: 1, rrf_score: 2 / 61, reranker_score: 0.94 },
    { chunk: { id: 'priorities', title: 'Northstar Analytics — Product priorities', raw_text: 'The next release prioritizes document search.' }, lexical_rank: 2, dense_rank: 2, rrf_score: 2 / 62, reranker_score: 0.21 },
  ],
}

test('capture the application with fictional sample data', async ({ page }) => {
  await mkdir('../docs/images', { recursive: true })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const responses: Record<string, unknown> = {
      '/api/health': { status: 'ready', api_key_configured: false, corpus_version: 1 },
      '/api/conversations': [{ id: 'sample-conversation', title: 'Sample report' }],
      '/api/conversations/sample-conversation/turns': [{ id: 'sample-turn', conversation_id: 'sample-conversation', question, rag_answer: 'Enterprise revenue grew **27% year over year**. Total annual revenue reached **$12.4 million**, up from $10.0 million in the previous year. [E1]', baseline_answer: '', trace, status: 'completed', created_at: '2026-11-25T15:00:00Z' }],
      '/api/documents': [{ id: documentId, name: 'sample-report.md', status: 'ready', size_bytes: 620, chunk_count: 3, created_at: '2026-11-25T15:00:00Z' }],
      '/api/eval-cases': cases,
      '/api/benchmarks': [{ id: 'illustrative-run', status: 'completed', total_cases: 1, completed_cases: 1, created_at: '2026-11-25T15:00:00Z', metrics: { cases: 1, wins: { rag: 1, baseline: 0, tie: 0 }, retrieval: { recall_at_k: 1 }, mean_correctness: { rag: 0.9 }, output_tokens_estimated: { rag: 42 } }, config_snapshot: {}, results: [] }],
    }
    if (!(path in responses)) throw new Error(`Unexpected screenshot API request: ${path}`)
    await route.fulfill({ json: responses[path] })
  })
  await page.goto('/')
  await expect(page.getByText('Enterprise revenue grew', { exact: false }).first()).toBeVisible()
  await page.getByRole('button', { name: /Retrieval diagnostics/ }).click()
  await expect(page.getByText('Adaptive K = 2')).toBeVisible()
  await page.evaluate(async () => { await document.fonts.ready })
  await page.screenshot({ path: '../docs/images/chat.png', fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Documents', exact: true }).click()
  await expect(page.getByText('sample-report.md')).toBeVisible()
  await page.screenshot({ path: '../docs/images/documents.png', fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Benchmarks', exact: true }).click()
  await expect(page.getByText('1/1 cases · completed')).toBeVisible()
  await page.screenshot({ path: '../docs/images/benchmarks.png', fullPage: true, animations: 'disabled' })
})
