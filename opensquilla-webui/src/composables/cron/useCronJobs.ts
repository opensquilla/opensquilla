import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import { useRequest } from '@/composables/useRequest'
import { useToasts } from '@/composables/useToasts'
import type { CronJob } from '@/types/cron'
import { humanCountdown, humanTime } from '@/utils/cron/time'

interface CronListResponse {
  jobs?: CronJob[]
}

export function useCronJobs() {
  const rpc = useRpcStore()
  const { pushToast } = useToasts()
  const searchText = ref('')
  const viewMode = ref<'cards' | 'table'>('cards')
  const runningJobIds = ref<Set<string>>(new Set())
  const sortCol = ref('next_run')
  const sortAsc = ref(true)
  const now = ref(Date.now())

  const { data: cronData, loading, error, refresh } = useRequest<CronListResponse | CronJob[]>(
    'cron.list',
    undefined,
    { errorLabel: 'Failed to load cron jobs' },
  )

  const jobs = computed<CronJob[]>(() => {
    const d = cronData.value
    if (!d) return []
    return Array.isArray(d) ? d : (d.jobs || [])
  })

  let tickInterval: ReturnType<typeof setInterval> | null = null
  let reloadTimer: ReturnType<typeof setTimeout> | null = null
  let unsubRunFinished: (() => void) | null = null

  const enabledCount = computed(() => jobs.value.filter(j => j.enabled).length)
  const pausedCount = computed(() => jobs.value.length - enabledCount.value)
  const reminderCount = computed(() => jobs.value.filter(j => (j.payloadKind || j.payload_kind) === 'reminder').length)
  const agentTaskCount = computed(() => jobs.value.filter(j => (j.payloadKind || j.payload_kind) === 'agent_turn').length)

  const upcomingJobs = computed(() => jobs.value
    .filter(j => isUpcomingRun(j, now.value))
    .map(j => ({ job: j, ts: new Date(j.next_run!).getTime() }))
    .sort((a, b) => a.ts - b.ts))

  const nextJob = computed(() => upcomingJobs.value[0] || null)
  const nextCountdown = computed(() => nextJob.value ? humanCountdown(new Date(nextJob.value.ts), now.value) : '—')
  const nextRunHint = computed(() => nextJob.value
    ? `${nextJob.value.job.name || nextJob.value.job.id} · ${humanTime(new Date(nextJob.value.ts))}`
    : 'no upcoming runs')

  const last24h = computed(() => jobs.value.reduce((acc, job) => {
    const ts = job.last_run ? new Date(job.last_run) : null
    if (ts && !isNaN(ts.getTime()) && now.value - ts.getTime() < 24 * 3600 * 1000) {
      acc.runs += 1
      if (job.last_status === 'ok' || job.last_status === 'success') acc.ok += 1
      if (job.last_status === 'error' || job.last_status === 'fail') acc.err += 1
    }
    return acc
  }, { runs: 0, ok: 0, err: 0 }))

  const upcomingHorizon = computed(() => jobs.value
    .filter(j => isUpcomingRun(j, now.value))
    .map(j => ({ job: j, ts: new Date(j.next_run!).getTime() }))
    .filter(o => o.ts > now.value && (o.ts - now.value) < 12 * 3600 * 1000)
    .sort((a, b) => a.ts - b.ts))

  const filteredSortedJobs = computed(() => {
    const st = searchText.value.toLowerCase()
    const filtered = jobs.value.filter(j => {
      if (!st) return true
      return (j.name || '').toLowerCase().includes(st) ||
        (j.message || j.prompt || '').toLowerCase().includes(st) ||
        (j.payloadKind || '').toLowerCase().includes(st) ||
        String(j.sessionTarget || j.session_target || '').toLowerCase().includes(st) ||
        (j.expression || j.schedule || '').toLowerCase().includes(st)
    })
    return [...filtered].sort((a, b) => {
      let va: unknown = a[sortCol.value as keyof CronJob] ?? ''
      let vb: unknown = b[sortCol.value as keyof CronJob] ?? ''
      if (sortCol.value === 'next_run' || sortCol.value === 'last_run') {
        va = va ? new Date(va as string).getTime() : (sortAsc.value ? Infinity : -Infinity)
        vb = vb ? new Date(vb as string).getTime() : (sortAsc.value ? Infinity : -Infinity)
      } else {
        va = String(va).toLowerCase()
        vb = String(vb).toLowerCase()
      }
      const cmp = (va as number | string) < (vb as number | string) ? -1 : (va as number | string) > (vb as number | string) ? 1 : 0
      return sortAsc.value ? cmp : -cmp
    })
  })

  const loadData = refresh

  function scheduleReload() {
    void refresh()
    if (reloadTimer) clearTimeout(reloadTimer)
    reloadTimer = setTimeout(() => { void refresh() }, 750)
  }

  function onSort(col: string) {
    if (sortCol.value === col) {
      sortAsc.value = !sortAsc.value
    } else {
      sortCol.value = col
      sortAsc.value = true
    }
  }

  async function toggleJob(job: CronJob) {
    try {
      await rpc.call('cron.update', { id: job.id, enabled: !job.enabled })
      pushToast(`Job ${job.enabled ? 'paused' : 'resumed'}`, { tone: 'ok' })
      void refresh()
    } catch (err) {
      pushToast('Update failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
    }
  }

  function isJobRunning(id: string): boolean {
    return runningJobIds.value.has(id)
  }

  async function runJob(id: string) {
    runningJobIds.value = new Set(runningJobIds.value).add(id)
    try {
      const res = await rpc.call<{ reply?: string; error?: string }>('cron.run', { id })
      if (res?.error) pushToast(`Run failed: ${res.error}`, { tone: 'danger' })
      else pushToast(res?.reply ? `Run complete: ${res.reply.substring(0, 120)}` : 'Job triggered', { tone: 'ok' })
    } catch (err) {
      pushToast('Run failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
    } finally {
      const next = new Set(runningJobIds.value)
      next.delete(id)
      runningJobIds.value = next
    }
  }

  async function removeJob(id: string) {
    await rpc.call('cron.remove', { id })
    pushToast('Job deleted', { tone: 'ok' })
    void refresh()
  }

  onMounted(() => {
    tickInterval = setInterval(() => { now.value = Date.now() }, 1000)
    rpc.waitForConnection()
      .then(() => rpc.call('cron.subscribe', {}))
      .catch(() => { /* subscription is best-effort */ })
    unsubRunFinished = rpc.on('cron.run.finished', scheduleReload)
  })

  onUnmounted(() => {
    if (tickInterval) clearInterval(tickInterval)
    if (reloadTimer) clearTimeout(reloadTimer)
    if (unsubRunFinished) unsubRunFinished()
    rpc.call('cron.unsubscribe', {}).catch(() => {})
  })

  return {
    jobs,
    loading,
    error,
    searchText,
    viewMode,
    runningJobIds,
    sortCol,
    sortAsc,
    now,
    enabledCount,
    pausedCount,
    reminderCount,
    agentTaskCount,
    nextCountdown,
    nextRunHint,
    last24h,
    upcomingHorizon,
    filteredSortedJobs,
    loadData,
    onSort,
    toggleJob,
    runJob,
    removeJob,
    isJobRunning,
  }
}

export function isUpcomingRun(job: CronJob, now = Date.now()): boolean {
  if (!job.enabled || !job.next_run || job.status === 'running') return false
  const ts = new Date(job.next_run)
  return !isNaN(ts.getTime()) && ts.getTime() > now
}

export function nextRunText(job: CronJob, now = Date.now()): string {
  if (!job.enabled) return '—'
  if (job.status === 'running') return 'running'
  if (!job.next_run) return '—'
  const ts = new Date(job.next_run)
  if (isNaN(ts.getTime())) return '—'
  if (ts.getTime() <= now) return 'awaiting update'
  return humanCountdown(ts, now)
}

export function nextRunAbs(job: CronJob, now = Date.now()): string {
  if (!job.enabled || job.status === 'running' || !job.next_run) return ''
  const ts = new Date(job.next_run)
  if (isNaN(ts.getTime()) || ts.getTime() <= now) return ''
  return humanTime(ts)
}

export function dotClass(job: CronJob): string {
  if (!job.enabled) return 'is-off'
  const lastStatus = job.last_status || (job.last_run ? 'ok' : null)
  if (lastStatus === 'error' || lastStatus === 'fail') return 'is-error'
  return 'is-on'
}

export function jobKindLabel(job: CronJob): string {
  const kind = job.payloadKind || job.payload_kind
  if (kind === 'reminder') return 'Reminder'
  if (kind === 'system_event') return 'System event'
  return 'Agent task'
}

export function jobKindClass(job: CronJob): string {
  const kind = job.payloadKind || job.payload_kind
  return kind === 'reminder' ? 'is-reminder' : 'is-agent'
}

export function isImminent(job: CronJob, now = Date.now()): boolean {
  if (!job.next_run) return false
  const left = new Date(job.next_run).getTime() - now
  return left > 0 && left < 60_000
}
