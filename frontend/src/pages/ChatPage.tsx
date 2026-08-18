import { FormEvent, useEffect, useState } from 'react'
import { ChevronDown, CornerDownLeft, FileText, GitCompareArrows, Search, Send, Timer, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { events, get, post } from '../lib/api'
import type { Citation, Trace, Turn } from '../types'

export default function ChatPage() {
  const [conversationId, setConversationId] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [compare, setCompare] = useState(false)
  const [busy, setBusy] = useState(false)
  const [citation, setCitation] = useState<Citation | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    get<any[]>('/conversations').then(async conversations => {
      const conversation = conversations[0] ?? await post<any>('/conversations')
      setConversationId(conversation.id)
      setTurns(await get<Turn[]>(`/conversations/${conversation.id}/turns`))
    }).catch(error => setError(error.message))
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const value = question.trim()
    if (!value || !conversationId || busy) return
    setQuestion(''); setError(''); setBusy(true)
    try {
      const turn = await post<Turn>(`/conversations/${conversationId}/turns`, { question: value, compare })
      setTurns(current => [...current, { ...turn, rag_answer: '', baseline_answer: '' }])
      events(`/turns/${turn.id}/events`, {
        'retrieval.complete': (trace: Trace) => setTurns(current => current.map(item => item.id === turn.id ? { ...item, trace } : item)),
        'answer.delta': ({ variant, delta }) => setTurns(current => current.map(item => item.id === turn.id ? { ...item, [variant === 'rag' ? 'rag_answer' : 'baseline_answer']: (item[variant === 'rag' ? 'rag_answer' : 'baseline_answer'] ?? '') + delta } : item)),
        'judge.complete': judge => setTurns(current => current.map(item => item.id === turn.id ? { ...item, judge } : item)),
        complete: async () => { setBusy(false); const saved = await get<Turn>(`/turns/${turn.id}`); setTurns(current => current.map(item => item.id === turn.id ? saved : item)) },
        failed: ({ message }) => { setBusy(false); setError(message) },
      })
    } catch (error) { setBusy(false); setError((error as Error).message) }
  }

  return <div className="page chat-page">
    <header className="page-header"><div><span className="eyebrow">Grounded conversations</span><h1>Ask your corpus</h1><p>Hybrid retrieval, adaptive evidence, deterministic sources.</p></div><label className="compare-toggle"><GitCompareArrows size={17}/><span>Compare with LLM only</span><input type="checkbox" checked={compare} onChange={event => setCompare(event.target.checked)}/><i/></label></header>
    <section className="chat-stream">
      {!turns.length && <EmptyChat/>}
      {turns.map(turn => <TurnView key={turn.id} turn={turn} onCitation={setCitation}/>) }
      {error && <div className="error-banner">{error}</div>}
    </section>
    <form className="composer" onSubmit={submit}><textarea aria-label="Question" value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} placeholder="Ask a question about your documents…"/><div className="composer-bar"><span><CornerDownLeft size={14}/> Enter to send · Shift+Enter for a new line</span><button className="primary icon-button" disabled={!question.trim() || busy}><Send size={18}/></button></div></form>
    {citation && <SourceDrawer citation={citation} onClose={() => setCitation(null)}/>} 
  </div>
}

function EmptyChat() { return <div className="empty-state"><span><Search size={26}/></span><h2>Your evidence, interrogated.</h2><p>Upload documents, then ask direct questions or conversational follow-ups such as “And the year before?”</p></div> }

function TurnView({ turn, onCitation }: { turn: Turn; onCitation: (citation: Citation) => void }) {
  const [diagnostics, setDiagnostics] = useState(false)
  const evidence = turn.trace?.evidence ?? []
  const columns = turn.baseline_answer !== undefined && turn.baseline_answer !== ''
  return <article className="turn">
    <div className="user-message">{turn.question}</div>
    <div className={`answer-grid ${columns ? 'compared' : ''}`}>
      {columns && <AnswerCard label="LLM only" answer={turn.baseline_answer ?? ''} muted/>}
      <AnswerCard label="RAG answer" answer={turn.rag_answer ?? ''} evidence={evidence} onCitation={onCitation}/>
    </div>
    {turn.judge && <JudgeCard judge={turn.judge}/>} 
    {turn.trace && <div className="diagnostics"><button onClick={() => setDiagnostics(!diagnostics)}><ChevronDown className={diagnostics ? 'rotated' : ''} size={16}/> Retrieval diagnostics <span>{turn.trace.selected_k} selected</span></button>{diagnostics && <Diagnostics trace={turn.trace}/>}</div>}
  </article>
}

function AnswerCard({ label, answer, evidence = [], onCitation, muted = false }: { label: string; answer: string; evidence?: Citation[]; onCitation?: (citation: Citation) => void; muted?: boolean }) {
  return <div className={`answer-card ${muted ? 'muted' : ''}`}><div className="card-label">{label}{!answer && <span className="streaming-dot"/>}</div><div className="markdown"><ReactMarkdown>{answer || 'Thinking…'}</ReactMarkdown></div>{evidence.length > 0 && <div className="citations">{evidence.map(item => <button key={item.evidence_id} onClick={() => onCitation?.(item)}><FileText size={13}/>{item.evidence_id} · {item.document_name}{item.page ? ` p.${item.page}` : ''}</button>)}</div>}</div>
}

function JudgeCard({ judge }: { judge: Record<string, any> }) {
  const labels = judge.labels ?? {}
  const preferred = labels[judge.preference] ?? judge.preference ?? 'pending'
  return <div className="judge-card"><div><span>Reference-free judge</span><strong>{preferred === 'tie' ? 'Tie' : `${preferred} preferred`}</strong></div><p>{judge.rationale || 'Pairwise evaluation complete.'}</p></div>
}

function Diagnostics({ trace }: { trace: Trace }) {
  const timing = Object.entries(trace.timings_ms).reduce((sum, [, value]) => sum + value, 0)
  return <div className="diagnostic-body"><div className="query-rewrite"><span>Original</span><p>{trace.original_query}</p><span>Standalone query</span><p>{trace.rewritten_query}</p></div><div className="diag-summary"><span><Timer size={14}/>{Math.round(timing)} ms pipeline</span><span>{trace.candidates.length} fused candidates</span><span>Adaptive K = {trace.selected_k}</span></div><div className="candidate-table"><div className="candidate-row head"><span>Passage</span><span>BM25</span><span>Dense</span><span>RRF</span><span>Rerank</span></div>{trace.candidates.slice(0, 10).map(item => <div className="candidate-row" key={item.chunk.id}><span>{item.chunk.title}{item.chunk.page ? ` · p.${item.chunk.page}` : ''}</span><span>{item.lexical_rank ?? '—'}</span><span>{item.dense_rank ?? '—'}</span><span>{item.rrf_score.toFixed(3)}</span><span>{item.reranker_score.toFixed(3)}</span></div>)}</div></div>
}

function SourceDrawer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  return <div className="drawer-backdrop" onClick={onClose}><aside className="source-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close" onClick={onClose}><X/></button><span className="eyebrow">{citation.evidence_id}</span><h2>{citation.document_name}</h2><p className="source-meta">{citation.page ? `Page ${citation.page}` : 'Page not available'}</p><blockquote>{citation.excerpt}</blockquote><a className="primary link-button" href={`/api/documents/${citation.document_id}/file${citation.page ? `#page=${citation.page}` : ''}`} target="_blank">Open original document</a></aside></div>
}
