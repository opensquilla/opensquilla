// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createApp, h, nextTick, type App } from 'vue'
import i18n from '@/i18n'
import KnowledgeUploadPanel from './KnowledgeUploadPanel.vue'
import {
  saveStoredKnowledgeUpload,
  type FetchLike,
  type KnowledgeIndexType,
  type StoredKnowledgeUpload,
} from './knowledgeUpload'

const mountedApps: App[] = []
let fetchMock: Mock<FetchLike>

function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function savedUpload(
  jobId: string | null,
  indexTypes: KnowledgeIndexType[] = ['fts', 'vector'],
): StoredKnowledgeUpload {
  return {
    version: 1,
    collectionId: 'customer_shared',
    uploadId: 'upload-1',
    jobId,
    filename: 'customer.zip',
    sizeBytes: 10,
    lastModified: 1_700_000_000_000,
    indexTypes,
  }
}

function jobBody(overrides: Record<string, unknown> = {}) {
  return {
    jobId: 'job-1',
    uploadId: 'upload-1',
    state: 'ready',
    phase: 'complete',
    overallProgress: 100,
    upload: { uploadedBytes: 10, sizeBytes: 10, percent: 100 },
    files: { total: 5, processed: 5, skipped: 0, failed: 0 },
    chunks: { total: 12, ftsIndexed: 12, vectorIndexed: 12 },
    warnings: [],
    error: null,
    ...overrides,
  }
}

async function settle(rounds = 10) {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve()
  await nextTick()
}

async function mountPanel() {
  const root = document.createElement('div')
  document.body.appendChild(root)
  const onVerifySearch = vi.fn()
  const app = createApp({
    render: () => h(KnowledgeUploadPanel, { onVerifySearch }),
  })
  app.use(i18n)
  app.mount(root)
  mountedApps.push(app)
  await settle()
  return { root, onVerifySearch }
}

function chooseFile(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: [file],
  })
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

function setChecked(input: HTMLInputElement, checked: boolean) {
  input.checked = checked
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

beforeEach(() => {
  localStorage.clear()
  i18n.global.locale.value = 'en'
  fetchMock = vi.fn<FetchLike>()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('KnowledgeUploadPanel', () => {
  it('offers exactly FTS/vector, requires one, and normalizes cancel/recheck order', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/uploads') && init?.method === 'POST') {
        return jsonResponse({
          uploadId: 'upload-1',
          filename: 'customer.zip',
          sizeBytes: 4,
          uploadedBytes: 0,
          indexTypes: ['fts', 'vector'],
          chunkSizeBytes: 16_777_216,
        }, 201)
      }
      if (url.endsWith('/uploads/upload-1') && init?.method === 'PATCH') {
        return jsonResponse({
          uploadId: 'upload-1',
          filename: 'customer.zip',
          sizeBytes: 4,
          uploadedBytes: 4,
          indexTypes: ['fts', 'vector'],
          chunkSizeBytes: 16_777_216,
        }, 200, { 'Upload-Offset': '4' })
      }
      if (url.endsWith('/uploads/upload-1/complete')) {
        return jsonResponse({ uploadId: 'upload-1', jobId: 'job-1', state: 'queued' }, 202)
      }
      if (url.endsWith('/jobs/job-1')) {
        return jsonResponse(jobBody({
          chunks: { total: 3, ftsIndexed: 3, vectorIndexed: 3 },
        }))
      }
      throw new Error(`unexpected request: ${url}`)
    })
    const { root } = await mountPanel()
    const indexes = Array.from(root.querySelectorAll<HTMLInputElement>(
      '.knowledge-upload__indexes input[type="checkbox"]',
    ))
    expect(indexes.map(input => input.value)).toEqual(['fts', 'vector'])

    setChecked(indexes[0]!, false)
    await nextTick()
    setChecked(indexes[1]!, false)
    await nextTick()
    expect(root.textContent).toContain('Select at least one index.')

    const start = root.querySelector<HTMLButtonElement>('[data-testid="knowledge-upload-start"]')!
    chooseFile(
      root.querySelector<HTMLInputElement>('[data-testid="knowledge-upload-file"]')!,
      new File(['data'], 'customer.zip', {
        type: 'application/zip',
        lastModified: 1_700_000_000_000,
      }),
    )
    await nextTick()
    expect(start.disabled).toBe(true)

    setChecked(indexes[1]!, true)
    await nextTick()
    setChecked(indexes[0]!, true)
    await nextTick()
    expect(start.disabled).toBe(false)
    start.click()
    await settle(16)

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST'
      && String(init.body).startsWith('{'))!
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      filename: 'customer.zip',
      sizeBytes: 4,
      indexTypes: ['fts', 'vector'],
    })
    expect(fetchMock.mock.calls.map(([url, init]) => [String(url), init?.method ?? 'GET']))
      .toHaveLength(4)
    expect(root.querySelector('[data-testid="knowledge-upload-error"]')?.textContent)
      .toBeUndefined()
    await vi.waitFor(() => {
      expect(root.querySelector('[data-testid="knowledge-upload-result"]')).not.toBeNull()
    })
  })

  it('restores upload bytes after refresh and requires the same File before resuming', async () => {
    saveStoredKnowledgeUpload(savedUpload(null))
    fetchMock.mockResolvedValue(jsonResponse({
      uploadId: 'upload-1',
      filename: 'customer.zip',
      sizeBytes: 10,
      uploadedBytes: 4,
      indexTypes: ['fts', 'vector'],
      chunkSizeBytes: 16_777_216,
    }))

    const { root } = await mountPanel()
    expect(root.querySelector('[data-testid="knowledge-upload-reselect"]')?.textContent)
      .toContain('customer.zip')
    expect(root.querySelector('[data-testid="knowledge-upload-bytes"]')?.textContent)
      .toContain('4 bytes / 10 bytes')

    const input = root.querySelector<HTMLInputElement>('[data-testid="knowledge-upload-file"]')!
    const start = root.querySelector<HTMLButtonElement>('[data-testid="knowledge-upload-start"]')!
    expect(input.disabled).toBe(false)
    expect(start.disabled).toBe(true)

    chooseFile(input, new File(['0123456789'], 'customer.zip', {
      type: 'application/zip',
      lastModified: 1_700_000_000_001,
    }))
    await nextTick()
    expect(root.textContent).toContain('Select the same file to resume')
    expect(start.disabled).toBe(true)

    chooseFile(input, new File(['0123456789'], 'customer.zip', {
      type: 'application/zip',
      lastModified: 1_700_000_000_000,
    }))
    await nextTick()
    expect(start.disabled).toBe(false)
    expect(start.textContent).toContain('Resume upload')
  })

  it('restores a running job, shows its exact phase, and locks new uploads', async () => {
    saveStoredKnowledgeUpload(savedUpload('job-1'))
    fetchMock.mockResolvedValue(jsonResponse(jobBody({
      state: 'running',
      phase: 'parsing',
      overallProgress: 42,
      files: { total: 5, processed: 2, skipped: 0, failed: 0 },
      chunks: { total: 6, ftsIndexed: 0, vectorIndexed: 0 },
    })))

    const { root } = await mountPanel()

    expect(root.querySelector('[data-testid="knowledge-job-state"]')?.textContent)
      .toContain('Running')
    expect(root.querySelector('[data-phase="validating"]')?.getAttribute('data-phase-status'))
      .toBe('done')
    expect(root.querySelector('[data-phase="extracting"]')?.getAttribute('data-phase-status'))
      .toBe('done')
    expect(root.querySelector('[data-phase="parsing"]')?.getAttribute('data-phase-status'))
      .toBe('current')
    expect(root.querySelector<HTMLInputElement>('[data-testid="knowledge-upload-file"]')?.disabled)
      .toBe(true)
    expect(root.textContent).toContain('42%')
  })

  it('shows warning completion counters and reuses the existing search workbench entry', async () => {
    saveStoredKnowledgeUpload(savedUpload('job-1'))
    fetchMock.mockResolvedValue(jsonResponse(jobBody({
      state: 'ready_with_warnings',
      files: { total: 5, processed: 4, skipped: 1, failed: 0 },
      chunks: { total: 12, ftsIndexed: 12, vectorIndexed: 10 },
      warnings: ['notes.txt was skipped'],
    })))

    const { root, onVerifySearch } = await mountPanel()

    expect(root.querySelector('[data-testid="knowledge-upload-result"]')?.textContent)
      .toContain('4 / 5')
    expect(root.querySelector('[data-testid="knowledge-upload-result"]')?.textContent)
      .toContain('12')
    expect(root.querySelector('[data-testid="knowledge-job-warnings"]')?.textContent)
      .toContain('notes.txt was skipped')
    const verify = root.querySelector<HTMLButtonElement>('[data-testid="knowledge-upload-verify"]')!
    verify.click()
    await nextTick()
    expect(onVerifySearch).toHaveBeenCalledTimes(1)
    expect(root.querySelector<HTMLInputElement>('[data-testid="knowledge-upload-file"]')?.disabled)
      .toBe(false)
  })

  it('shows a structured failure at the failed phase and marks an unrequested index skipped', async () => {
    saveStoredKnowledgeUpload(savedUpload('job-1', ['vector']))
    fetchMock.mockResolvedValue(jsonResponse(jobBody({
      state: 'failed',
      phase: 'vector_indexing',
      overallProgress: 72,
      chunks: { total: 12, ftsIndexed: 0, vectorIndexed: 7 },
      error: { code: 'vector_failed', message: 'Embedding service unavailable' },
    })))

    const { root } = await mountPanel()

    expect(root.querySelector('[data-phase="fts_indexing"]')?.getAttribute('data-phase-status'))
      .toBe('skipped')
    expect(root.querySelector('[data-phase="vector_indexing"]')?.getAttribute('data-phase-status'))
      .toBe('failed')
    expect(root.querySelector('[data-testid="knowledge-job-error"]')?.textContent)
      .toContain('Embedding service unavailable')
    expect(root.querySelector('[data-testid="knowledge-upload-verify"]')).toBeNull()
  })
})
