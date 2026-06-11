import { computed, ref, watch, type Ref } from 'vue'
import type { ChatRunStatus } from '@/types/chat'
import type { ToolResultPayload } from '@/types/rpc'
import type { RpcEventHandler } from '@/lib/rpc'
import { isCurrentSessionPayload } from '@/utils/chat/streamEvents'

const APPROVAL_POLL_INTERVAL_MS = 2000
const MAX_RESOLVED_OUTCOMES = 4

export interface ChatApprovalItem {
  id: string
  namespace: string
  toolName: string
  command: string
  args: Record<string, unknown> | null
  warning: string
  agent: string
  sessionKey: string
}

export type ChatApprovalResolution = 'approved' | 'approved_always' | 'denied'

export interface ChatApprovalEntry {
  approval: ChatApprovalItem
  resolution: ChatApprovalResolution | null
  error: string
}

export type ChatApprovalDecision = 'allow-once' | 'allow-always' | 'deny'

export interface ChatClarifyField {
  name: string
  prompt: string
  type: string
  required: boolean
  defaultValue: string
  choices: string[]
}

export interface ChatClarifyRequest {
  intro: string
  fields: ChatClarifyField[]
  runId: string
  step: string
}

interface ApprovalsSnapshotItem {
  id?: string
  namespace?: string
  toolName?: string
  pluginId?: string
  actionKind?: string
  command?: string
  argv?: unknown
  args?: Record<string, unknown>
  params?: Record<string, unknown>
  warning?: string
  agent?: string
  sessionKey?: string
}

interface ApprovalsSnapshotResponse {
  pending?: ApprovalsSnapshotItem[]
  mode?: string
}

type ApprovalsRpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
  on: (event: string, handler: RpcEventHandler) => () => void
}

export interface UseChatApprovalsOptions {
  rpc: ApprovalsRpcClient
  sessionKey: Ref<string>
  runStatus: Ref<ChatRunStatus>
  /** Deliver a deny note back to the agent through the normal send/queue path. */
  onDenyFeedback?: (note: string) => void
  /** Mirror the gateway-wide pending count (topbar pill / nav badge). */
  onSnapshotCount?: (count: number) => void
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra }
  let token = ''
  try { token = sessionStorage.getItem('opensquilla.wsToken') || '' } catch { /* ignore */ }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

function snapshotItemToApproval(item: ApprovalsSnapshotItem): ChatApprovalItem | null {
  const id = String(item.id || '').trim()
  if (!id) return null
  let command = String(item.command || '')
  if (!command && Array.isArray(item.argv) && item.argv.length > 0) {
    command = item.argv.map(String).join(' ')
  }
  const args = item.args && typeof item.args === 'object' ? item.args : null
  if (!command && args && typeof args.command === 'string') command = args.command
  return {
    id,
    namespace: String(item.namespace || 'exec'),
    toolName: String(item.toolName || item.pluginId || item.actionKind || 'Unknown tool'),
    command,
    args,
    warning: String(item.warning || ''),
    agent: String(item.agent || ''),
    sessionKey: String(item.sessionKey || ''),
  }
}

function parseClarifyRequest(payload: ToolResultPayload): ChatClarifyRequest | null {
  const rawArgs = (payload as Record<string, unknown>).arguments
  if (!rawArgs || typeof rawArgs !== 'object') return null
  const args = rawArgs as Record<string, unknown>
  if (args.kind !== 'user_input' || args.paused !== true) return null
  const schema = args.clarify_schema
  if (!schema || typeof schema !== 'object') return null
  const schemaObj = schema as Record<string, unknown>
  const rawFields = Array.isArray(schemaObj.fields) ? schemaObj.fields : []
  const fields: ChatClarifyField[] = []
  for (const raw of rawFields) {
    if (!raw || typeof raw !== 'object') continue
    const field = raw as Record<string, unknown>
    const name = String(field.name || '').trim()
    if (!name) continue
    fields.push({
      name,
      prompt: String(field.prompt || ''),
      type: String(field.type || 'string').toLowerCase(),
      required: field.required === true,
      defaultValue: field.default == null ? '' : String(field.default),
      choices: Array.isArray(field.choices) ? field.choices.map(String) : [],
    })
  }
  if (fields.length === 0) return null
  return {
    intro: String(schemaObj.intro || ''),
    fields,
    runId: typeof args.run_id === 'string' ? args.run_id : '',
    step: typeof args.step === 'string' ? args.step : '',
  }
}

/**
 * In-thread approvals and clarify requests for the current chat session.
 *
 * Approvals: the gateway pushes `exec.approval.requested` / `.resolved`
 * (and the plugin namespace equivalents) the moment a run blocks or a
 * decision lands; each push triggers an immediate snapshot refresh so the
 * in-thread card appears without waiting on the poll. While the run is
 * blocked on approval (or unresolved cards are on screen) the snapshot is
 * still polled every ~2s as a fallback and filtered to this session.
 * Resolution goes through the existing HTTP resolve endpoint; resolved
 * cards collapse into one-line outcome rows.
 *
 * Clarify: the engine surfaces a pending clarify form as a tool_result whose
 * arguments carry `kind: "user_input", paused: true, clarify_schema`; the
 * card state is derived from that stream event and submitted back through
 * the `chat.clarify_submit` RPC.
 */
export function useChatApprovals(options: UseChatApprovalsOptions) {
  const { rpc, sessionKey, runStatus } = options

  const approvalEntries = ref<ChatApprovalEntry[]>([])
  const approvalBusyIds = ref<Set<string>>(new Set())
  const pendingClarify = ref<ChatClarifyRequest | null>(null)
  const clarifySubmitted = ref(false)
  const clarifyBusy = ref(false)
  const clarifyError = ref('')

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let fetchInFlight = false
  let refetchQueued = false

  const hasUnresolvedApproval = computed(() =>
    approvalEntries.value.some(entry => !entry.resolution))

  function syncSnapshot(pending: ApprovalsSnapshotItem[]) {
    const sessionItems = pending
      .map(snapshotItemToApproval)
      .filter((item): item is ChatApprovalItem =>
        item !== null && !!sessionKey.value && item.sessionKey === sessionKey.value)
    const liveIds = new Set(sessionItems.map(item => item.id))
    // Unresolved cards that vanished from the snapshot were resolved elsewhere
    // (Approvals page, another client) — drop them silently.
    let next = approvalEntries.value.filter(
      entry => entry.resolution !== null || liveIds.has(entry.approval.id))
    const knownIds = new Set(next.map(entry => entry.approval.id))
    for (const item of sessionItems) {
      if (!knownIds.has(item.id)) {
        next = [...next, { approval: item, resolution: null, error: '' }]
      }
    }
    // Cap how many collapsed outcome rows linger in the thread.
    const resolved = next.filter(entry => entry.resolution !== null)
    if (resolved.length > MAX_RESOLVED_OUTCOMES) {
      const dropCount = resolved.length - MAX_RESOLVED_OUTCOMES
      const dropIds = new Set(resolved.slice(0, dropCount).map(entry => entry.approval.id))
      next = next.filter(entry => !dropIds.has(entry.approval.id))
    }
    approvalEntries.value = next
  }

  async function fetchSnapshot() {
    if (fetchInFlight) {
      // A push event landed mid-fetch; the in-flight response may predate
      // it, so run one more fetch when the current one settles.
      refetchQueued = true
      return
    }
    fetchInFlight = true
    try {
      const res = await fetch('/api/approvals', { headers: authHeaders() })
      if (!res.ok) throw new Error('HTTP ' + res.status)
      const data = await res.json() as ApprovalsSnapshotResponse
      const pending = data.pending || []
      options.onSnapshotCount?.(pending.length)
      syncSnapshot(pending)
    } catch (err) {
      console.warn('Approvals snapshot failed: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      fetchInFlight = false
      if (refetchQueued) {
        refetchQueued = false
        void fetchSnapshot()
      }
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPolling() {
    if (pollTimer) return
    void fetchSnapshot()
    pollTimer = setInterval(() => { void fetchSnapshot() }, APPROVAL_POLL_INTERVAL_MS)
  }

  watch(
    () => runStatus.value.status === 'approval_pending' || hasUnresolvedApproval.value,
    shouldPoll => {
      if (shouldPoll) startPolling()
      else stopPolling()
    },
  )

  async function resolveApproval(entry: ChatApprovalEntry, decision: ChatApprovalDecision, note = '') {
    const id = entry.approval.id
    if (approvalBusyIds.value.has(id) || entry.resolution) return
    approvalBusyIds.value = new Set([...approvalBusyIds.value, id])
    entry.error = ''
    const approved = decision !== 'deny'
    const allowAlways = decision === 'allow-always'
    const body = {
      id,
      namespace: entry.approval.namespace || 'exec',
      approved,
      allowAlways,
      rememberIntent: allowAlways,
    }
    try {
      const res = await fetch('/api/approvals/resolve', {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error('HTTP ' + res.status)
      entry.resolution = decision === 'deny' ? 'denied' : allowAlways ? 'approved_always' : 'approved'
      if (decision === 'deny' && note.trim()) options.onDenyFeedback?.(note.trim())
    } catch (err) {
      entry.error = 'Could not resolve — ' + (err instanceof Error ? err.message : String(err))
    } finally {
      const ids = new Set(approvalBusyIds.value)
      ids.delete(id)
      approvalBusyIds.value = ids
    }
  }

  function handleToolResult(payload: ToolResultPayload) {
    if (!payload || typeof payload !== 'object') return
    if (!isCurrentSessionPayload(payload, sessionKey.value)) return
    const request = parseClarifyRequest(payload)
    if (!request) return
    pendingClarify.value = request
    clarifySubmitted.value = false
    clarifyError.value = ''
  }

  /**
   * Gateway approval lifecycle push: refresh the snapshot immediately so
   * the in-thread card (and the gateway-wide pending count) updates
   * without waiting for the next poll tick.
   */
  function handleApprovalPush() {
    void fetchSnapshot()
  }

  /** Register stream listeners; returns the unsubscribe function. */
  function subscribe(): () => void {
    const unsubs = [
      rpc.on('session.event.tool_result', handleToolResult as RpcEventHandler),
      rpc.on('exec.approval.requested', handleApprovalPush as RpcEventHandler),
      rpc.on('exec.approval.resolved', handleApprovalPush as RpcEventHandler),
      rpc.on('plugin.approval.requested', handleApprovalPush as RpcEventHandler),
      rpc.on('plugin.approval.resolved', handleApprovalPush as RpcEventHandler),
    ]
    return () => { unsubs.forEach(unsub => unsub()) }
  }

  async function submitClarify(fields: Record<string, string | boolean>) {
    if (clarifyBusy.value || clarifySubmitted.value || !pendingClarify.value) return
    clarifyBusy.value = true
    clarifyError.value = ''
    const params: Record<string, unknown> = { sessionKey: sessionKey.value, fields }
    if (pendingClarify.value.runId) params.run_id = pendingClarify.value.runId
    try {
      await rpc.call('chat.clarify_submit', params)
      clarifySubmitted.value = true
    } catch (err) {
      clarifyError.value = 'Send failed — ' + (err instanceof Error ? err.message : String(err))
    } finally {
      clarifyBusy.value = false
    }
  }

  function dismissClarify() {
    pendingClarify.value = null
    clarifySubmitted.value = false
    clarifyError.value = ''
  }

  // Session switches reset all in-thread card state; a fresh snapshot check
  // recovers approvals that were already pending (e.g. reload mid-approval).
  watch(sessionKey, key => {
    stopPolling()
    approvalEntries.value = []
    approvalBusyIds.value = new Set()
    dismissClarify()
    if (key) void fetchSnapshot()
  }, { immediate: true })

  function cleanup() {
    stopPolling()
  }

  return {
    approvalEntries,
    approvalBusyIds,
    hasUnresolvedApproval,
    pendingClarify,
    clarifySubmitted,
    clarifyBusy,
    clarifyError,
    resolveApproval,
    submitClarify,
    dismissClarify,
    subscribe,
    cleanup,
  }
}
