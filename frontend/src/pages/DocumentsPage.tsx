import { ChangeEvent, useEffect, useRef, useState } from 'react'
import { Database, File, FileUp, MoreHorizontal, RefreshCw, Trash2 } from 'lucide-react'
import { get, post, remove } from '../lib/api'
import type { DocumentItem } from '../types'

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const load = () => get<DocumentItem[]>('/documents').then(setDocuments).catch(error => setError(error.message))
  useEffect(() => { load(); const timer = window.setInterval(load, 2000); return () => clearInterval(timer) }, [])

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return
    setUploading(true); setError('')
    const data = new FormData(); data.append('file', file)
    try { const response = await fetch('/api/documents', { method: 'POST', body: data }); if (!response.ok) { const body = await response.json(); throw new Error(body.detail ?? 'Upload failed') } await load() }
    catch (error) { setError((error as Error).message) } finally { setUploading(false); event.target.value = '' }
  }
  async function reindex(id: string) { await post(`/documents/${id}/reindex`); await load() }
  async function destroy(id: string) { if (confirm('Delete this document and its index?')) { await remove(`/documents/${id}`); await load() } }

  return <div className="page"><header className="page-header"><div><span className="eyebrow">Corpus management</span><h1>Documents</h1><p>Every active document participates in retrieval.</p></div><button className="primary" onClick={() => input.current?.click()} disabled={uploading}><FileUp size={17}/>{uploading ? 'Uploading…' : 'Upload document'}</button><input ref={input} hidden type="file" accept=".pdf,.docx,.md,.txt,.html,.htm" onChange={upload}/></header>
    {error && <div className="error-banner">{error}</div>}
    <div className="drop-zone" onClick={() => input.current?.click()}><span><Database size={25}/></span><div><strong>Build your evidence base</strong><p>PDF, DOCX, Markdown, TXT, or HTML · up to 50 MB</p></div></div>
    <section className="table-card"><div className="table-title"><h2>Shared corpus</h2><span>{documents.length} documents</span></div>{!documents.length ? <div className="table-empty">No documents uploaded yet.</div> : <div className="document-list">{documents.map(document => <div className="document-row" key={document.id}><span className="file-icon"><File size={18}/></span><div className="document-name"><strong>{document.name}</strong><span>{formatBytes(document.size_bytes)} · {new Date(document.created_at).toLocaleDateString()}</span>{document.error && <small>{document.error}</small>}</div><span className={`status-pill ${document.status}`}>{document.status}</span><span className="chunk-count">{document.chunk_count ? `${document.chunk_count} chunks` : '—'}</span><div className="row-actions"><button title="Reindex" onClick={() => reindex(document.id)}><RefreshCw size={16}/></button><button title="Delete" onClick={() => destroy(document.id)}><Trash2 size={16}/></button><button><MoreHorizontal size={16}/></button></div></div>)}</div>}</section>
  </div>
}
function formatBytes(bytes: number) { return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }

