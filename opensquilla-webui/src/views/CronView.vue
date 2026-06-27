<template>
  <div class="cron-stage control-stage">
    <header class="cron-stage__header control-stage__header">
      <div class="cron-stage__title-block control-stage__title-block">
        <h2 class="cron-stage__title control-stage__title">Cron Jobs</h2>
        <p class="cron-stage__subtitle control-stage__subtitle">Time-driven tasks &mdash; orchestrate reminders, agent turns, and recurring work.</p>
      </div>
      <div class="cron-stage__actions control-stage__actions">
        <div class="cron-search-wrap">
          <span class="cron-search-icon"><Icon name="search" :size="16" /></span>
          <input v-model="cronJobs.searchText.value" class="cron-search-input" type="search" placeholder="Search jobs&hellip;" autocomplete="off">
        </div>
        <button class="btn btn--ghost" title="Refresh" :disabled="refreshing" @click="refreshCron">
          <Icon name="refresh" :size="16" /><span>{{ refreshing ? 'Refreshing…' : 'Refresh' }}</span>
        </button>
        <button class="btn btn--primary" @click="cronForm.openPanel(null)">
          <Icon name="plus" :size="16" /><span>New job</span>
        </button>
      </div>
    </header>

    <section class="cron-summary control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 4">
      <div class="stat stat--hero control-stat control-stat--hero">
        <div class="stat-label control-stat__label">Active schedules</div>
        <div class="stat-value control-stat__value">{{ cronJobs.enabledCount.value }}<span class="stat-total"> / {{ cronJobs.jobs.value.length }}</span></div>
        <div class="stat-hint control-stat__hint">{{ cronJobs.pausedCount.value ? `${cronJobs.pausedCount.value} paused` : 'all enabled' }}</div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Next run</div>
        <div class="stat-value mono control-stat__value control-stat__value--mono">{{ cronJobs.nextCountdown.value }}</div>
        <div class="stat-hint control-stat__hint">{{ cronJobs.nextRunHint.value }}</div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Last 24h runs</div>
        <div class="stat-value control-stat__value">{{ cronJobs.last24h.value.runs }}</div>
        <div class="stat-hint control-stat__hint">
          <span v-if="cronJobs.last24h.value.ok" class="cron-pos">{{ cronJobs.last24h.value.ok }} ok</span>
          <span v-if="cronJobs.last24h.value.ok && cronJobs.last24h.value.err"> &middot; </span>
          <span v-if="cronJobs.last24h.value.err" class="cron-neg">{{ cronJobs.last24h.value.err }} fail</span>
          <span v-if="!cronJobs.last24h.value.ok && !cronJobs.last24h.value.err">awaiting first run</span>
        </div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Mix</div>
        <div class="stat-value control-stat__value">
          <span title="Reminders"><span class="stat__chip stat__chip--info">{{ cronJobs.reminderCount.value }}</span></span>
          <span>/</span>
          <span title="Agent tasks"><span class="stat__chip stat__chip--accent">{{ cronJobs.agentTaskCount.value }}</span></span>
        </div>
        <div class="stat-hint control-stat__hint">reminders &middot; agent tasks</div>
      </div>
    </section>

    <section v-if="cronJobs.upcomingHorizon.value.length > 0" class="cron-horizon">
      <div class="cron-horizon__head">
        <span class="cron-horizon__title">Next 12 hours</span>
        <span class="cron-horizon__legend"><span class="cron-horizon__dot" />upcoming run</span>
      </div>
      <div class="cron-horizon__rail">
        <button
          v-for="(o, i) in cronJobs.upcomingHorizon.value"
          :key="o.job.id"
          class="cron-horizon__marker"
          :style="{ left: horizonLeft(o.ts), '--i': i }"
          @click="onHorizonClick(o.job.id)"
        >
          <span class="cron-horizon__marker-dot" />
          <span class="cron-horizon__marker-tip">
            <strong>{{ o.job.name || o.job.id }}</strong>
            <em>{{ humanCountdown(new Date(o.ts), cronJobs.now.value) }}</em>
          </span>
        </button>
      </div>
      <div class="cron-horizon__axis">
        <span v-for="h in [0, 3, 6, 9, 12]" :key="h" class="cron-horizon__tick" :style="{ left: (h / 12) * 100 + '%' }">
          <span class="cron-horizon__tick-line" />
          <span class="cron-horizon__tick-label">{{ h === 0 ? 'now' : horizonTickLabel(h) }}</span>
        </span>
      </div>
    </section>

    <div v-if="cronJobs.loading.value && cronJobs.jobs.value.length === 0" class="state">
      <LoadingSpinner />
    </div>

    <ErrorState
      v-else-if="cronJobs.error.value"
      :message="cronJobs.error.value"
      :on-retry="cronJobs.loadData"
    />

    <CronJobList
      v-else
      :jobs="cronJobs.filteredSortedJobs.value"
      :total-jobs="cronJobs.jobs.value.length"
      :search-text="cronJobs.searchText.value"
      :view-mode="cronJobs.viewMode.value"
      :selected-id="selectedId"
      :sort-col="cronJobs.sortCol.value"
      :sort-asc="cronJobs.sortAsc.value"
      :now="cronJobs.now.value"
      :running-job-ids="runningJobIds"
      @update:view-mode="cronJobs.viewMode.value = $event"
      @create="cronForm.openPanel(null)"
      @preset="cronForm.openPanel(null, $event)"
      @select="toggleSelected"
      @run="cronJobs.runJob"
      @toggle="cronJobs.toggleJob"
      @edit="cronForm.openPanel"
      @delete="deleteJob"
      @sort="cronJobs.onSort"
    />

    <CronRunHistory
      v-if="selectedId && selectedJob"
      :job="selectedJob"
      :runs="cronRuns.runs.value"
      :loading="cronRuns.runsLoading.value"
      @close="selectedId = null"
      @open-chat="openRunChat"
    />

    <CronJobPanel
      v-model:form="cronForm.form"
      :open="cronForm.panelOpen.value"
      :editing-job="cronForm.editingJob.value"
      :cron-explain-human="cronForm.cronExplainHuman.value"
      :cron-explain-valid="cronForm.cronExplainValid.value"
      :cron-explain-invalid="cronForm.cronExplainInvalid.value"
      :cron-explain-upcoming="cronForm.cronExplainUpcoming.value"
      :job-mode-hint="cronForm.jobModeHint.value"
      :session-target-hint="cronForm.sessionTargetHint.value"
      :show-target-session-row="cronForm.showTargetSessionRow.value"
      :target-session-label="cronForm.targetSessionLabel.value"
      :target-session-hint="cronForm.targetSessionHint.value"
      :message-label="cronForm.messageLabel.value"
      @close="cronForm.closePanel"
      @save="cronForm.saveJob"
      @cron-input="cronForm.renderCronExplain(cronForm.form.cron)"
      @preset="cronForm.applyPreset"
      @payload-kind-change="cronForm.onPayloadKindChange"
      @session-target-change="cronForm.onSessionTargetChange"
    />

    <CronDeleteDialog
      :open="deleteModalOpen"
      :job="deleteTarget"
      @cancel="closeDeleteDialog"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import CronDeleteDialog from '@/components/cron/CronDeleteDialog.vue'
import CronJobList from '@/components/cron/CronJobList.vue'
import CronJobPanel from '@/components/cron/CronJobPanel.vue'
import CronRunHistory from '@/components/cron/CronRunHistory.vue'
import { useCronForm } from '@/composables/cron/useCronForm'
import { useCronJobs } from '@/composables/cron/useCronJobs'
import { useCronRuns } from '@/composables/cron/useCronRuns'
import { useToasts } from '@/composables/useToasts'
import type { CronJob } from '@/types/cron'
import { humanCountdown } from '@/utils/cron/time'

const router = useRouter()
const { pushToast } = useToasts()
const selectedId = ref<string | null>(null)
const deleteModalOpen = ref(false)
const deleteTarget = ref<CronJob | null>(null)

const cronJobs = useCronJobs()
const cronRuns = useCronRuns(selectedId)
const cronForm = useCronForm({ afterSaved: cronJobs.loadData })

// cronJobs.loadData is the silent useRequest refresh (no loading flag), so wrap
// it in a local flag to give the manual refresh button a busy state.
const refreshing = ref(false)
async function refreshCron() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await cronJobs.loadData()
  } finally {
    refreshing.value = false
  }
}

const selectedJob = computed(() => cronJobs.jobs.value.find(job => job.id === selectedId.value) || null)
const runningJobIds = computed(() => cronJobs.runningJobIds.value)

function toggleSelected(id: string) {
  selectedId.value = selectedId.value === id ? null : id
}

function onHorizonClick(id: string) {
  selectedId.value = id
  nextTick(() => {
    const card = document.querySelector(`[data-cron-row="${CSS.escape(id)}"]`)
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function openRunChat(sessionKey: string) {
  router.push('/chat?session=' + encodeURIComponent(sessionKey))
}

function horizonLeft(ts: number): string {
  const span = 12 * 3600 * 1000
  const left = ((ts - cronJobs.now.value) / span) * 100
  return Math.max(0, Math.min(100, left)) + '%'
}

function horizonTickLabel(h: number): string {
  const ts = cronJobs.now.value + h * 3600 * 1000
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function deleteJob(job: CronJob) {
  deleteTarget.value = job
  deleteModalOpen.value = true
}

function closeDeleteDialog() {
  deleteModalOpen.value = false
  deleteTarget.value = null
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    const id = deleteTarget.value.id
    await cronJobs.removeJob(id)
    if (selectedId.value === id) selectedId.value = null
  } catch (err) {
    pushToast('Delete failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    closeDeleteDialog()
  }
}
</script>

<style>
.cron-search-wrap {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  gap: 8px;
  padding: 0 12px;
}

.cron-search-icon {
  color: var(--text-dim);
}

.cron-search-input {
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-sm);
  min-width: 180px;
  outline: none;
  padding: 8px 0;
}

.stat--hero {
  min-height: 116px;
}

.stat-total {
  color: var(--text-muted);
  font-size: 1rem;
  font-weight: 400;
}

.stat__chip {
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  padding: 2px 8px;
}

.stat__chip--info {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.stat__chip--accent {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.cron-pos { color: var(--ok); }
.cron-neg { color: var(--danger); }

/* Horizon */
.cron-horizon {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.cron-horizon__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  margin-bottom: var(--sp-3);
}

.cron-horizon__title {
  font-size: var(--fs-sm);
  font-weight: 600;
}

.cron-horizon__legend {
  align-items: center;
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  gap: 6px;
}

.cron-horizon__dot {
  background: var(--accent);
  border-radius: 50%;
  display: inline-block;
  height: 8px;
  width: 8px;
}

.cron-horizon__rail {
  height: 32px;
  position: relative;
}

.cron-horizon__marker {
  align-items: center;
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  display: flex;
  padding: 0;
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
}

.cron-horizon__marker-dot {
  background: var(--accent);
  border-radius: 50%;
  height: 10px;
  width: 10px;
}

.cron-horizon__marker-tip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-md);
  display: none;
  font-size: 11px;
  left: 50%;
  padding: 6px 10px;
  position: absolute;
  top: -8px;
  transform: translate(-50%, -100%);
  white-space: nowrap;
  z-index: 10;
}

.cron-horizon__marker:hover .cron-horizon__marker-tip {
  display: block;
}

.cron-horizon__marker-tip strong {
  display: block;
  font-size: 12px;
}

.cron-horizon__marker-tip em {
  color: var(--text-muted);
  font-style: normal;
}

.cron-horizon__axis {
  border-top: 1px solid var(--border);
  height: 20px;
  margin-top: var(--sp-2);
  position: relative;
}

.cron-horizon__tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
}

.cron-horizon__tick-line {
  background: var(--border);
  display: block;
  height: 6px;
  margin: 0 auto;
  width: 1px;
}

.cron-horizon__tick-label {
  color: var(--text-dim);
  display: block;
  font-size: 10px;
  margin-top: 2px;
  text-align: center;
}

/* Jobs list */
.cron-jobs__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.cron-jobs__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.cron-jobs__count {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
  padding: 2px 8px;
}

.cron-view-toggle {
  display: flex;
  gap: 2px;
}

.cron-view-toggle__btn {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 4px 12px;
}

.cron-view-toggle__btn.is-active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-foreground);
}

.cron-card.is-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.cron-card.is-imminent {
  animation: cron-pulse 2s infinite;
}

@keyframes cron-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 30%, transparent); }
  50% { box-shadow: 0 0 0 4px transparent; }
}

.cron-card__head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
}

.cron-card__dot {
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
  height: 10px;
  width: 10px;
}

.cron-card__dot.is-on { background: var(--ok); }
.cron-card__dot.is-off { background: var(--text-dim); }
.cron-card__dot.is-error { background: var(--danger); }

.cron-card__name {
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  overflow: hidden;
  padding: 0;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cron-card__name:hover {
  color: var(--accent);
}

.cron-pill {
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  margin-left: auto;
  padding: 2px 8px;
  text-transform: uppercase;
}

.cron-pill--is-reminder {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.cron-pill--is-agent {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.cron-card__schedule {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.cron-expr {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 2px 8px;
}

.cron-expr--inline {
  background: transparent;
  border: none;
  padding: 0;
}

.cron-card__human {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.cron-card__meta {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
}

.cron-card__meta > div {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.cron-card__meta dt {
  color: var(--text-dim);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.25;
}

.cron-card__meta dd {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
}

.cron-mono {
  font-family: var(--font-mono);
}

.cron-muted {
  color: var(--text-dim);
}

.cron-card__abs {
  color: var(--text-dim);
  font-size: 11px;
}

.cron-card__message {
  grid-column: 1 / -1;
}

.cron-card__message dd {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
}

.cron-card__actions {
  display: flex;
  gap: 4px;
  margin-top: auto;
  padding-top: var(--sp-2);
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
  font-size: 12px;
}

.cron-iconbtn:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.cron-iconbtn:disabled {
  cursor: wait;
  opacity: 0.72;
}

.cron-iconbtn--accent:hover {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.cron-iconbtn--danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.cron-iconbtn--sm {
  padding: 2px 6px;
}

/* Table */
.cron-table-wrap {
  overflow-x: auto;
}

.cron-table {
  border-collapse: collapse;
  font-size: var(--fs-sm);
  width: 100%;
}

.cron-table th,
.cron-table td {
  border-bottom: 1px solid var(--border);
  padding: 10px 12px;
  text-align: left;
  vertical-align: middle;
}

.cron-table th {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cron-th-sort {
  cursor: pointer;
  user-select: none;
}

.cron-th-sort:hover {
  color: var(--text);
}

.cron-table__arrow {
  color: var(--accent);
}

.cron-table tr.is-selected td {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.cron-table__actions {
  display: flex;
  gap: 2px;
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

/* Status */
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

.status--off {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

/* Empty state */
.state {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.state-icon {
  color: var(--text-dim);
}

.state-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.state-text {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
  max-width: 520px;
}

.cron-empty__clock {
  color: var(--text-dim);
  height: 120px;
  width: 120px;
}

.cron-empty__clock svg {
  height: 100%;
  width: 100%;
}

.cron-empty__ring {
  animation: cron-spin 60s linear infinite;
  transform-origin: center;
}

.cron-empty__hand {
  animation: cron-spin 12s linear infinite;
  transform-origin: 60px 60px;
}

@keyframes cron-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.cron-empty__title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.cron-empty__msg {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

.cron-empty__cta {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}

.cron-empty__hints {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.cron-empty__hints-label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cron-empty-hint {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  text-align: left;
  width: 100%;
}

.cron-empty-hint:hover {
  border-color: var(--accent);
}

.cron-empty-hint code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 2px 8px;
  white-space: nowrap;
}

.cron-empty-hint span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

/* Panel */
.cron-panel-overlay {
  bottom: 0;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1000;
}

.cron-panel__scrim {
  background: var(--scrim);
  bottom: 0;
  left: 0;
  opacity: 0;
  position: fixed;
  right: 0;
  top: 0;
  transition: opacity 0.22s;
}

.cron-panel__scrim.is-open {
  opacity: 1;
}

.cron-panel {
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  bottom: 0;
  display: flex;
  flex-direction: column;
  max-width: 480px;
  position: fixed;
  right: 0;
  top: 0;
  transform: translateX(100%);
  transition: transform 0.22s ease-out;
  width: 100%;
  z-index: 1001;
}

.cron-panel.is-open {
  transform: translateX(0);
}

.cron-panel__head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: var(--sp-4);
}

.cron-panel__eyebrow {
  color: var(--text-dim);
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.cron-panel__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
}

.cron-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
}

.cron-panel__actions {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-4);
}

/* Form fields */
.cron-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--sp-3);
}

.cron-field__label {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.cron-field__input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

.cron-field__input:focus {
  border-color: var(--accent);
  outline: none;
}

.cron-field__input--mono {
  font-family: var(--font-mono);
}

.cron-field__input--textarea {
  min-height: 80px;
  resize: vertical;
}

.cron-field__hint {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.5;
}

/* Cron explain */
.cron-explain {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
}

.cron-explain.is-valid {
  border-color: var(--ok);
}

.cron-explain.is-invalid {
  border-color: var(--danger);
}

.cron-explain__human {
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.cron-explain__hint {
  color: var(--text-dim);
  font-size: 12px;
  margin-top: 4px;
}

.cron-explain__upcoming {
  list-style: none;
  margin: var(--sp-2) 0 0;
  padding: 0;
}

.cron-explain__upcoming li {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  padding: 2px 0;
}

.cron-explain__num {
  color: var(--text-dim);
  font-size: 11px;
  min-width: 18px;
}

.cron-explain__abs {
  color: var(--text-dim);
  font-size: 11px;
}

/* Presets */
.cron-presets {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-2);
}

.cron-presets__label {
  color: var(--text-dim);
  font-size: 11px;
}

.cron-preset {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 8px;
}

.cron-preset:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Advanced */
.cron-advanced {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: var(--sp-3);
}

.cron-advanced__summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: 500;
  padding: var(--sp-3);
  user-select: none;
}

.cron-advanced__body {
  border-top: 1px solid var(--border);
  padding: var(--sp-3);
}

.cron-advanced--nested {
  margin-top: var(--sp-3);
}

/* Toggle */
.cron-toggle {
  align-items: center;
  cursor: pointer;
  display: inline-flex;
  gap: 10px;
  margin-bottom: var(--sp-3);
}

.cron-toggle input {
  display: none;
}

.cron-toggle__track {
  background: var(--border);
  border-radius: 12px;
  display: inline-block;
  height: 20px;
  position: relative;
  transition: background 0.15s;
  width: 36px;
}

.cron-toggle input:checked + .cron-toggle__track {
  background: var(--accent);
}

.cron-toggle__thumb {
  background: var(--bg);
  border-radius: 50%;
  display: block;
  height: 16px;
  left: 2px;
  position: absolute;
  top: 2px;
  transition: transform 0.15s;
  width: 16px;
}

.cron-toggle input:checked + .cron-toggle__track .cron-toggle__thumb {
  transform: translateX(16px);
}

.cron-toggle__label {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

/* Spinner */
.cron-spinner {
  animation: cron-spin 1s linear infinite;
  border: 2px solid var(--border);
  border-radius: 50%;
  border-top-color: var(--accent);
  display: inline-block;
  height: 14px;
  width: 14px;
}

/* Modal */
.modal-overlay {
  align-items: center;
  background: var(--scrim);
  bottom: 0;
  display: flex;
  justify-content: center;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1100;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  max-width: 420px;
  padding: var(--sp-5);
  width: 90%;
}

.modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.modal__body {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin-bottom: var(--sp-4);
}

.modal__footer {
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
}

/* Transitions */
.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.2s;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

/* Responsive */
@media (max-width: 980px) {
  .cron-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .cron-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .cron-card-grid {
    grid-template-columns: 1fr;
  }

  .cron-panel {
    max-width: 100%;
  }
}

@media (max-width: 480px) {
  .cron-summary {
    grid-template-columns: 1fr;
  }
}
</style>
