import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatAttachments } from './useChatAttachments'

const pushToast = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ pushToast }),
}))

function stagedPdf(name = 'paper.pdf') {
  return new File([new Uint8Array(2_000_001)], name, { type: 'application/pdf' })
}

function unsupportedBinary(name = 'bad.bin') {
  return new File([new Uint8Array([0])], name, { type: 'application/octet-stream' })
}

function successfulUploadResponse(fileUuid = 'file-1') {
  return {
    ok: true,
    status: 200,
    json: async () => ({ file_uuid: fileUuid }),
    text: async () => '',
  }
}

async function flushUpload() {
  await new Promise(resolve => setTimeout(resolve, 0))
}

describe('useChatAttachments', () => {
  beforeEach(() => {
    pushToast.mockClear()
    vi.stubGlobal('sessionStorage', {
      getItem: vi.fn((key: string) => key === 'opensquilla.wsToken' ? 'token-123' : null),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps valid files from a mixed batch when another file is rejected', async () => {
    const fetchMock = vi.fn().mockResolvedValue(successfulUploadResponse('file-valid'))
    vi.stubGlobal('fetch', fetchMock)

    const attachments = useChatAttachments()

    await attachments.addAttachments([stagedPdf('valid.pdf'), unsupportedBinary()])
    await flushUpload()

    expect(attachments.pendingAttachments.value).toMatchObject([
      { kind: 'staged', name: 'valid.pdf', file_uuid: 'file-valid' },
    ])
    expect(pushToast).toHaveBeenCalledWith(
      expect.stringContaining('Unsupported file: bad.bin'),
      { tone: 'danger' },
    )
  })

  it('rejects zero-byte files before read or upload work starts', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const attachments = useChatAttachments()

    await attachments.addAttachments([new File([], 'empty.txt', { type: 'text/plain' })])

    expect(fetchMock).not.toHaveBeenCalled()
    expect(attachments.pendingAttachments.value).toHaveLength(0)
    expect(pushToast).toHaveBeenCalledWith('Empty file: empty.txt', { tone: 'danger' })
  })

  it('enforces the frontend aggregate attachment count before upload work starts', async () => {
    const fetchMock = vi.fn().mockResolvedValue(successfulUploadResponse('file-count'))
    vi.stubGlobal('fetch', fetchMock)
    const attachments = useChatAttachments()

    const files = Array.from({ length: 11 }, (_, index) => stagedPdf(`paper-${index}.pdf`))
    await attachments.addAttachments(files)
    await flushUpload()

    expect(fetchMock).toHaveBeenCalledTimes(10)
    expect(attachments.pendingAttachments.value).toHaveLength(10)
    expect(pushToast).toHaveBeenCalledWith('Too many attachments: max 10', { tone: 'danger' })
  })

  it('enforces the frontend aggregate attachment size before upload work starts', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const attachments = useChatAttachments()
    attachments.pendingAttachments.value = Array.from({ length: 4 }, (_, index) => ({
      kind: 'staged',
      local_id: index + 1,
      name: `existing-${index}.pdf`,
      mime: 'application/pdf',
      size: 15 * 1024 * 1024,
      file_uuid: `existing-${index}`,
    }))

    await attachments.addAttachment(stagedPdf('overflow.pdf'))

    expect(fetchMock).not.toHaveBeenCalled()
    expect(attachments.pendingAttachments.value).toHaveLength(4)
    expect(pushToast).toHaveBeenCalledWith(
      'Attachments too large: overflow.pdf would exceed 60 MiB total',
      { tone: 'danger' },
    )
  })

  it('adds the WebSocket token as a bearer header on staged uploads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(successfulUploadResponse('file-token'))
    vi.stubGlobal('fetch', fetchMock)

    const attachments = useChatAttachments()
    await attachments.addAttachment(stagedPdf())
    await flushUpload()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/files/upload', expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      headers: { Authorization: 'Bearer token-123' },
    }))
  })

  it('marks a staged upload failed when the upload response omits file_uuid', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
      text: async () => '',
    })
    vi.stubGlobal('fetch', fetchMock)

    const attachments = useChatAttachments()
    await attachments.addAttachment(stagedPdf('missing-uuid.pdf'))
    await flushUpload()

    expect(attachments.pendingAttachments.value).toMatchObject([
      { kind: 'failed', name: 'missing-uuid.pdf', error: 'Upload response missing file_uuid' },
    ])
    expect(pushToast).toHaveBeenCalledWith(
      'Upload failed for missing-uuid.pdf: Upload response missing file_uuid',
      { tone: 'danger' },
    )
  })

  it('keeps failed staged uploads retryable without reselecting the file', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        text: async () => 'boom',
        json: async () => ({}),
      })
      .mockResolvedValueOnce(successfulUploadResponse('file-retry'))
    vi.stubGlobal('fetch', fetchMock)

    const attachments = useChatAttachments()
    await attachments.addAttachment(stagedPdf('retry.pdf'))
    await flushUpload()

    expect(attachments.pendingAttachments.value).toMatchObject([
      { kind: 'failed', name: 'retry.pdf', error: 'HTTP 500 boom' },
    ])
    expect(attachments.pendingAttachments.value[0].file).toBeInstanceOf(File)

    await attachments.retryAttachment(0)
    await flushUpload()

    expect(attachments.pendingAttachments.value).toMatchObject([
      { kind: 'staged', name: 'retry.pdf', file_uuid: 'file-retry' },
    ])
  })
})
