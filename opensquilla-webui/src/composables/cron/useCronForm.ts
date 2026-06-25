import { computed, nextTick, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import { useToasts } from '@/composables/useToasts'
import type { CronJob, CronJobFormModel, CronPanelTemplate } from '@/types/cron'
import { buildDeliveryFromValues, normalizeDeliveryFields } from '@/utils/cron/delivery'
import { explainCron, nextRuns, parseCron } from '@/utils/cron/schedule'
import { canonicalSessionKey } from '@/utils/chat/sessionKeys'

interface UseCronFormOptions {
  afterSaved: () => void
}

export function useCronForm(options: UseCronFormOptions) {
  const rpc = useRpcStore()
  const route = useRoute()
  const { pushToast } = useToasts()
  const panelOpen = ref(false)
  const editingJob = ref<CronJob | null>(null)
  const cronExplainHuman = ref('Enter a 5-field cron expression to preview')
  const cronExplainValid = ref(false)
  const cronExplainInvalid = ref(false)
  const cronExplainUpcoming = ref<Date[]>([])
  let previewTimer: ReturnType<typeof setTimeout> | null = null

  const form = reactive<CronJobFormModel>({
    name: '',
    type: 'cron',
    cron: '',
    every: '',
    at: '',
    tz: '',
    payloadKind: 'reminder',
    agentId: 'main',
    sessionTarget: 'isolated',
    targetSessionKey: '',
    message: '',
    wakeMode: 'now',
    deliveryMode: '',
    deliveryChannel: '',
    deliveryTo: '',
    deliveryAccount: '',
    deliveryWebhookUrl: '',
    deliveryWebhookToken: '',
    deliveryBestEffort: false,
    fdMode: '',
    fdChannel: '',
    fdTo: '',
    fdAccount: '',
    fdWebhookUrl: '',
    fdWebhookToken: '',
    enabled: true,
  })

  const jobModeHint = computed(() => {
    if (form.payloadKind === 'system_event') return 'System events append text to the agent main session and wake the heartbeat.'
    if (form.payloadKind === 'reminder') return 'Static reminders deliver this message directly; no model call or scheduled agent turn is created.'
    return 'Agent tasks run as scheduled turns and use the selected session target.'
  })

  const sessionTargetHint = computed(() => {
    if (form.payloadKind === 'system_event') return 'Main is locked for system events. Use Static Reminder for direct reminders.'
    if (form.payloadKind === 'reminder') return 'Static reminders run isolated and deliver back to the originating chat when one is available.'
    if (form.sessionTarget === 'current') return 'The scheduled agent task continues in the active chat session.'
    if (form.sessionTarget === 'isolated') return 'The scheduled agent task runs in its own cron session, separate from Main.'
    if (form.sessionTarget === 'session') return 'The scheduled agent task continues in the named session key.'
    return 'Choose where this background agent task keeps its conversation context.'
  })

  const showTargetSessionRow = computed(() => form.payloadKind === 'agent_turn' && (form.sessionTarget === 'current' || form.sessionTarget === 'session'))
  const targetSessionLabel = computed(() => form.sessionTarget === 'current' ? 'Current session key' : 'Named session key')
  const targetSessionHint = computed(() => form.sessionTarget === 'current'
    ? 'Current is bound to the active WebChat session key when the job is saved.'
    : 'Use a full session key from the chat header.')
  const messageLabel = computed(() => {
    if (form.payloadKind === 'system_event') return 'Event text'
    if (form.payloadKind === 'reminder') return 'Reminder text'
    return 'Task prompt'
  })

  function openPanel(job: CronJob | null, template?: CronPanelTemplate) {
    editingJob.value = job
    panelOpen.value = true
    const tpl = template || {}
    const payloadKind = job ? (job.payloadKind || 'agent_turn') : (tpl.payloadKind || 'reminder')
    const sessionTarget = job
      ? (job.sessionTarget || job.session_target || 'isolated')
      : (tpl.sessionTarget || (payloadKind === 'system_event' ? 'main' : 'isolated'))

    form.name = job ? (job.name || '') : (tpl.name || '')
    form.message = job ? (job.message || job.prompt || '') : (tpl.message || '')
    form.type = job ? (job.scheduleKind || job.schedule_kind || 'cron') : (tpl.scheduleKind || tpl.schedule_kind || 'cron')
    form.cron = job ? (job.expression || '') : (tpl.expression || '')
    form.enabled = job ? !!job.enabled : true
    form.agentId = job ? (job.agentId || 'main') : (tpl.agentId || 'main')
    form.payloadKind = payloadKind
    form.sessionTarget = sessionTarget
    form.targetSessionKey = job ? jobSessionKey(job) : (tpl.targetSessionKey || activeChatSessionKey() || '')
    form.every = form.type === 'every' ? (job ? (job.scheduleRaw || job.schedule_raw || '') : String(tpl.every_seconds || '')) : ''
    form.at = form.type === 'at' ? (job ? (job.scheduleRaw || job.schedule_raw || '') : (tpl.at || '')) : ''
    form.tz = job ? (job.tz || '') : (tpl.tz || '')
    form.wakeMode = job ? (job.wakeMode || job.wake_mode || 'now') : (tpl.wakeMode || 'now')

    Object.assign(form, normalizeDeliveryFields(job))
    onPayloadKindChange()
    renderCronExplain(form.cron)
    nextTick(() => document.getElementById('cp-name')?.focus())
  }

  function closePanel() {
    panelOpen.value = false
    editingJob.value = null
  }

  function onPayloadKindChange() {
    if (form.payloadKind === 'system_event') {
      form.sessionTarget = 'main'
    } else if (form.payloadKind === 'reminder') {
      form.sessionTarget = 'isolated'
    } else {
      const active = activeChatSessionKey()
      if (active && !form.targetSessionKey.trim()) form.targetSessionKey = active
      if (form.sessionTarget === 'current' && !form.targetSessionKey.trim()) form.targetSessionKey = active || jobSessionKey(editingJob.value)
    }
  }

  function onSessionTargetChange() {
    if (form.payloadKind !== 'agent_turn') return
    if (form.sessionTarget === 'current' && !form.targetSessionKey.trim()) {
      form.targetSessionKey = activeChatSessionKey() || jobSessionKey(editingJob.value)
    }
  }

  function applyPreset(cron: string) {
    form.cron = cron
    renderCronExplain(cron)
    nextTick(() => document.getElementById('cp-cron')?.focus())
  }

  function renderCronExplain(expr: string) {
    const trimmed = expr.trim()
    if (!trimmed) {
      cronExplainValid.value = false
      cronExplainInvalid.value = false
      cronExplainHuman.value = 'Enter a 5-field cron expression to preview'
      cronExplainUpcoming.value = []
      return
    }
    const parsed = parseCron(trimmed)
    if (!parsed) {
      cronExplainValid.value = false
      cronExplainInvalid.value = true
      cronExplainHuman.value = 'Could not parse expression — expected 5 fields (m h dom mon dow).'
      cronExplainUpcoming.value = []
      return
    }
    cronExplainInvalid.value = false
    cronExplainValid.value = true
    cronExplainHuman.value = explainCron(trimmed) || 'matches a custom cadence'
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = setTimeout(() => {
      cronExplainUpcoming.value = nextRuns(parsed, 3)
    }, 60)
  }

  async function saveJob() {
    const name = form.name.trim()
    if (!name) {
      pushToast('Name is required', { tone: 'danger' })
      return
    }
    const payloadKind = form.payloadKind
    const sessionTarget = payloadKind === 'system_event'
      ? 'main'
      : payloadKind === 'reminder'
        ? 'isolated'
        : form.sessionTarget
    const payload: Record<string, unknown> = {
      name,
      enabled: form.enabled,
      payloadKind,
      agentId: form.agentId.trim() || 'main',
      sessionTarget,
      text: form.message.trim(),
    }

    if (form.type === 'cron') {
      payload.schedule = { kind: 'cron', expr: form.cron.trim() }
    } else if (form.type === 'every') {
      const everySeconds = Number(form.every)
      if (!Number.isInteger(everySeconds) || everySeconds < 1) {
        pushToast('Interval must be an integer number of seconds', { tone: 'danger' })
        return
      }
      payload.schedule = { kind: 'every', every_seconds: everySeconds }
    } else if (form.type === 'at') {
      const at = form.at.trim()
      if (!at) {
        pushToast('ISO time is required', { tone: 'danger' })
        return
      }
      payload.schedule = { kind: 'at', at }
    }

    const tz = form.tz.trim()
    if (tz) {
      payload.tz = tz
      const sched = payload.schedule as Record<string, unknown>
      if (sched?.kind === 'cron') sched.tz = tz
    }
    if (form.wakeMode && form.wakeMode !== 'now') payload.wakeMode = form.wakeMode

    const deliveryResult = buildDeliveryFromValues({
      deliveryMode: form.deliveryMode,
      deliveryChannel: form.deliveryChannel,
      deliveryTo: form.deliveryTo,
      deliveryAccount: form.deliveryAccount,
      deliveryWebhookUrl: form.deliveryWebhookUrl,
      deliveryWebhookToken: form.deliveryWebhookToken,
      deliveryBestEffort: form.deliveryBestEffort,
      fdMode: form.fdMode,
      fdChannel: form.fdChannel,
      fdTo: form.fdTo,
      fdAccount: form.fdAccount,
      fdWebhookUrl: form.fdWebhookUrl,
      fdWebhookToken: form.fdWebhookToken,
    })
    if (deliveryResult.error) {
      pushToast(deliveryResult.error, { tone: 'danger' })
      return
    }
    if (deliveryResult.delivery !== null) payload.delivery = deliveryResult.delivery

    const targetSessionKey = form.targetSessionKey.trim()
    if (sessionTarget === 'current') {
      const boundSessionKey = targetSessionKey || activeChatSessionKey() || jobSessionKey(editingJob.value)
      if (!boundSessionKey) {
        pushToast('Current session key is required', { tone: 'danger' })
        return
      }
      payload.sessionKey = boundSessionKey
      payload.targetSessionKey = boundSessionKey
      payload.originSessionKey = boundSessionKey
    }
    if (payloadKind === 'reminder' && activeChatSessionKey()) payload.originSessionKey = activeChatSessionKey()
    if (sessionTarget === 'session') {
      if (!targetSessionKey) {
        pushToast('Named session key is required', { tone: 'danger' })
        return
      }
      payload.targetSessionKey = targetSessionKey
    }

    if (editingJob.value) payload.id = editingJob.value.id
    try {
      await rpc.call(editingJob.value ? 'cron.update' : 'cron.create', payload)
      pushToast(editingJob.value ? 'Schedule updated' : 'Schedule created', { tone: 'ok' })
      closePanel()
      options.afterSaved()
    } catch (err) {
      pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
    }
  }

  onUnmounted(() => {
    if (previewTimer) clearTimeout(previewTimer)
  })

  return {
    panelOpen,
    editingJob,
    form,
    cronExplainHuman,
    cronExplainValid,
    cronExplainInvalid,
    cronExplainUpcoming,
    jobModeHint,
    sessionTargetHint,
    showTargetSessionRow,
    targetSessionLabel,
    targetSessionHint,
    messageLabel,
    openPanel,
    closePanel,
    onPayloadKindChange,
    onSessionTargetChange,
    applyPreset,
    renderCronExplain,
    saveJob,
  }

  function activeChatSessionKey(): string {
    const routeSession = typeof route.query.session === 'string' ? canonicalOptionalSessionKey(route.query.session) : ''
    if (routeSession) return routeSession
    try {
      return canonicalOptionalSessionKey(localStorage.getItem('opensquilla_active_session') || '')
    } catch {
      return ''
    }
  }
}

export function jobSessionKey(job: CronJob | null): string {
  if (!job) return ''
  return job.originSessionKey ||
    job.origin_session_key ||
    job.targetSessionKey ||
    job.target_session_key ||
    job.sessionKey ||
    job.session_key ||
    ''
}

function canonicalOptionalSessionKey(key: string): string {
  const value = key.trim()
  return value ? canonicalSessionKey(value) : ''
}
