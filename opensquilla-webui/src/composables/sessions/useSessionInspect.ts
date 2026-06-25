import { ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import type { ChatHistoryMessage, ChatHistoryResponse } from '@/types/rpc'

// There is deliberately no sessions.get RPC; the inspect drawer composes
// sessions.preview (summary snippet) with chat.history (transcript pages).

export interface SessionInspectPreview {
  key: string
  title: string
  lastMessage: string
  updatedAt: number | null
}

interface RawPreviewRow {
  key?: string
  title?: string
  lastMessage?: string
  updatedAt?: number
}

interface SessionsPreviewResponse {
  previews?: RawPreviewRow[]
}

interface SessionsAbortResponse {
  aborted?: boolean
  key?: string
}

export const SESSION_INSPECT_PAGE_SIZE = 20

function transcriptMessageKey(msg: ChatHistoryMessage): string {
  return String(msg.message_id || msg.id || `${msg.role || ''}:${msg.timestamp ?? msg.ts ?? ''}:${msg.text || ''}`)
}

export function useSessionInspect() {
  const rpc = useRpcStore()
  const preview = ref<SessionInspectPreview | null>(null)
  const messages = ref<ChatHistoryMessage[]>([])
  const hasEarlier = ref(false)
  const loading = ref(false)
  const loadingEarlier = ref(false)
  const transcriptError = ref(false)

  let oldestCursor: string | number | null = null
  let requestSeq = 0
  let currentKey = ''

  async function fetchPreview(key: string, seq: number) {
    try {
      const data = await rpc.call<SessionsPreviewResponse>('sessions.preview', { keys: [key] })
      if (seq !== requestSeq) return
      const rows = data?.previews || []
      const row = rows.find(item => item.key === key) || rows[0] || null
      const updatedAt = row?.updatedAt != null ? Number(row.updatedAt) : NaN
      preview.value = row
        ? {
            key: String(row.key || key),
            title: String(row.title || ''),
            lastMessage: String(row.lastMessage || ''),
            updatedAt: Number.isFinite(updatedAt) ? updatedAt : null,
          }
        : null
    } catch {
      // Preview is a summary garnish; header data falls back to the ledger
      // row and transcript failures are surfaced separately.
      if (seq === requestSeq) preview.value = null
    }
  }

  async function fetchTranscript(key: string, seq: number, before?: string | number | null) {
    const params: Record<string, unknown> = {
      sessionKey: key,
      limit: SESSION_INSPECT_PAGE_SIZE,
      includeCanonical: false,
      includeSummaries: false,
    }
    if (before != null) params.before = before
    const data = await rpc.call<ChatHistoryResponse>('chat.history', params)
    if (seq !== requestSeq) return
    const page = data?.messages || []
    hasEarlier.value = Boolean(data?.has_more ?? data?.hasMore)
    oldestCursor = data?.oldest_cursor ?? data?.oldestCursor ?? null
    if (before != null) {
      const seen = new Set(messages.value.map(transcriptMessageKey))
      messages.value = [
        ...page.filter(msg => !seen.has(transcriptMessageKey(msg))),
        ...messages.value,
      ]
    } else {
      messages.value = page
    }
  }

  async function load(key: string) {
    const seq = ++requestSeq
    currentKey = key
    loading.value = true
    transcriptError.value = false
    preview.value = null
    messages.value = []
    hasEarlier.value = false
    oldestCursor = null
    try {
      await rpc.waitForConnection()
      if (seq !== requestSeq) return
      const [, transcript] = await Promise.allSettled([
        fetchPreview(key, seq),
        fetchTranscript(key, seq),
      ])
      if (seq !== requestSeq) return
      if (transcript.status === 'rejected') transcriptError.value = true
    } catch {
      if (seq === requestSeq) transcriptError.value = true
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  async function loadEarlier() {
    if (!hasEarlier.value || loadingEarlier.value || loading.value || !currentKey) return
    const seq = requestSeq
    loadingEarlier.value = true
    try {
      await fetchTranscript(currentKey, seq, oldestCursor)
    } catch {
      // Keep the loaded page; the button stays available for another try.
    } finally {
      if (seq === requestSeq) loadingEarlier.value = false
    }
  }

  async function abortSession(key: string): Promise<boolean> {
    const data = await rpc.call<SessionsAbortResponse>('sessions.abort', { key })
    return data?.aborted === true
  }

  function reset() {
    requestSeq++
    currentKey = ''
    preview.value = null
    messages.value = []
    hasEarlier.value = false
    oldestCursor = null
    loading.value = false
    loadingEarlier.value = false
    transcriptError.value = false
  }

  return {
    preview,
    messages,
    hasEarlier,
    loading,
    loadingEarlier,
    transcriptError,
    load,
    loadEarlier,
    abortSession,
    reset,
  }
}
