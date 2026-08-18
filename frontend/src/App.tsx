import { useEffect, useState } from 'react'
import { Activity, Database, FlaskConical, MessageSquareText, Sparkles } from 'lucide-react'
import { get } from './lib/api'
import ChatPage from './pages/ChatPage'
import DocumentsPage from './pages/DocumentsPage'
import BenchmarksPage from './pages/BenchmarksPage'

type Page = 'chat' | 'documents' | 'benchmarks'

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [health, setHealth] = useState<any>(null)
  useEffect(() => { get('/health').then(setHealth).catch(() => setHealth({ status: 'offline' })) }, [])
  const nav = [
    ['chat', MessageSquareText, 'Chat'], ['documents', Database, 'Documents'], ['benchmarks', FlaskConical, 'Benchmarks'],
  ] as const
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><Sparkles size={18}/></span><div><strong>RAG 2026</strong><small>Evidence engine</small></div></div>
      <nav>{nav.map(([id, Icon, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}><Icon size={18}/><span>{label}</span></button>)}</nav>
      <div className="sidebar-foot">
        <div className={`status-dot ${health?.status === 'ready' ? 'ok' : ''}`}><Activity size={14}/> {health?.status ?? 'Connecting'}</div>
        <small>{health?.api_key_configured ? 'OpenAI configured' : 'API key not configured'}</small>
        {health?.corpus_version !== undefined && <small>Corpus v{health.corpus_version}</small>}
      </div>
    </aside>
    <main>{page === 'chat' && <ChatPage/>}{page === 'documents' && <DocumentsPage/>}{page === 'benchmarks' && <BenchmarksPage/>}</main>
  </div>
}

