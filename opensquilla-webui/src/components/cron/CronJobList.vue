<template>
  <section class="cron-jobs">
    <div class="cron-jobs__head">
      <h3 class="cron-jobs__title">
        <template v-if="searchText">Matching schedules <span class="cron-jobs__count">{{ jobs.length }} of {{ totalJobs }}</span></template>
        <template v-else>All schedules <span class="cron-jobs__count">{{ jobs.length }}</span></template>
      </h3>
      <div class="cron-view-toggle" role="tablist" aria-label="View mode">
        <button class="cron-view-toggle__btn" :class="{ 'is-active': viewMode === 'cards' }" role="tab" @click="emit('update:viewMode', 'cards')">Cards</button>
        <button class="cron-view-toggle__btn" :class="{ 'is-active': viewMode === 'table' }" role="tab" @click="emit('update:viewMode', 'table')">Table</button>
      </div>
    </div>

    <div v-if="jobs.length === 0" class="state">
      <template v-if="totalJobs === 0">
        <div class="cron-empty__clock" aria-hidden="true">
          <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <radialGradient id="cg" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="color-mix(in srgb, var(--accent) 20%, transparent)" />
                <stop offset="60%" stop-color="color-mix(in srgb, var(--accent) 5%, transparent)" />
                <stop offset="100%" stop-color="transparent" />
              </radialGradient>
            </defs>
            <circle cx="60" cy="60" r="58" fill="url(#cg)" />
            <circle cx="60" cy="60" r="44" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1" />
            <circle cx="60" cy="60" r="44" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="2 6" class="cron-empty__ring" />
            <line
              v-for="deg in [0,30,60,90,120,150,180,210,240,270,300,330]"
              :key="deg"
              :x1="60 + Math.cos(deg * Math.PI / 180) * 40"
              :y1="60 + Math.sin(deg * Math.PI / 180) * 40"
              :x2="60 + Math.cos(deg * Math.PI / 180) * (deg % 90 === 0 ? 32 : 36)"
              :y2="60 + Math.sin(deg * Math.PI / 180) * (deg % 90 === 0 ? 32 : 36)"
              stroke="currentColor"
              :stroke-opacity="deg % 90 === 0 ? 0.5 : 0.25"
              :stroke-width="deg % 90 === 0 ? 1.5 : 1"
            />
            <line x1="60" y1="60" x2="60" y2="28" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" class="cron-empty__hand" />
            <line x1="60" y1="60" x2="84" y2="60" stroke="currentColor" stroke-opacity="0.6" stroke-width="2" stroke-linecap="round" />
            <circle cx="60" cy="60" r="3" fill="var(--accent)" />
          </svg>
        </div>
        <div class="cron-empty__title">Set the rhythm.</div>
        <p class="cron-empty__msg">No schedules yet. Create your first cron job to wake an agent, fire a reminder,<br>or kick off recurring work &mdash; all on time, all on your terms.</p>
        <button class="btn btn--primary cron-empty__cta" @click="emit('create')">
          <Icon name="plus" :size="16" /><span>Create your first schedule</span>
        </button>
        <div class="cron-empty__hints">
          <span class="cron-empty__hints-label">Try a preset</span>
          <button
            v-for="preset in presets"
            :key="preset.name"
            class="cron-empty-hint"
            @click="emit('preset', preset)"
          >
            <code>{{ preset.expression }}</code>
            <span>{{ preset.label }}</span>
          </button>
        </div>
      </template>
      <template v-else>
        <div class="state-icon"><Icon name="search" :size="48" /></div>
        <div class="state-title">No matches</div>
        <p class="state-text">No schedules match your search. Try a different query, or clear it to see everything.</p>
      </template>
    </div>

    <div v-else-if="viewMode === 'cards'" class="cron-card-grid control-card-grid" style="--control-card-min: 340px">
      <article
        v-for="(job, i) in jobs"
        :key="job.id"
        class="cron-card control-card control-card--interactive"
        :class="{ 'is-selected control-card--selected': selectedId === job.id, 'is-imminent': isImminent(job, now) }"
        :style="{ '--stagger': i }"
        :data-cron-row="job.id"
      >
        <header class="cron-card__head">
          <span class="cron-card__dot" :class="dotClass(job)" />
          <button type="button" class="cron-card__name" title="Show run history" @click="emit('select', job.id)">
            {{ job.name || job.id }}
          </button>
          <span class="cron-pill" :class="`cron-pill--${jobKindClass(job)}`">{{ jobKindLabel(job) }}</span>
        </header>
        <div class="cron-card__schedule">
          <code class="cron-expr">{{ job.expression || job.schedule || '—' }}</code>
          <span v-if="explainCron(job.expression || '')" class="cron-card__human">{{ explainCron(job.expression || '') }}</span>
        </div>
        <dl class="cron-card__meta">
          <div><dt>Target</dt><dd>{{ job.sessionTarget || job.session_target || '—' }}</dd></div>
          <div>
            <dt>Last run</dt>
            <dd>
              {{ job.last_run ? humanCountdownPast(new Date(job.last_run), now) : '—' }}
              <span v-if="job.last_status">
                &middot; <span :class="`status status--${job.last_status === 'ok' || job.last_status === 'success' ? 'ok' : 'err'}`">{{ job.last_status }}</span>
              </span>
            </dd>
          </div>
          <div>
            <dt>Next run</dt>
            <dd>
              <template v-if="job.enabled">
                <span class="cron-mono">{{ nextRunText(job, now) }}</span>
                <span v-if="nextRunAbs(job, now)" class="cron-card__abs"> &middot; {{ nextRunAbs(job, now) }}</span>
              </template>
              <span v-else class="cron-muted">paused</span>
            </dd>
          </div>
          <div v-if="(job.message || job.prompt || '').trim()" class="cron-card__message">
            <dt>Prompt</dt>
            <dd>{{ truncate(job.message || job.prompt || '') }}</dd>
          </div>
        </dl>
        <footer class="cron-card__actions">
          <button class="cron-iconbtn cron-iconbtn--accent" title="Run now" :disabled="runningJobIds.has(job.id)" @click="emit('run', job.id)">
            <span v-if="runningJobIds.has(job.id)" class="cron-spinner" aria-hidden="true"></span>
            <Icon v-else name="send" :size="16" />
            <span>{{ runningJobIds.has(job.id) ? 'Running...' : 'Run' }}</span>
          </button>
          <button class="cron-iconbtn" :title="job.enabled ? 'Pause' : 'Resume'" @click="emit('toggle', job)">
            <Icon :name="job.enabled ? 'stop' : 'send'" :size="16" /><span>{{ job.enabled ? 'Pause' : 'Resume' }}</span>
          </button>
          <button class="cron-iconbtn" title="Edit" @click="emit('edit', job)">
            <Icon name="edit" :size="16" /><span>Edit</span>
          </button>
          <button class="cron-iconbtn cron-iconbtn--danger" title="Delete" @click="emit('delete', job)">
            <Icon name="trash" :size="16" />
          </button>
        </footer>
      </article>
    </div>

    <div v-else class="cron-table-wrap">
      <table class="cron-table">
        <thead>
          <tr>
            <th v-for="col in tableCols" :key="col.key" :class="{ 'cron-th-sort': sortableCols.includes(col.key) }" @click="sortableCols.includes(col.key) ? emit('sort', col.key) : undefined">
              {{ col.label }}
              <span v-if="sortCol === col.key" class="cron-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id" :class="{ 'is-selected': selectedId === job.id, 'is-imminent': isImminent(job, now) }" :data-cron-row="job.id">
            <td>
              <span class="cron-card__dot" :class="dotClass(job)" />
              <button class="cron-link" @click="emit('select', job.id)">{{ job.name || job.id }}</button>
            </td>
            <td><span class="cron-pill" :class="`cron-pill--${jobKindClass(job)}`">{{ jobKindLabel(job) }}</span></td>
            <td>{{ job.sessionTarget || job.session_target || '—' }}</td>
            <td><code class="cron-expr cron-expr--inline">{{ job.expression || job.schedule || '—' }}</code></td>
            <td>
              <span v-if="job.enabled" class="status status--ok">enabled</span>
              <span v-else class="status status--off">paused</span>
            </td>
            <td class="cron-mono">{{ job.last_run ? humanCountdownPast(new Date(job.last_run), now) : '—' }}</td>
            <td class="cron-mono">{{ job.enabled ? nextRunText(job, now) : '—' }}</td>
            <td class="cron-table__actions">
              <button class="cron-iconbtn cron-iconbtn--sm" :title="runningJobIds.has(job.id) ? 'Running' : 'Run now'" :disabled="runningJobIds.has(job.id)" @click="emit('run', job.id)">
                <span v-if="runningJobIds.has(job.id)" class="cron-spinner" aria-hidden="true"></span>
                <Icon v-else name="send" :size="14" />
              </button>
              <button class="cron-iconbtn cron-iconbtn--sm" :title="job.enabled ? 'Pause' : 'Resume'" @click="emit('toggle', job)">
                <Icon :name="job.enabled ? 'stop' : 'send'" :size="14" />
              </button>
              <button class="cron-iconbtn cron-iconbtn--sm" title="Edit" @click="emit('edit', job)">
                <Icon name="edit" :size="14" />
              </button>
              <button class="cron-iconbtn cron-iconbtn--sm cron-iconbtn--danger" title="Delete" @click="emit('delete', job)">
                <Icon name="trash" :size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { CronJob, CronPanelTemplate } from '@/types/cron'
import { explainCron } from '@/utils/cron/schedule'
import { humanCountdownPast } from '@/utils/cron/time'
import { dotClass, isImminent, jobKindClass, jobKindLabel, nextRunAbs, nextRunText } from '@/composables/cron/useCronJobs'

defineProps<{
  jobs: CronJob[]
  totalJobs: number
  searchText: string
  viewMode: 'cards' | 'table'
  selectedId: string | null
  sortCol: string
  sortAsc: boolean
  now: number
  runningJobIds: Set<string>
}>()

const emit = defineEmits<{
  'update:viewMode': [mode: 'cards' | 'table']
  create: []
  preset: [template: CronPanelTemplate]
  select: [id: string]
  run: [id: string]
  toggle: [job: CronJob]
  edit: [job: CronJob]
  delete: [job: CronJob]
  sort: [key: string]
}>()

const tableCols = [
  { key: 'name', label: 'Name' },
  { key: 'payloadKind', label: 'Kind' },
  { key: 'sessionTarget', label: 'Target' },
  { key: 'expression', label: 'Schedule' },
  { key: 'enabled', label: 'Status' },
  { key: 'last_run', label: 'Last Run' },
  { key: 'next_run', label: 'Next Run' },
  { key: '_actions', label: '' },
]
const sortableCols = ['name', 'payloadKind', 'sessionTarget', 'expression', 'last_run', 'next_run']

const presets: Array<CronPanelTemplate & { label: string }> = [
  { name: 'Daily standup nudge', expression: '0 9 * * 1-5', payloadKind: 'reminder', message: 'Good morning! Time for standup.', label: 'Weekday morning reminder' },
  { name: 'Hourly health check', expression: '0 * * * *', payloadKind: 'agent_turn', message: 'Run a quick system health check and report any anomalies.', label: 'Hourly agent check' },
  { name: 'Friday wrap-up', expression: '0 17 * * 5', payloadKind: 'agent_turn', message: "Summarize this week's work and propose next week's priorities.", label: 'Friday agent wrap-up' },
]

function truncate(value: string): string {
  const text = value.trim()
  return text.length > 140 ? text.slice(0, 140) + '…' : text
}
</script>
