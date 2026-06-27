<template>
  <div v-if="open" class="meta-runs-overlay" @click.self="emit('close')">
    <aside
      ref="drawerRef"
      class="meta-runs-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="MetaSkill run history"
    >
      <header class="meta-runs-head">
        <h3 class="meta-runs-head__title">MetaSkill runs</h3>
        <button type="button" class="btn btn--ghost" :disabled="loading" @click="loadFailures">
          Failures
        </button>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          aria-label="Close MetaSkill run history"
          title="Close"
          @click="emit('close')"
        >
          <Icon name="x" :size="16" />
        </button>
      </header>

      <div class="meta-runs-body">
        <p v-if="loading" class="meta-runs-empty">Loading…</p>
        <p v-else-if="error" class="meta-runs-error" role="alert">{{ error }}</p>
        <p v-else-if="runs.length === 0" class="meta-runs-empty">No MetaSkill runs for this session.</p>
        <ol v-else class="meta-runs-list">
          <li v-for="run in runs" :key="runKey(run)" class="meta-runs-item" :data-run-id="run.run_id || ''">
            <div class="meta-runs-item__row">
              <button type="button" class="meta-runs-item__name" @click="runAction('show', run)">
                {{ run.meta_skill_name || 'meta-skill' }}
              </button>
              <span class="meta-runs-item__status">{{ run.status || 'unknown' }}{{ costText(run) }}</span>
            </div>
            <div class="meta-runs-item__actions">
              <button type="button" class="btn btn--ghost" @click="runAction('draft', run)">Draft</button>
              <button type="button" class="btn btn--ghost" @click="runAction('diff', run)">Diff</button>
              <button type="button" class="btn btn--ghost" @click="runAction('replay', run)">Replay</button>
              <button type="button" class="btn btn--ghost" @click="runAction('cost', run)">Cost</button>
              <button
                type="button"
                class="btn btn--ghost meta-runs-validate"
                :class="validationAvailable(run) ? 'is-available' : 'is-unavailable'"
                :title="validationTitle(run)"
                @click="runAction('validate', run)"
              >
                Validate
              </button>
            </div>
            <!-- Detail panel: replace-or-toggle per run+kind (not append-forever) -->
            <pre
              v-if="detailFor(run)"
              class="meta-runs-detail"
              :data-kind="detailFor(run)!.kind"
            >{{ detailFor(run)!.json }}</pre>
          </li>
        </ol>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, toRef, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useDialogA11y } from '@/composables/useDialogA11y'

interface MetaRunUsage {
  available?: boolean
  cost_usd?: number | null
}

interface MetaRunSummary {
  usage?: MetaRunUsage
}

interface MetaRunValidation {
  available?: boolean
  reason?: string
}

interface MetaRunListItem {
  run_id?: string
  meta_skill_name?: string
  status?: string
  summary?: MetaRunSummary
  validation?: MetaRunValidation
}

interface MetaRunsListResponse {
  runs?: MetaRunListItem[]
}

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

const props = withDefaults(
  defineProps<{
    open: boolean
    rpc: RpcClient
    sessionKey: string
    limit?: number
  }>(),
  { limit: 20 },
)

const emit = defineEmits<{
  close: []
}>()

const runs = ref<MetaRunListItem[]>([])
const loading = ref(false)
const error = ref('')
// Detail panels: one per run_id, carrying { kind, json }. Replace-or-toggle.
const details = ref<Map<string, { kind: string; json: string }>>(new Map())

const drawerRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)

const openRef = toRef(props, 'open')
useDialogA11y(drawerRef, openRef, () => emit('close'), { initialFocus: closeBtn })

function runKey(run: MetaRunListItem): string {
  return run.run_id || run.meta_skill_name || JSON.stringify(run)
}

function costText(run: MetaRunListItem): string {
  const usage = run.summary?.usage
  if (usage?.available && usage.cost_usd != null) {
    return ` · $${Number(usage.cost_usd || 0).toFixed(4)}`
  }
  return ''
}

function validationAvailable(run: MetaRunListItem): boolean {
  return run.validation?.available === true
}

function validationTitle(run: MetaRunListItem): string {
  return validationAvailable(run)
    ? 'Validation available'
    : run.validation?.reason || 'Validation unavailable'
}

function detailFor(run: MetaRunListItem) {
  return details.value.get(run.run_id || '')
}

function setDetail(runId: string, kind: string, payload: unknown) {
  const json = JSON.stringify(payload ?? {}, null, 2)
  const next = new Map(details.value)
  const existing = next.get(runId)
  // Toggle off if the same kind is already shown for this run.
  if (existing && existing.kind === kind && existing.json === json) {
    next.delete(runId)
  } else {
    next.set(runId, { kind, json })
  }
  details.value = next
}

function setDetailError(runId: string, message: string) {
  const next = new Map(details.value)
  next.set(runId, { kind: 'error', json: message || 'Action failed' })
  details.value = next
}

// Newest-first DOM order: the next id (older run) is the diff target.
function previousRunIdFor(runId: string): string {
  const ids = runs.value.map((r) => r.run_id || '').filter(Boolean)
  const unique = ids.filter((id, index) => ids.indexOf(id) === index)
  const index = unique.indexOf(runId)
  return index >= 0 ? unique[index + 1] || '' : ''
}

async function loadRuns() {
  loading.value = true
  error.value = ''
  details.value = new Map()
  try {
    const payload = await props.rpc.call<MetaRunsListResponse>('meta.runs.list', {
      sessionKey: props.sessionKey,
      limit: props.limit,
    })
    runs.value = Array.isArray(payload?.runs) ? payload.runs : []
  } catch (err) {
    runs.value = []
    error.value = err instanceof Error ? err.message : String(err || 'Failed to load runs')
  } finally {
    loading.value = false
  }
}

async function loadFailures() {
  try {
    const payload = await props.rpc.call('meta.runs.failures', {
      sessionKey: props.sessionKey,
      limit: 20,
    })
    // Surface session-wide failures as a synthetic top detail row.
    const next = new Map(details.value)
    next.set('__failures__', { kind: 'failures', json: JSON.stringify(payload ?? {}, null, 2) })
    details.value = next
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err || 'Action failed')
  }
}

async function runAction(action: string, run: MetaRunListItem) {
  const runId = run.run_id || ''
  if (!runId) return
  try {
    if (action === 'show') {
      const payload = await props.rpc.call<{ run?: unknown }>('meta.runs.show', { runId })
      setDetail(runId, 'show', payload.run ?? payload)
    } else if (action === 'draft') {
      const payload = await props.rpc.call<{ draft?: unknown }>('meta.runs.draft', {
        runId,
        sessionKey: props.sessionKey,
      })
      setDetail(runId, 'draft', payload.draft ?? payload)
    } else if (action === 'diff') {
      const previousRunId = previousRunIdFor(runId)
      if (!previousRunId) {
        setDetailError(runId, 'No previous run to diff against.')
        return
      }
      const payload = await props.rpc.call<{ diff?: unknown }>('meta.runs.diff', {
        leftRunId: previousRunId,
        rightRunId: runId,
      })
      setDetail(runId, 'diff', payload.diff ?? payload)
    } else if (action === 'replay') {
      const payload = await props.rpc.call<{ replay?: unknown }>('meta.runs.replay', {
        runId,
        mode: 'failed-step',
      })
      setDetail(runId, 'replay', payload.replay ?? payload)
    } else if (action === 'cost') {
      const payload = await props.rpc.call('meta.runs.cost', {
        sessionKey: props.sessionKey,
        limit: 20,
      })
      setDetail(runId, 'cost', payload)
    } else if (action === 'validate') {
      const payload = await props.rpc.call<{ validation?: unknown }>('meta.runs.validate', { runId })
      setDetail(runId, 'validate', payload.validation ?? payload)
    }
  } catch (err) {
    setDetailError(runId, err instanceof Error ? err.message : String(err || 'Action failed'))
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    void loadRuns()
  },
  { immediate: true },
)
</script>

<style scoped>
.meta-runs-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  justify-content: flex-end;
  background: color-mix(in srgb, var(--bg) 60%, transparent);
}

.meta-runs-drawer {
  width: min(440px, 100%);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}

.meta-runs-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--hairline);
}

.meta-runs-head__title {
  flex: 1;
  margin: 0;
  color: var(--text);
  font-size: var(--fs-sm, 0.875rem);
  font-weight: 650;
}

.meta-runs-body {
  flex: 1;
  overflow: auto;
  padding: 12px 16px;
}

.meta-runs-empty,
.meta-runs-error {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm, 0.875rem);
}

.meta-runs-error {
  color: var(--danger);
}

.meta-runs-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 12px;
}

.meta-runs-item {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-base, var(--bg)) 72%, transparent);
}

.meta-runs-item__row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.meta-runs-item__name {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-runs-item__status {
  color: var(--text-muted);
  font-size: var(--fs-xs, 0.75rem);
  font-variant-numeric: tabular-nums;
}

.meta-runs-item__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-runs-validate.is-unavailable {
  opacity: 0.6;
}

.meta-runs-detail {
  margin: 10px 0 0;
  padding: 9px 10px;
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs, 0.75rem);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.meta-runs-detail[data-kind="error"] {
  color: var(--danger);
}
</style>
