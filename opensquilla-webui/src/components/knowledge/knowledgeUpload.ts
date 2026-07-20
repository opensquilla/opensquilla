export const KNOWLEDGE_API_BASE = '/api/v1/knowledge'
export const DEFAULT_UPLOAD_CHUNK_SIZE_BYTES = 16 * 1024 * 1024
export const PREFERRED_UPLOAD_CHUNK_SIZE_BYTES = 4 * 1024 * 1024
export const UPLOAD_STORAGE_KEY = 'opensquilla.knowledge.customer_shared.upload.v1'

export class KnowledgeApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'KnowledgeApiError'
  }
}

export type KnowledgeIndexType = 'fts' | 'vector'
const KNOWLEDGE_INDEX_TYPE_ORDER: readonly KnowledgeIndexType[] = ['fts', 'vector']

export function normalizeKnowledgeIndexTypes(
  indexTypes: KnowledgeIndexType[],
): KnowledgeIndexType[] {
  const selected = new Set(indexTypes)
  const normalized = KNOWLEDGE_INDEX_TYPE_ORDER.filter(indexType => selected.has(indexType))
  if (normalized.length === 0) throw new Error('Select at least one knowledge index')
  return normalized
}

export type KnowledgeJobState = 'queued' | 'running' | 'ready' | 'ready_with_warnings' | 'failed'
export type KnowledgeJobPhase =
  | 'validating'
  | 'extracting'
  | 'parsing'
  | 'fts_indexing'
  | 'vector_indexing'
  | 'complete'

export interface KnowledgeUploadStatus {
  uploadId: string
  filename: string
  sizeBytes: number
  uploadedBytes: number
  indexTypes: KnowledgeIndexType[]
  chunkSizeBytes: number
  jobId: string | null
}

export interface KnowledgeJobUpload {
  uploadedBytes: number
  sizeBytes: number
  percent: number
}

export interface KnowledgeJobFiles {
  total: number
  processed: number
  skipped: number
  failed: number
}

export interface KnowledgeJobChunks {
  total: number
  ftsIndexed: number
  vectorIndexed: number
}

export interface KnowledgeJob {
  jobId: string
  uploadId: string
  state: KnowledgeJobState
  phase: KnowledgeJobPhase
  overallProgress: number
  upload: KnowledgeJobUpload
  files: KnowledgeJobFiles
  chunks: KnowledgeJobChunks
  warnings: string[]
  error: { code: string; message: string } | null
}

export interface StoredKnowledgeUpload {
  version: 1
  collectionId: 'customer_shared'
  uploadId: string
  jobId: string | null
  filename: string
  sizeBytes: number
  lastModified: number
  indexTypes: KnowledgeIndexType[]
}

export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const JOB_STATES = new Set<KnowledgeJobState>([
  'queued',
  'running',
  'ready',
  'ready_with_warnings',
  'failed',
])
const JOB_PHASES = new Set<KnowledgeJobPhase>([
  'validating',
  'extracting',
  'parsing',
  'fts_indexing',
  'vector_indexing',
  'complete',
])

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function finiteInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value >= 0
    ? value
    : null
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text.trim()) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function errorDetail(payload: unknown): string {
  if (typeof payload === 'string') return payload
  const body = record(payload)
  if (!body) return ''
  const detail = body.detail ?? body.error ?? body.message
  if (typeof detail === 'string') return detail
  const nested = record(detail)
  if (nested && typeof nested.message === 'string') return nested.message
  return ''
}

async function expectJson(
  response: Response,
  expectedStatuses: number[],
): Promise<Record<string, unknown>> {
  const payload = await readResponseBody(response)
  if (!expectedStatuses.includes(response.status)) {
    const detail = errorDetail(payload)
    throw new KnowledgeApiError(
      detail || `Knowledge API request failed (${response.status})`,
      response.status,
    )
  }
  const body = record(payload)
  if (!body) throw new Error('Knowledge API returned an invalid JSON response')
  return body
}

function uploadFromPayload(
  payload: Record<string, unknown>,
  fallback: Partial<KnowledgeUploadStatus> = {},
): KnowledgeUploadStatus {
  const uploadId = nonEmptyString(payload.uploadId) ?? fallback.uploadId
  const filename = nonEmptyString(payload.filename) ?? fallback.filename ?? ''
  const sizeBytes = finiteInteger(payload.sizeBytes) ?? fallback.sizeBytes
  const uploadedBytes = finiteInteger(payload.uploadedBytes) ?? fallback.uploadedBytes ?? 0
  const payloadIndexTypes = validIndexTypes(payload.indexTypes) ? payload.indexTypes : null
  const indexTypes = payloadIndexTypes ?? fallback.indexTypes
  const advertisedChunkSize = finiteInteger(payload.chunkSizeBytes)
  const chunkSizeBytes = advertisedChunkSize && advertisedChunkSize > 0
    ? advertisedChunkSize
    : fallback.chunkSizeBytes ?? DEFAULT_UPLOAD_CHUNK_SIZE_BYTES
  const jobId = nonEmptyString(payload.jobId) ?? fallback.jobId ?? null
  if (!uploadId || !filename || sizeBytes === undefined || uploadedBytes > sizeBytes || !indexTypes) {
    throw new Error('Knowledge API returned an invalid upload status')
  }
  return {
    uploadId,
    filename,
    sizeBytes,
    uploadedBytes,
    indexTypes,
    chunkSizeBytes,
    jobId,
  }
}

export async function createKnowledgeUpload(
  file: File,
  indexTypes: KnowledgeIndexType[],
  fetcher: FetchLike = fetch,
): Promise<KnowledgeUploadStatus> {
  const normalizedIndexTypes = normalizeKnowledgeIndexTypes(indexTypes)
  const response = await fetcher(`${KNOWLEDGE_API_BASE}/uploads`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      sizeBytes: file.size,
      indexTypes: normalizedIndexTypes,
    }),
  })
  const payload = await expectJson(response, [201])
  return uploadFromPayload(payload, {
    filename: file.name,
    sizeBytes: file.size,
    uploadedBytes: 0,
    indexTypes: normalizedIndexTypes,
  })
}

export async function getKnowledgeUpload(
  uploadId: string,
  fetcher: FetchLike = fetch,
): Promise<KnowledgeUploadStatus> {
  const response = await fetcher(`${KNOWLEDGE_API_BASE}/uploads/${encodeURIComponent(uploadId)}`, {
    credentials: 'same-origin',
  })
  return uploadFromPayload(await expectJson(response, [200]), { uploadId })
}

function offsetFromPatchResponse(response: Response): number | null {
  const header = response.headers.get('Upload-Offset')
  if (header !== null && /^\d+$/.test(header.trim())) return Number(header)
  return null
}

function conflictOffset(payload: unknown): number | null {
  const error = record(record(payload)?.error)
  if (error?.code !== 'upload_offset_mismatch') return null
  return finiteInteger(error.expectedOffset)
}

export async function uploadFileInChunks(
  file: File,
  initial: KnowledgeUploadStatus,
  options: {
    fetcher?: FetchLike
    signal?: AbortSignal
    onProgress?: (status: KnowledgeUploadStatus) => void
  } = {},
): Promise<KnowledgeUploadStatus> {
  const fetcher = options.fetcher ?? fetch
  let status = initial
  let offset = initial.uploadedBytes
  let unchangedConflicts = 0
  if (initial.sizeBytes !== file.size) throw new Error('Selected file size does not match the upload')

  while (offset < file.size) {
    const requestChunkSize = Math.min(
      status.chunkSizeBytes,
      PREFERRED_UPLOAD_CHUNK_SIZE_BYTES,
    )
    const end = Math.min(file.size, offset + requestChunkSize)
    const chunk = file.slice(offset, end)
    const response = await fetcher(
      `${KNOWLEDGE_API_BASE}/uploads/${encodeURIComponent(status.uploadId)}`,
      {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/octet-stream',
          'Upload-Offset': String(offset),
        },
        body: chunk,
        signal: options.signal,
      },
    )

    if (response.status === 409) {
      const payload = await readResponseBody(response)
      const expectedOffset = conflictOffset(payload)
      const recovered = expectedOffset === null
        ? await getKnowledgeUpload(status.uploadId, fetcher)
        : { ...status, uploadedBytes: expectedOffset }
      if (recovered.uploadedBytes === offset) unchangedConflicts += 1
      else unchangedConflicts = 0
      if (unchangedConflicts >= 3) throw new Error('Upload offset conflict could not be resolved')
      if (recovered.uploadedBytes > file.size) throw new Error('Server upload offset exceeds file size')
      status = recovered
      offset = recovered.uploadedBytes
      options.onProgress?.(status)
      continue
    }

    const payload = await readResponseBody(response)
    if (response.status !== 200) {
      const detail = errorDetail(payload)
      throw new Error(detail || `Knowledge upload failed (${response.status})`)
    }
    const body = record(payload)
    if (!body) throw new Error('Knowledge API returned an invalid upload response')
    const patched = uploadFromPayload(body, status)
    const nextOffset = offsetFromPatchResponse(response)
    if (
      nextOffset === null
      || nextOffset !== patched.uploadedBytes
      || nextOffset <= offset
      || nextOffset > file.size
    ) {
      throw new Error('Knowledge API returned an invalid upload offset')
    }
    offset = nextOffset
    status = patched
    options.onProgress?.(status)
  }
  return status
}

export async function completeKnowledgeUpload(
  uploadId: string,
  fetcher: FetchLike = fetch,
): Promise<{ uploadId: string; jobId: string; state: KnowledgeJobState }> {
  const response = await fetcher(
    `${KNOWLEDGE_API_BASE}/uploads/${encodeURIComponent(uploadId)}/complete`,
    { method: 'POST', credentials: 'same-origin' },
  )
  const payload = await expectJson(response, [202])
  const returnedUploadId = nonEmptyString(payload.uploadId)
  const jobId = nonEmptyString(payload.jobId)
  const state = payload.state
  if (!returnedUploadId || !jobId || typeof state !== 'string' || !JOB_STATES.has(state as KnowledgeJobState)) {
    throw new Error('Knowledge API returned an invalid completion response')
  }
  return { uploadId: returnedUploadId, jobId, state: state as KnowledgeJobState }
}

export function parseKnowledgeJob(payload: unknown): KnowledgeJob {
  const body = record(payload)
  const jobId = nonEmptyString(body?.jobId)
  const uploadId = nonEmptyString(body?.uploadId)
  const state = body?.state
  const phase = body?.phase
  const overallProgress = typeof body?.overallProgress === 'number' && Number.isFinite(body.overallProgress)
    ? body.overallProgress
    : null
  if (
    !body
    || !jobId
    || !uploadId
    || typeof state !== 'string'
    || !JOB_STATES.has(state as KnowledgeJobState)
    || typeof phase !== 'string'
    || !JOB_PHASES.has(phase as KnowledgeJobPhase)
    || overallProgress === null
    || overallProgress < 0
    || overallProgress > 100
  ) {
    throw new Error('Knowledge API returned an invalid job status')
  }
  const warnings = Array.isArray(body.warnings)
    && body.warnings.every((item): item is string => typeof item === 'string')
    ? body.warnings
    : null
  const upload = record(body.upload)
  const files = record(body.files)
  const chunks = record(body.chunks)
  const errorRecord = body.error === null ? null : record(body.error)
  const errorCode = nonEmptyString(errorRecord?.code)
  const errorMessage = nonEmptyString(errorRecord?.message)
  const parsedError = errorCode && errorMessage
    ? { code: errorCode, message: errorMessage }
    : null
  const jobUpload = upload && {
    uploadedBytes: finiteInteger(upload.uploadedBytes),
    sizeBytes: finiteInteger(upload.sizeBytes),
    percent: typeof upload.percent === 'number' && Number.isFinite(upload.percent)
      ? upload.percent
      : null,
  }
  const jobFiles = files && {
    total: finiteInteger(files.total),
    processed: finiteInteger(files.processed),
    skipped: finiteInteger(files.skipped),
    failed: finiteInteger(files.failed),
  }
  const jobChunks = chunks && {
    total: finiteInteger(chunks.total),
    ftsIndexed: finiteInteger(chunks.ftsIndexed),
    vectorIndexed: finiteInteger(chunks.vectorIndexed),
  }
  if (
    !warnings
    || !jobUpload
    || jobUpload.uploadedBytes === null
    || jobUpload.sizeBytes === null
    || jobUpload.uploadedBytes > jobUpload.sizeBytes
    || jobUpload.percent === null
    || jobUpload.percent < 0
    || jobUpload.percent > 100
    || !jobFiles
    || Object.values(jobFiles).some(value => value === null)
    || !jobChunks
    || Object.values(jobChunks).some(value => value === null)
    || (body.error !== null && !parsedError)
  ) {
    throw new Error('Knowledge API returned invalid job details')
  }
  return {
    jobId,
    uploadId,
    state: state as KnowledgeJobState,
    phase: phase as KnowledgeJobPhase,
    overallProgress,
    upload: jobUpload as KnowledgeJobUpload,
    files: jobFiles as KnowledgeJobFiles,
    chunks: jobChunks as KnowledgeJobChunks,
    warnings,
    error: parsedError,
  }
}

export async function getKnowledgeJob(
  jobId: string,
  fetcher: FetchLike = fetch,
): Promise<KnowledgeJob> {
  const response = await fetcher(`${KNOWLEDGE_API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
    credentials: 'same-origin',
  })
  return parseKnowledgeJob(await expectJson(response, [200]))
}

function validIndexTypes(value: unknown): value is KnowledgeIndexType[] {
  return Array.isArray(value)
    && value.length > 0
    && value.every(item => item === 'fts' || item === 'vector')
    && new Set(value).size === value.length
}

export function loadStoredKnowledgeUpload(storage: Storage = localStorage): StoredKnowledgeUpload | null {
  try {
    const raw = storage.getItem(UPLOAD_STORAGE_KEY)
    if (!raw) return null
    const value = record(JSON.parse(raw))
    const uploadId = nonEmptyString(value?.uploadId)
    const filename = nonEmptyString(value?.filename)
    const sizeBytes = finiteInteger(value?.sizeBytes)
    const lastModified = finiteInteger(value?.lastModified)
    if (
      value?.version !== 1
      || value.collectionId !== 'customer_shared'
      || !uploadId
      || !filename
      || sizeBytes === null
      || lastModified === null
      || !validIndexTypes(value.indexTypes)
    ) return null
    return {
      version: 1,
      collectionId: 'customer_shared',
      uploadId,
      jobId: nonEmptyString(value.jobId),
      filename,
      sizeBytes,
      lastModified,
      indexTypes: value.indexTypes,
    }
  } catch {
    return null
  }
}

export function saveStoredKnowledgeUpload(
  value: StoredKnowledgeUpload,
  storage: Storage = localStorage,
) {
  storage.setItem(UPLOAD_STORAGE_KEY, JSON.stringify(value))
}

export function clearStoredKnowledgeUpload(storage: Storage = localStorage) {
  storage.removeItem(UPLOAD_STORAGE_KEY)
}

export function matchesStoredFile(file: File, stored: StoredKnowledgeUpload): boolean {
  return file.name === stored.filename
    && file.size === stored.sizeBytes
    && file.lastModified === stored.lastModified
}
