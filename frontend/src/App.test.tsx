import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import App from './App'

vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  if (url.includes('/health')) return new Response(JSON.stringify({ status: 'ready', api_key_configured: false, corpus_version: 0 }))
  if (url.includes('/conversations')) return new Response(JSON.stringify([]))
  return new Response(JSON.stringify([]))
}))

test('renders the product navigation and credential status', async () => {
  render(<App />)
  expect(screen.getByText('RAG 2026')).toBeInTheDocument()
  expect(screen.getByText('Documents')).toBeInTheDocument()
  expect(await screen.findByText('API key not configured')).toBeInTheDocument()
})

