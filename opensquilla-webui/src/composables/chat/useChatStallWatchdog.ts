import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import { taskTerminalStatus } from '@/utils/chat/streamEvents'

// Soft content-silence watchdog for the live chat stream.
//
// The hard idle timeout in useChatStream (~210s) ends the turn when NO events
// arrive at all — but a wedged provider call keeps the run "alive" through
// session.event.run_heartbeat (~15s cadence), so the hard timeout never fires
// while nothing useful is happening. This watchdog measures silence of CONTENT
// events only (text/thinking/tool/router frames); heartbeats and transport
// ticks deliberately do not reset it. Crossing the threshold raises a
// dismissible banner offering to keep waiting or interrupt the turn.
//
// Two false-positive gates suspend the watchdog entirely:
//  - tool-in-flight: a tool_use_start without its matching tool_result means a
//    long tool execution may legitimately emit nothing for minutes.
//  - approval-pending: an unresolved exec/plugin approval blocks the run on
//    the human, not the provider.

export const SOFT_STALL_THRESHOLD_MS = 90_000
// After "keep waiting", the banner stays hidden for this long, then re-arms.
export const STALL_REARM_DELAY_MS = 30_000
const CHECK_INTERVAL_MS = 1_000
// text_delta bursts arrive many times a second; while the banner is down a
// re-check can wait for the 1s ticker, so evaluations this close are skipped.
const EVALUATE_MIN_INTERVAL_MS = 500

// Events that prove the provider/agent is actually making progress. Everything
// outside this set (run_heartbeat, state_change, transport ticks, …) is
// liveness-only and must NOT reset the content-silence clock.
const CONTENT_EVENTS = new Set([
  'session.event.text_delta',
  'session.event.thinking',
  'session.event.tool_use_start',
  'session.event.tool_use_delta',
  'session.event.tool_result',
  'session.event.router_decision',
  // Long compaction or ensemble phases emit only these frames; they prove
  // forward progress and must keep the banner down.
  'session.event.compaction',
  'session.event.ensemble_progress',
])

const APPROVAL_REQUESTED_EVENTS = new Set([
  'exec.approval.requested',
  'plugin.approval.requested',
])

const APPROVAL_RESOLVED_EVENTS = new Set([
  'exec.approval.resolved',
  'plugin.approval.resolved',
])

export type StallSuspendReason = 'tool-running' | 'approval-pending' | null

export interface UseChatStallWatchdogOptions {
  /** Live-turn flag from useChatStream; the watchdog only runs while true. */
  isStreaming: Ref<boolean>
  /** Injectable clock for tests; defaults to Date.now. */
  now?: () => number
}

function payloadToolId(payload: Record<string, unknown>): string {
  const id = payload.tool_use_id ?? payload.toolUseId ?? payload.id
  return typeof id === 'string' ? id : ''
}

function payloadApprovalId(payload: Record<string, unknown>): string {
  const id = payload.approval_id ?? payload.approvalId
  return typeof id === 'string' ? id : ''
}

// Terminal events end the turn, so the banner clears and per-turn tracking
// resets. Mirrors handleRpcAny's terminal detection: `*.done` / `chat.done` /
// `*.error` plus TaskRuntime terminals (via the shared taskTerminalStatus
// helper); task_group frames are mid-turn checkpoints, not turn terminals,
// and are excluded upstream.
function isTerminalEvent(event: string): boolean {
  if (event.endsWith('.done') || event === 'chat.done') return true
  if (event.endsWith('.error')) return true
  return taskTerminalStatus(event) !== ''
}

export function useChatStallWatchdog(options: UseChatStallWatchdogOptions) {
  const now = options.now ?? (() => Date.now())

  const stallActive = ref(false)
  const stallSeconds = ref(0)
  const pendingToolIds = ref<ReadonlySet<string>>(new Set())
  const pendingApprovalIds = ref<ReadonlySet<string>>(new Set())
  // Epoch ms until which a "keep waiting" dismissal keeps the banner hidden.
  const dismissedUntil = ref(0)
  let lastContentAt = now()
  let lastEvaluatedAt = 0
  let ticker: ReturnType<typeof setInterval> | null = null

  // Approval-pending wins when both gates hold: a blocked approval usually
  // coincides with an unresolved tool call, and the human is the root cause.
  const suspendReason = computed<StallSuspendReason>(() => {
    if (pendingApprovalIds.value.size > 0) return 'approval-pending'
    if (pendingToolIds.value.size > 0) return 'tool-running'
    return null
  })

  function evaluate() {
    lastEvaluatedAt = now()
    if (!options.isStreaming.value || suspendReason.value !== null) {
      stallActive.value = false
      return
    }
    const nowMs = now()
    if (dismissedUntil.value > nowMs) {
      stallActive.value = false
      return
    }
    const silence = nowMs - lastContentAt
    if (silence >= SOFT_STALL_THRESHOLD_MS) {
      stallSeconds.value = Math.floor(silence / 1000)
      stallActive.value = true
    } else {
      stallActive.value = false
    }
  }

  // A content event restarts the silence clock and drops both the banner and
  // any prior dismissal (fresh progress means the next stall is a new episode).
  function noteContent() {
    lastContentAt = now()
    dismissedUntil.value = 0
    // With no banner up, a re-evaluation this soon after the last one cannot
    // change anything — the ticker re-checks within 1s anyway. An active
    // banner always re-evaluates so fresh content clears it immediately.
    if (!stallActive.value && now() - lastEvaluatedAt < EVALUATE_MIN_INTERVAL_MS) return
    evaluate()
  }

  function addTool(id: string) {
    if (!id) return
    const next = new Set(pendingToolIds.value)
    next.add(id)
    pendingToolIds.value = next
  }

  function removeTool(id: string) {
    if (!id || !pendingToolIds.value.has(id)) return
    const next = new Set(pendingToolIds.value)
    next.delete(id)
    pendingToolIds.value = next
  }

  function addApproval(id: string) {
    if (!id) return
    const next = new Set(pendingApprovalIds.value)
    next.add(id)
    pendingApprovalIds.value = next
    evaluate()
  }

  function removeApproval(id: string) {
    if (!id || !pendingApprovalIds.value.has(id)) return
    const next = new Set(pendingApprovalIds.value)
    next.delete(id)
    pendingApprovalIds.value = next
    // The run just unblocked; measure silence from here, not from before the
    // approval, or the banner would fire the instant the human decides.
    lastContentAt = now()
    evaluate()
  }

  // Terminal: the turn is over — clear the banner and all per-turn tracking so
  // a stopped turn's unresolved tools can never suspend the next turn.
  function clearTurn() {
    pendingToolIds.value = new Set()
    pendingApprovalIds.value = new Set()
    dismissedUntil.value = 0
    lastContentAt = now()
    stallActive.value = false
    stallSeconds.value = 0
  }

  /**
   * Feed one gateway event (already filtered to the active session by the
   * caller). Content events reset the silence clock; tool start/result and
   * approval requested/resolved drive the suspension gates; terminals clear;
   * everything else — run_heartbeat above all — is ignored.
   */
  function noteEvent(eventName: string, payload?: unknown) {
    if (typeof eventName !== 'string' || !eventName) return
    const record = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>

    if (APPROVAL_REQUESTED_EVENTS.has(eventName)) {
      addApproval(payloadApprovalId(record))
      return
    }
    if (APPROVAL_RESOLVED_EVENTS.has(eventName)) {
      removeApproval(payloadApprovalId(record))
      return
    }

    // Task-group checkpoints end with `.done`/`.failed` but the turn goes on.
    if (eventName.startsWith('session.event.task_group.')) return

    if (isTerminalEvent(eventName)) {
      clearTurn()
      return
    }

    if (!CONTENT_EVENTS.has(eventName)) return
    if (eventName === 'session.event.tool_use_start') addTool(payloadToolId(record))
    else if (eventName === 'session.event.tool_result') removeTool(payloadToolId(record))
    noteContent()
  }

  /** Full reset (session switch): forget every gate, clock, and dismissal. */
  function reset() {
    clearTurn()
  }

  /** "Keep waiting": hide the banner now and re-arm after the delay. */
  function dismiss() {
    dismissedUntil.value = now() + STALL_REARM_DELAY_MS
    stallActive.value = false
  }

  function stopTicker() {
    if (ticker) {
      clearInterval(ticker)
      ticker = null
    }
  }

  watch(options.isStreaming, streaming => {
    if (streaming) {
      // New turn: silence is measured from the turn start.
      lastContentAt = now()
      dismissedUntil.value = 0
      stallActive.value = false
      if (!ticker) ticker = setInterval(evaluate, CHECK_INTERVAL_MS)
    } else {
      stopTicker()
      stallActive.value = false
      dismissedUntil.value = 0
      // Unfinished tools and approvals from an ended turn must not suspend the
      // next one — a missed approval.resolved (e.g. across a WS reconnect)
      // would otherwise gate the watchdog forever.
      pendingToolIds.value = new Set()
      pendingApprovalIds.value = new Set()
    }
  }, { immediate: true })

  onScopeDispose(stopTicker)

  return {
    stallActive,
    stallSeconds,
    suspendReason,
    noteEvent,
    reset,
    dismiss,
  }
}
