import { reactive, ref, watch, type Ref } from 'vue'
import type { RpcEventHandler } from '@/lib/rpc'
import type {
  MetaPreflightPayload,
  MetaRunAnnouncedPayload,
  MetaRunCompletedPayload,
  MetaStepStatePayload,
  SessionEventPayload,
} from '@/types/rpc'
import { isCurrentSessionPayload, isStaleEpoch } from '@/utils/chat/streamEvents'
import {
  completeRun,
  createRibbon,
  updateStep,
  type MetaRibbonState,
} from '@/utils/chat/metaRibbon'
import {
  createPreflight,
  skillDisplayName,
  type MetaPreflightState,
} from '@/utils/chat/metaPreflight'
import type {
  MetaPreflightActionPayload,
  MetaPreflightPhase,
} from '@/components/chat/MetaPreflightCard.vue'

/**
 * Self-contained controller for the MetaSkill run UI, mirroring
 * useChatApprovals. Owns the four `session.event.meta_*` subscriptions, the
 * per-run_id state Maps, the action handlers, and the confirm/replay RPC.
 *
 * Seq gating: the `*` wildcard (handleRpcAny) advances the shared lastStreamSeq
 * for every session.event.* and runs AFTER these exact meta handlers, so this
 * controller must NOT call acceptStreamSeq (advancing twice would drop the next
 * frame). Instead gatePayload reads the pre-frame cursor read-only and drops
 * stale/duplicate frames (seq <= lastStreamSeq) — without this, a replayed
 * meta_run_announced (e.g. on reconnect) would recreate the ribbon and reset it
 * to all-pending. It also gates on isStaleEpoch + isCurrentSessionPayload and
 * is a no-op on an unknown run_id (preserved from the vanilla modules).
 */

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
  on: (event: string, handler: RpcEventHandler) => () => void
}

export interface MetaPreflightEntry {
  state: MetaPreflightState
  phase: MetaPreflightPhase
  errorText: string
}

export interface UseMetaRunsOptions {
  rpc: RpcClient
  sessionKey: Ref<string>
  currentEpoch: Ref<number>
  /**
   * Shared stream-seq cursor (the same ref advanced by handleRpcAny for every
   * session.event.*). Used read-only here to drop stale/duplicate meta frames.
   */
  lastStreamSeq: Ref<number>
  /**
   * Send the hidden preflight confirmation (provider text with markers +
   * visible bubble text). Wired from ChatView's send path.
   */
  sendHiddenConfirmation: (
    confirmed: { message?: string } | null,
    detail: {
      runId: string
      metaSkillName: string
      interpretedRequest: string
      language: string
    },
  ) => void
  /** Scroll the in-thread step card for a chip click into view. */
  scrollToStepCard: (stepId: string) => void
  /**
   * Refill the composer with `text` and fire the send path (mirrors vanilla's
   * retry/replay tail: `_textarea.value = text; _autoResizeTextarea(); _onSend()`).
   */
  sendComposerText: (text: string) => void
  /** The most recent user message text (mirrors vanilla `_latestUserMessageText`). */
  lastUserMessageText: () => string
  /** Composer affordances (placeholder hint + focus) for switch-skill. */
  setComposerPlaceholder?: (text: string) => void
  focusComposer?: () => void
  pushToast: (message: string, options?: { tone?: 'info' | 'danger'; duration?: number }) => void
}

export function useMetaRuns(options: UseMetaRunsOptions) {
  const { rpc, sessionKey, currentEpoch, lastStreamSeq } = options

  // Reactive Maps keyed by run_id. ribbonOrder keeps render order stable.
  const ribbons = ref<Map<string, MetaRibbonState>>(new Map())
  const preflights = ref<Map<string, MetaPreflightEntry>>(new Map())
  const ribbonOrder = ref<string[]>([])

  function noteRunId(runId: string) {
    if (!runId) return
    if (!ribbonOrder.value.includes(runId)) ribbonOrder.value = [...ribbonOrder.value, runId]
  }

  function gatePayload(payload: SessionEventPayload | null | undefined): boolean {
    if (!payload || typeof payload !== 'object') return false
    if (isStaleEpoch(payload, currentEpoch.value)) return false
    if (!isCurrentSessionPayload(payload, sessionKey.value)) return false
    // Drop stale/duplicate stream frames (e.g. replayed on reconnect). Without
    // this, a re-delivered meta_run_announced would reset the ribbon to
    // all-pending and lose progress. The wildcard handleRpcAny advances
    // lastStreamSeq for every session.event.* and runs AFTER the exact meta
    // handlers, so we read the pre-frame cursor here (read-only, never advance).
    // Frames without a numeric stream_seq are accepted, matching acceptStreamSeq.
    const seq = payload.stream_seq
    if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastStreamSeq.value) return false
    return true
  }

  /* ── Event handlers ──────────────────────────────────────────────── */

  function onPreflight(payload: MetaPreflightPayload) {
    if (!gatePayload(payload)) return
    const state = reactive(createPreflight(payload)) as MetaPreflightState
    if (!state.runId) return
    noteRunId(state.runId)
    const next = new Map(preflights.value)
    next.set(state.runId, { state, phase: 'ready', errorText: '' })
    preflights.value = next
  }

  function onRunAnnounced(payload: MetaRunAnnouncedPayload) {
    if (!gatePayload(payload)) return
    const ribbon = reactive(createRibbon(payload)) as MetaRibbonState
    if (!ribbon.runId) return
    noteRunId(ribbon.runId)
    const next = new Map(ribbons.value)
    next.set(ribbon.runId, ribbon)
    ribbons.value = next
    // The run started: collapse the preflight checkpoint into a running line.
    const entry = preflights.value.get(ribbon.runId)
    if (entry && entry.phase !== 'cancelled') setPreflightPhase(ribbon.runId, 'running')
  }

  function onStepState(payload: MetaStepStatePayload) {
    if (!gatePayload(payload)) return
    const runId = payload.run_id || ''
    const ribbon = ribbons.value.get(runId)
    if (!ribbon) return // out-of-order / unknown run — tolerate
    updateStep(ribbon, payload)
  }

  function onRunCompleted(payload: MetaRunCompletedPayload) {
    if (!gatePayload(payload)) return
    const runId = payload.run_id || ''
    const ribbon = ribbons.value.get(runId)
    if (!ribbon) return
    completeRun(ribbon, payload)
  }

  /* ── Phase helpers ───────────────────────────────────────────────── */

  function setPreflightPhase(runId: string, phase: MetaPreflightPhase, errorText = '') {
    const entry = preflights.value.get(runId)
    if (!entry) return
    const next = new Map(preflights.value)
    next.set(runId, { ...entry, phase, errorText })
    preflights.value = next
  }

  /* ── Action handlers ─────────────────────────────────────────────── */

  async function onPreflightAction(payload: MetaPreflightActionPayload) {
    const { action, runId } = payload
    const entry = preflights.value.get(runId)
    if (!entry) return

    if (action === 'dismiss') {
      setPreflightPhase(runId, 'cancelled')
      return
    }

    // continue / defaults both confirm the preflight then fire the hidden send.
    setPreflightPhase(runId, 'submitting')
    let confirmed: { message?: string } | null = null
    try {
      confirmed = await rpc.call<{ message?: string }>('meta.runs.confirm_preflight', {
        sessionKey: sessionKey.value,
        runId,
        run_id: runId,
        // The server feeds interpretedRequest into confirmation_message() so the
        // authored confirmation carries the interpreted-request context.
        interpretedRequest: payload.interpretedRequest,
        fields: payload.confirmedFields,
        useDefaults: action === 'defaults',
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setPreflightPhase(runId, 'error', message)
      return
    }
    try {
      options.sendHiddenConfirmation(confirmed, {
        runId,
        metaSkillName: payload.metaSkillName,
        interpretedRequest: payload.interpretedRequest,
        language: entry.state.language,
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setPreflightPhase(runId, 'error', message)
      return
    }
    // A meta_run_announced will flip this to 'running'; until then show submitting.
  }

  // Map a replay-bearing action to the server replay mode (mirrors vanilla
  // `_onMetaRibbonAction`: retry-step → failed-step, retry-with-partial-context
  // → partial-context).
  const REPLAY_MODES: Record<string, string> = {
    'retry-step': 'failed-step',
    'retry-with-partial-context': 'partial-context',
  }

  // Toast-only actions: vanilla surfaces guidance and does NOT call replay.
  const TOAST_ACTIONS: Record<string, string> = {
    'install-dependency': 'Install the missing dependency, then retry this MetaSkill run.',
    'continue-text-only': 'Continue with text outputs only, then retry if an artifact is still needed.',
  }

  async function onRibbonAction(payload: { action: string; stepId: string | null; runId: string }) {
    const { action, runId, stepId } = payload

    if (action === 'retry-run') {
      // Re-send the ORIGINATING user message (vanilla `_retryMetaRibbonRun`):
      // refill the composer with the prior user message and re-send it.
      const text = options.lastUserMessageText()
      if (!text) {
        options.pushToast('No previous message to retry', { tone: 'info' })
        return
      }
      options.sendComposerText(text)
      return
    }

    if (action === 'switch-skill' || action === 'switch-meta-skill') {
      // Hand control back to the composer so the operator can pick a new skill,
      // surfacing the vanilla guidance hint (placeholder if the composer exposes
      // a setter, otherwise via the toast path so it is not silently dropped).
      const hint = '想换哪个 meta-skill？例如：Use meta-skill `meta-kid-project-planner`'
      options.setComposerPlaceholder?.(hint)
      options.focusComposer?.()
      return
    }

    if (action === 'show-detail') {
      // Vanilla expands the target step card (data-expanded='true') before
      // scrolling. The Vue thread keys tool cards by renderKey, not by a
      // meta_step_<id> anchor, so there is no equivalent expand target to set
      // here; scroll the card into view (no-op if it is not yet rendered).
      if (stepId) options.scrollToStepCard(`meta_step_${stepId}`)
      return
    }

    if (action in TOAST_ACTIONS) {
      // install-dependency / continue-text-only are toast-only in vanilla.
      options.pushToast(TOAST_ACTIONS[action], { tone: 'info', duration: 3000 })
      return
    }

    // retry-step, retry-with-partial-context → server replay. The returned
    // replay.message is the text to send: refill the composer and fire the send
    // path so the replay actually runs (vanilla `_replayMetaRibbonRun`).
    const mode = REPLAY_MODES[action] || 'failed-step'
    try {
      const payloadOut = await rpc.call<{ replay?: { message?: string } } & { message?: string }>(
        'meta.runs.replay',
        {
          sessionKey: sessionKey.value,
          runId,
          run_id: runId,
          mode,
          action,
          stepId: stepId || undefined,
        },
      )
      const replay = payloadOut && payloadOut.replay ? payloadOut.replay : payloadOut
      const message = replay && replay.message ? replay.message : ''
      if (message) options.sendComposerText(message)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      options.pushToast(`Replay failed — ${message}`, { tone: 'danger' })
    }
  }

  function onChipSelect(payload: { stepId: string; runId: string }) {
    if (!payload.stepId) return
    options.scrollToStepCard(`meta_step_${payload.stepId}`)
  }

  /* ── Subscription lifecycle ──────────────────────────────────────── */

  function subscribe(): () => void {
    const unsubs = [
      rpc.on('session.event.meta_preflight', onPreflight as RpcEventHandler),
      rpc.on('session.event.meta_run_announced', onRunAnnounced as RpcEventHandler),
      rpc.on('session.event.meta_step_state', onStepState as RpcEventHandler),
      rpc.on('session.event.meta_run_completed', onRunCompleted as RpcEventHandler),
    ]
    return () => {
      unsubs.forEach((unsub) => unsub())
    }
  }

  function reset() {
    ribbons.value = new Map()
    preflights.value = new Map()
    ribbonOrder.value = []
  }

  // Session switches clear all per-run state.
  watch(sessionKey, () => reset())

  function cleanup() {
    reset()
  }

  // skillDisplayName is re-exported so ChatView can label the hidden send.
  return {
    ribbons,
    preflights,
    ribbonOrder,
    onPreflightAction,
    onRibbonAction,
    onChipSelect,
    subscribe,
    cleanup,
    skillDisplayName,
  }
}
