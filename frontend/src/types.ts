export type DocumentItem = { id: string; name: string; status: string; size_bytes: number; chunk_count: number; error?: string; created_at: string }
export type Citation = { evidence_id: string; chunk_id: string; document_id: string; document_name: string; page?: number; excerpt: string }
export type Candidate = { chunk: { id: string; title: string; raw_text: string; page?: number }; lexical_rank?: number; dense_rank?: number; rrf_score: number; reranker_score: number }
export type Trace = { original_query: string; rewritten_query: string; selected_k: number; timings_ms: Record<string, number>; evidence: Citation[]; candidates: Candidate[] }
export type Turn = { id: string; conversation_id: string; question: string; rag_answer?: string; baseline_answer?: string; judge?: Record<string, unknown>; trace?: Trace; status: string; created_at: string }
export type EvalCase = { id: string; question: string; history: {role: string; content: string}[]; reference_answer: string; relevant_evidence: Record<string, unknown>[]; tags: string[]; notes: string }
export type BenchmarkRun = { id: string; status: string; total_cases: number; completed_cases: number; metrics: Record<string, any>; config_snapshot: Record<string, any>; results: Record<string, any>[]; created_at: string }

