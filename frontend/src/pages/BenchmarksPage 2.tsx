import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react'
import { BarChart3, FileInput, FlaskConical, Play, Plus, Trash2, Trophy } from 'lucide-react'
import { events, get, post, remove } from '../lib/api'
import type { BenchmarkRun, EvalCase } from '../types'

export default function BenchmarksPage() {
  const [cases, setCases] = useState<EvalCase[]>([])
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [editing, setEditing] = useState(false)
  const [live, setLive] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const load = async () => { setCases(await get('/eval-cases')); setRuns(await get('/benchmarks')) }
  useEffect(() => { load().catch(error => setError(error.message)) }, [])

  async function start() {
    setError('')
    try {
      const run = await post<BenchmarkRun>('/benchmarks'); setLive({ run, metrics: {}, completed: 0 })
      events(`/benchmarks/${run.id}/events`, {
        'case.complete': data => setLive(current => ({ ...current, ...data })),
        complete: async data => { setLive(current => ({ ...current, metrics: data.metrics, done: true })); setRuns(await get('/benchmarks')) },
        failed: data => setError(data.message),
      })
    } catch (error) { setError((error as Error).message) }
  }
  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0]; if (!selected) return
    const data = new FormData(); data.append('file', selected)
    const response = await fetch('/api/eval-cases/import', { method: 'POST', body: data })
    if (!response.ok) setError((await response.json()).detail ?? 'Import failed'); else await load()
    event.target.value = ''
  }

  const latest = live?.metrics ?? runs[0]?.metrics ?? {}
  return <div className="page"><header className="page-header"><div><span className="eyebrow">Evaluation laboratory</span><h1>Benchmarks</h1><p>Measure retrieval and answer quality, not just model preference.</p></div><div className="header-actions"><button onClick={() => file.current?.click()}><FileInput size={17}/>Import CSV / JSONL</button><button className="primary" onClick={start} disabled={!cases.length || (live && !live.done)}><Play size={17}/>Run suite</button><input ref={file} hidden type="file" accept=".csv,.jsonl" onChange={importFile}/></div></header>
    {error && <div className="error-banner">{error}</div>}
    <section className="metric-grid"><Metric label="RAG win rate" value={percent((latest.wins?.rag ?? 0) / Math.max(1, latest.cases ?? 0))} icon={<Trophy/>}/><Metric label="Retrieval recall" value={percent(latest.retrieval?.recall_at_k ?? 0)} icon={<BarChart3/>}/><Metric label="RAG correctness" value={percent(latest.mean_correctness?.rag ?? 0)} icon={<FlaskConical/>}/><Metric label="Cases evaluated" value={`${live?.completed ?? latest.cases ?? 0}${live?.total ? ` / ${live.total}` : ''}`} icon={<Play/>}/></section>
    {live && !live.done && <div className="run-progress"><div style={{ width: `${100 * (live.completed ?? 0) / Math.max(1, live.total ?? live.run.total_cases)}%` }}/><span>Benchmark running · results update after every case</span></div>}
    <div className="benchmark-grid"><section className="table-card"><div className="table-title"><div><h2>Evaluation cases</h2><span>Ground-truth questions and evidence</span></div><button onClick={() => setEditing(true)}><Plus size={16}/>New case</button></div><div className="case-list">{cases.map(item => <div className="case-row" key={item.id}><div><strong>{item.question}</strong><span>{item.reference_answer || 'No reference answer'}</span></div><button onClick={async () => { await remove(`/eval-cases/${item.id}`); await load() }}><Trash2 size={15}/></button></div>)}{!cases.length && <div className="table-empty">Create a case or import a CSV/JSONL suite.</div>}</div></section>
      <section className="table-card"><div className="table-title"><h2>Run history</h2><span>Configuration-snapshotted</span></div><div className="case-list">{runs.map(run => <div className="case-row" key={run.id}><div><strong>{new Date(run.created_at).toLocaleString()}</strong><span>{run.completed_cases}/{run.total_cases} cases · {run.status}</span></div><span className={`status-pill ${run.status}`}>{run.status}</span></div>)}{!runs.length && <div className="table-empty">No benchmark runs yet.</div>}</div></section></div>
    {editing && <CaseModal onClose={() => setEditing(false)} onSaved={async () => { setEditing(false); await load() }}/>} 
  </div>
}

function Metric({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) { return <div className="metric-card"><span>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div> }
function percent(value: number) { return `${Math.round(value * 100)}%` }

function CaseModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [question, setQuestion] = useState(''); const [reference, setReference] = useState(''); const [notes, setNotes] = useState('')
  async function save(event: FormEvent) { event.preventDefault(); await post('/eval-cases', { question, reference_answer: reference, notes, history: [], relevant_evidence: [], tags: [] }); onSaved() }
  return <div className="drawer-backdrop"><form className="case-modal" onSubmit={save}><span className="eyebrow">New evaluation case</span><h2>Define ground truth</h2><label>Question<textarea required value={question} onChange={event => setQuestion(event.target.value)}/></label><label>Reference answer<textarea required value={reference} onChange={event => setReference(event.target.value)}/></label><label>Notes<textarea value={notes} onChange={event => setNotes(event.target.value)}/></label><div className="modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary">Save case</button></div></form></div>
}

