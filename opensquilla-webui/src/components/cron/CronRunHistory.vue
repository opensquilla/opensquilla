<template>
  <div class="cron-detail">
    <div class="cron-detail__head">
      <div>
        <span class="cron-detail__eyebrow">Run history</span>
        <strong class="cron-detail__name">{{ job.name || job.id }}</strong>
      </div>
      <button class="cron-iconbtn" aria-label="Close" @click="emit('close')">
        <Icon name="x" :size="16" />
      </button>
    </div>
    <div class="cron-detail__runs">
      <p v-if="loading" class="cron-muted">Loading&hellip;</p>
      <p v-else-if="runs.length === 0" class="cron-muted">No run history yet.</p>
      <table v-else class="cron-runs">
        <thead>
          <tr><th>Time</th><th>Status</th><th>Duration</th><th>Delivery</th><th>Reply</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.started_at">
            <td class="cron-mono">{{ run.started_at ? relTime(run.started_at) : '—' }}</td>
            <td><span :class="`status status--${run.status === 'ok' ? 'ok' : 'err'}`">{{ run.status || 'unknown' }}</span></td>
            <td class="cron-mono">{{ run.duration_ms != null ? run.duration_ms + 'ms' : '—' }}</td>
            <td>{{ deliveryStatusText(run) }}</td>
            <td class="cron-runs__reply">{{ run.summary ? run.summary.substring(0, 120) : '—' }}</td>
            <td>
              <button v-if="run.sessionKey" class="cron-link cron-run-chat-link" @click="emit('openChat', run.sessionKey)">
                &rarr; Chat
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'

interface CronRunHistoryJob {
  id: string
  name?: string
}

interface CronRunHistoryRun {
  started_at?: string
  status?: string
  duration_ms?: number
  deliveryStatus?: Record<string, unknown> | string
  delivery_status?: Record<string, unknown> | string
  summary?: string
  sessionKey?: string
}

defineProps<{
  job: CronRunHistoryJob
  runs: CronRunHistoryRun[]
  loading: boolean
}>()

const emit = defineEmits<{
  close: []
  openChat: [sessionKey: string]
}>()

function deliveryStatusText(run: CronRunHistoryRun): string {
  const status = run.deliveryStatus || run.delivery_status
  if (!status) return '—'
  if (typeof status === 'string') return status
  return `ch: ${stringField(status, 'channel') || '-'}, ws: ${stringField(status, 'ws') || '-'}`
}

function stringField(source: Record<string, unknown>, key: string): string {
  const value = source[key]
  return typeof value === 'string' ? value : ''
}

function humanCountdownPast(date: Date): string {
  const diff = Date.now() - date.getTime()
  if (diff < 0) return 'in ' + formatDuration(-diff)
  if (diff < 1000) return 'just now'
  return formatDuration(diff) + ' ago'
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm ' + (s % 60) + 's'
  const h = Math.floor(m / 60)
  if (h < 24) return h + 'h ' + (m % 60) + 'm'
  const d = Math.floor(h / 24)
  return d + 'd ' + (h % 24) + 'h'
}

function relTime(ts: string): string {
  const date = new Date(ts)
  if (isNaN(date.getTime())) return '—'
  return humanCountdownPast(date)
}
</script>

<style scoped>
.cron-detail {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-top: var(--sp-3);
  overflow: hidden;
}

.cron-detail__head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: var(--sp-4);
}

.cron-detail__eyebrow {
  color: var(--text-dim);
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.cron-detail__name {
  color: var(--text);
  font-size: var(--fs-md);
}

.cron-detail__runs {
  padding: var(--sp-4);
}

.cron-muted {
  color: var(--text-dim);
}

.cron-mono {
  font-family: var(--font-mono);
}

.cron-iconbtn {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  padding: 4px 8px;
  transition: background var(--transition), border-color var(--transition), color var(--transition);
}

.cron-iconbtn:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.cron-runs {
  border-collapse: collapse;
  font-size: var(--fs-sm);
  width: 100%;
}

.cron-runs th,
.cron-runs td {
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
}

.cron-runs th {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.cron-runs__reply {
  color: var(--text-muted);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cron-link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  padding: 0;
  text-decoration: underline;
}

.cron-link:hover {
  color: var(--text);
}

.status {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
}

.status--ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.status--err {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}
</style>
