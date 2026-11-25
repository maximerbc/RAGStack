import { expect, test } from '@playwright/test'

test('navigates between Chat, Documents, and Benchmarks', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ready', api_key_configured: false, corpus_version: 0 } }))
  await page.route('**/api/conversations', route => route.fulfill({ json: route.request().method() === 'POST' ? { id: 'conversation-1', title: 'New conversation' } : [] }))
  await page.route('**/api/conversations/conversation-1/turns', route => route.fulfill({ json: [] }))
  await page.route('**/api/documents', route => route.fulfill({ json: [] }))
  await page.route('**/api/eval-cases', route => route.fulfill({ json: [] }))
  await page.route('**/api/benchmarks', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Ask your corpus' })).toBeVisible()
  await page.getByRole('button', { name: 'Documents' }).click()
  await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible()
  await page.getByRole('button', { name: 'Benchmarks' }).click()
  await expect(page.getByRole('heading', { name: 'Benchmarks' })).toBeVisible()
})
