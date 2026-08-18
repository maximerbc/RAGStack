const jsonHeaders = { 'Content-Type': 'application/json' }

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try { const body = await response.json(); message = body.detail ?? body.message ?? message } catch { /* empty */ }
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', headers: body ? jsonHeaders : undefined, body: body ? JSON.stringify(body) : undefined })
export const remove = (path: string) => api<void>(path, { method: 'DELETE' })

export function events(path: string, handlers: Record<string, (data: any) => void>): EventSource {
  const source = new EventSource(`/api${path}`)
  Object.entries(handlers).forEach(([name, handler]) => source.addEventListener(name, event => handler(JSON.parse((event as MessageEvent).data))))
  const close = () => source.close()
  ;['complete', 'failed', 'cancelled'].forEach(name => source.addEventListener(name, close))
  return source
}

