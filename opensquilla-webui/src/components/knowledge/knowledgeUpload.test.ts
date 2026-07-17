import { describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_UPLOAD_CHUNK_SIZE_BYTES,
  UPLOAD_STORAGE_KEY,
  createKnowledgeUpload,
  loadStoredKnowledgeUpload,
  matchesStoredFile,
  parseKnowledgeJob,
  saveStoredKnowledgeUpload,
  uploadFileInChunks,
  type FetchLike,
  type KnowledgeUploadStatus,
  type StoredKnowledgeUpload,
} from './knowledgeUpload'

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

function fileOf(content = '0123456789', lastModified = 1_700_000_000_000): File {
  return new File([content], 'customer.zip', {
    type: 'application/zip',
    lastModified,
  })
}

function uploadStatus(
  uploadedBytes = 0,
  chunkSizeBytes = 4,
): KnowledgeUploadStatus {
  return {
    uploadId: 'upload-1',
    filename: 'customer.zip',
    sizeBytes: 10,
    uploadedBytes,
    indexTypes: ['fts', 'vector'],
    chunkSizeBytes,
    jobId: null,
  }
}

function patchBody(uploadedBytes: number) {
  return {
    uploadId: 'upload-1',
    filename: 'customer.zip',
    sizeBytes: 10,
    uploadedBytes,
    indexTypes: ['fts', 'vector'],
    chunkSizeBytes: 4,
  }
}

describe('knowledge upload API contract', () => {
  it('creates the fixed customer upload with the selected index types', async () => {
    const file = fileOf('data')
    const fetcher = vi.fn<FetchLike>().mockResolvedValue(jsonResponse({
      uploadId: 'upload-1',
      filename: 'customer.zip',
      sizeBytes: 4,
      uploadedBytes: 0,
      indexTypes: ['fts'],
      chunkSizeBytes: DEFAULT_UPLOAD_CHUNK_SIZE_BYTES,
    }, 201))

    const created = await createKnowledgeUpload(file, ['fts'], fetcher)

    expect(created.chunkSizeBytes).toBe(16_777_216)
    expect(fetcher).toHaveBeenCalledTimes(1)
    const [url, init] = fetcher.mock.calls[0]!
    expect(url).toBe('/api/v1/knowledge/uploads')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({
      filename: 'customer.zip',
      sizeBytes: 4,
      indexTypes: ['fts'],
    })
  })

  it('deduplicates and orders index types before creating an upload', async () => {
    const file = fileOf('data')
    const fetcher = vi.fn<FetchLike>().mockResolvedValue(jsonResponse({
      uploadId: 'upload-1',
      filename: 'customer.zip',
      sizeBytes: 4,
      uploadedBytes: 0,
      indexTypes: ['fts', 'vector'],
      chunkSizeBytes: DEFAULT_UPLOAD_CHUNK_SIZE_BYTES,
    }, 201))

    await createKnowledgeUpload(file, ['vector', 'fts', 'vector'], fetcher)

    const [, init] = fetcher.mock.calls[0]!
    expect(JSON.parse(String(init?.body))).toEqual({
      filename: 'customer.zip',
      sizeBytes: 4,
      indexTypes: ['fts', 'vector'],
    })
  })

  it('PATCHes bounded file slices in order and trusts only matching body/header offsets', async () => {
    const progress: number[] = []
    const fetcher = vi.fn<FetchLike>()
      .mockResolvedValueOnce(jsonResponse(patchBody(4), 200, { 'Upload-Offset': '4' }))
      .mockResolvedValueOnce(jsonResponse(patchBody(8), 200, { 'Upload-Offset': '8' }))
      .mockResolvedValueOnce(jsonResponse(patchBody(10), 200, { 'Upload-Offset': '10' }))

    const result = await uploadFileInChunks(fileOf(), uploadStatus(), {
      fetcher,
      onProgress: status => progress.push(status.uploadedBytes),
    })

    expect(result.uploadedBytes).toBe(10)
    expect(progress).toEqual([4, 8, 10])
    expect(fetcher.mock.calls.map(([, init]) => (
      (init?.headers as Record<string, string>)['Upload-Offset']
    ))).toEqual(['0', '4', '8'])
    expect(fetcher.mock.calls.map(([, init]) => (init?.body as Blob).size))
      .toEqual([4, 4, 2])
  })

  it('recovers a 409 from the frozen expectedOffset without re-uploading accepted bytes', async () => {
    const fetcher = vi.fn<FetchLike>()
      .mockResolvedValueOnce(jsonResponse({
        error: {
          code: 'upload_offset_mismatch',
          message: 'expected offset 4',
          expectedOffset: 4,
        },
      }, 409))
      .mockResolvedValueOnce(jsonResponse(patchBody(8), 200, { 'Upload-Offset': '8' }))
      .mockResolvedValueOnce(jsonResponse(patchBody(10), 200, { 'Upload-Offset': '10' }))

    const result = await uploadFileInChunks(fileOf(), uploadStatus(), { fetcher })

    expect(result.uploadedBytes).toBe(10)
    expect(fetcher.mock.calls.map(([, init]) => (
      (init?.headers as Record<string, string>)['Upload-Offset']
    ))).toEqual(['0', '4', '8'])
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith('/upload-1'))).toBe(true)
  })

  it('rejects a successful PATCH whose Upload-Offset header disagrees with its body', async () => {
    const fetcher = vi.fn<FetchLike>().mockResolvedValue(
      jsonResponse(patchBody(4), 200, { 'Upload-Offset': '3' }),
    )
    await expect(uploadFileInChunks(fileOf(), uploadStatus(), { fetcher }))
      .rejects.toThrow('invalid upload offset')
  })

  it('validates the frozen job progress, counters, warnings, and structured error', () => {
    const job = parseKnowledgeJob({
      jobId: 'job-1',
      uploadId: 'upload-1',
      state: 'ready_with_warnings',
      phase: 'complete',
      overallProgress: 100,
      upload: { uploadedBytes: 10, sizeBytes: 10, percent: 100 },
      files: { total: 5, processed: 4, skipped: 1, failed: 0 },
      chunks: { total: 12, ftsIndexed: 12, vectorIndexed: 10 },
      warnings: ['one file was skipped'],
      error: null,
      extraField: 'forward-compatible',
    })

    expect(job.files.processed).toBe(4)
    expect(job.chunks.vectorIndexed).toBe(10)
    expect(job.warnings).toEqual(['one file was skipped'])
    expect(() => parseKnowledgeJob({
      ...job,
      overallProgress: 101,
    })).toThrow('invalid job status')
    expect(() => parseKnowledgeJob({
      ...job,
      error: { code: 'broken' },
    })).toThrow('invalid job details')
  })
})

describe('knowledge upload resume metadata', () => {
  it('round-trips only ids and file metadata and verifies the reselected file', () => {
    const storage = new Map<string, string>()
    const storageLike: Storage = {
      get length() {
        return storage.size
      },
      clear: () => storage.clear(),
      getItem: (key: string) => storage.get(key) ?? null,
      key: (index: number) => Array.from(storage.keys())[index] ?? null,
      removeItem: (key: string) => {
        storage.delete(key)
      },
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
    }
    const saved: StoredKnowledgeUpload = {
      version: 1,
      collectionId: 'customer_shared',
      uploadId: 'upload-1',
      jobId: 'job-1',
      filename: 'customer.zip',
      sizeBytes: 10,
      lastModified: 1_700_000_000_000,
      indexTypes: ['fts', 'vector'],
    }

    saveStoredKnowledgeUpload(saved, storageLike)

    expect(storage.has(UPLOAD_STORAGE_KEY)).toBe(true)
    expect(loadStoredKnowledgeUpload(storageLike)).toEqual(saved)
    expect(matchesStoredFile(fileOf(), saved)).toBe(true)
    expect(matchesStoredFile(fileOf('0123456789', saved.lastModified + 1), saved)).toBe(false)
  })
})
