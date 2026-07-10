<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import GatewayStatusBlock from '@/components/settings/GatewayStatusBlock.vue'
import SettingsUpdatePanel from '@/components/settings/SettingsUpdatePanel.vue'
import { usePlatform, type GatewayStatus } from '@/platform'
import { useConfirm } from '@/composables/useConfirm'
import { useToasts } from '@/composables/useToasts'
import {
  formatByteSize,
  summarizeMigrationReport,
  type MigrationReportSummary,
} from '@/utils/migrationReport'

const { t } = useI18n()

// Desktop-only Runtime section of the shared SettingsDialog. The desktop app
// owns its local gateway process, so this surfaces its status/log/restart and
// the "reset saved setup" escape hatch — the controls the old standalone
// DesktopSettingsView carried. Web never renders this (desktopOnly section).
const platform = usePlatform()
const { confirm } = useConfirm()
const { pushToast } = useToasts()

const loading = ref(true)
const busy = ref(false)
const gateway = shallowRef<GatewayStatus | null>(null)

const STATUS_KEYS: Record<string, string> = {
  starting: 'setup.runtime.statusStarting',
  ready: 'setup.runtime.statusReady',
  stopped: 'setup.runtime.statusStopped',
  error: 'setup.runtime.statusError',
}

const statusLabel = computed(() => {
  const key = STATUS_KEYS[gateway.value?.status ?? '']
  return key ? t(key) : t('setup.runtime.statusUnknown')
})
const gatewayError = computed(() => gateway.value?.error || '')
const url = computed(() => gateway.value?.url || t('setup.runtime.noActiveGateway'))
const logAvailable = computed(() => Boolean(gateway.value?.logPath))
const logHint = computed(() => gateway.value?.logPath || t('setup.runtime.noLogPath'))

// This panel only ever mounts on desktop (SettingsDialog gates it behind
// isDesktop), so the capability flags are always true here; gate the buttons on
// the optional methods actually being wired instead.
const canRevealLog = computed(() => Boolean(platform.gateway.revealLog))
const canRestart = computed(() => Boolean(platform.gateway.retryStartup))
const canReset = computed(() => Boolean(platform.settings.resetDesktopSettings))

// Desktop data cleanup is wired directly on the desktop preload bridge
// (desktop-only, self-contained — it shells out to `opensquilla uninstall` in
// the Python core). It does not remove the installed app bundle itself.
interface UninstallBridge {
  uninstallRun?: (payload: { purgeData: boolean }) => Promise<{ ok: boolean; aborted?: boolean; detail?: string }>
  quitApp?: () => Promise<unknown>
}

// Legacy-home import rides the same preload bridge (also desktop-only and
// self-contained: the Electron main process quiesces the gateway, shells out to
// the bundled `opensquilla migrate`, then restarts behind the boot splash).
// All methods are optional so a panel served by a newer gateway to an older
// desktop shell simply hides the row instead of crashing.
interface MigrationBridge {
  migrationSummary?: () => Promise<{
    ok: boolean
    candidate: { kind: string; path: string } | null
    report: unknown | null
    previewId?: string
    raw?: string
  }>
  migrationRun?: (opts: { overwrite?: boolean; previewId: string }) => Promise<{
    ok: boolean
    aborted?: boolean
    migrationApplied?: boolean
    restartOk?: boolean
    requiresProviderSetup?: boolean
    report?: unknown
    detail?: string
  }>
  migrationTakeLastResult?: () => Promise<{
    ok: boolean
    migrationApplied: boolean
    restartOk: boolean
    requiresProviderSetup: boolean
    detail?: string
  } | null>
  onMigrationProgress?: (cb: (state: { phase: string; detail?: string }) => void) => () => void
}

const desktopBridge = (
  globalThis as unknown as { opensquillaDesktop?: UninstallBridge & MigrationBridge }
).opensquillaDesktop
const canUninstall = computed(() => Boolean(desktopBridge?.uninstallRun))
const canMigrate = computed(
  () => Boolean(desktopBridge?.migrationSummary && desktopBridge?.migrationRun),
)

async function loadStatus() {
  loading.value = true
  try {
    gateway.value = await platform.gateway.getStatus()
  } catch (err) {
    pushToast(t('setup.runtime.statusReadFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    loading.value = false
  }
}

async function revealLog() {
  if (!platform.gateway.revealLog) return
  try {
    const ok = await platform.gateway.revealLog()
    if (!ok) pushToast(t('setup.runtime.noLogToReveal'), { tone: 'danger' })
  } catch (err) {
    pushToast(t('setup.runtime.revealFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  }
}

async function restartGateway() {
  if (!platform.gateway.retryStartup) return
  busy.value = true
  try {
    await platform.gateway.retryStartup()
    pushToast(t('setup.runtime.restarting'))
    await loadStatus()
  } catch (err) {
    pushToast(t('setup.runtime.restartFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

async function resetSetup() {
  if (!platform.settings.resetDesktopSettings) return
  const ok = await confirm({
    title: t('setup.runtime.resetConfirmTitle'),
    body: t('setup.runtime.resetConfirmBody'),
    primaryLabel: t('setup.runtime.resetConfirmPrimary'),
  })
  if (!ok) return
  busy.value = true
  try {
    await platform.settings.resetDesktopSettings()
    pushToast(t('setup.runtime.resetDone'))
  } catch (err) {
    pushToast(t('setup.runtime.resetFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

async function uninstall(purgeData: boolean) {
  if (!desktopBridge?.uninstallRun) return
  const ok = await confirm(
    purgeData
      ? {
          title: t('setup.runtime.uninstallPurgeTitle'),
          body: t('setup.runtime.uninstallPurgeBody'),
          primaryLabel: t('setup.runtime.uninstallPurgePrimary'),
        }
      : {
          title: t('setup.runtime.uninstallConfirmTitle'),
          body: t('setup.runtime.uninstallConfirmBody'),
          primaryLabel: t('setup.runtime.uninstallConfirmPrimary'),
        },
  )
  if (!ok) return
  busy.value = true
  try {
    const result = await desktopBridge.uninstallRun({ purgeData })
    if (result?.aborted) {
      // Cancelled at the native dialog, or refused (e.g. a gateway still running).
      // Not an error — surface the reason only when it is informative.
      if (result.detail && result.detail !== 'cancelled') {
        pushToast(result.detail, { tone: 'danger' })
      }
      return
    }
    if (!result?.ok) {
      pushToast(t('setup.runtime.uninstallFailed', { detail: result?.detail || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      return
    }
    pushToast(t('setup.runtime.uninstallDone'))
    await desktopBridge.quitApp?.()
  } catch (err) {
    pushToast(t('setup.runtime.uninstallFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

// --- Legacy-home import (rescue flow for users past first run) ---
const migrationOpen = ref(false)
const migrationBusy = ref(false)
const migrationCandidate = ref<{ kind: string; path: string } | null>(null)
const migrationSummary = shallowRef<MigrationReportSummary | null>(null)
const migrationPreviewId = ref('')
const migrationOverwrite = ref(false)
const migrationPhase = ref('')
let migrationProgressUnsub: (() => void) | null = null

const migrationCountsText = computed(() => {
  const summary = migrationSummary.value
  if (!summary) return ''
  const c = summary.itemCounts
  const parts: string[] = []
  if (c.planned) parts.push(t('setup.runtime.migrationCountPlanned', { n: c.planned }))
  if (c.migrated) parts.push(t('setup.runtime.migrationCountMigrated', { n: c.migrated }))
  if (c.skipped) parts.push(t('setup.runtime.migrationCountSkipped', { n: c.skipped }))
  if (c.error) parts.push(t('setup.runtime.migrationCountError', { n: c.error }))
  return parts.length ? parts.join(' · ') : t('setup.runtime.migrationCountNone')
})
const migrationDiskText = computed(() => {
  const summary = migrationSummary.value
  if (!summary) return ''
  return t('setup.runtime.migrationDisk', {
    required: formatByteSize(summary.diskRequiredBytes),
    free: formatByteSize(summary.diskFreeBytes),
  })
})
const migrationHasBlockingErrors = computed(() => {
  const summary = migrationSummary.value
  if (!summary) return true
  // The one preflight/target error is resolved by explicitly opting into
  // overwrite-with-backups. Every other report error remains blocking.
  const acknowledgedByOverwrite = summary.needsOverwrite ? 1 : 0
  return summary.itemCounts.error > acknowledgedByOverwrite
})

function subscribeMigrationProgress() {
  if (migrationProgressUnsub || !desktopBridge?.onMigrationProgress) return
  migrationProgressUnsub = desktopBridge.onMigrationProgress((state) => {
    if (!state || typeof state.phase !== 'string') return
    migrationPhase.value = state.detail ? `${state.phase} — ${state.detail}` : state.phase
  })
}

function unsubscribeMigrationProgress() {
  migrationProgressUnsub?.()
  migrationProgressUnsub = null
}

// Row click: dry-run summary over the bridge, then the inline confirm block.
async function openMigration() {
  if (!desktopBridge?.migrationSummary) return
  migrationBusy.value = true
  try {
    const result = await desktopBridge.migrationSummary()
    const candidate = result.candidate && typeof result.candidate.path === 'string'
      ? result.candidate
      : null
    if (!candidate) {
      if (!result?.ok) {
        pushToast(t('setup.runtime.migrationSummaryFailed', { detail: result?.raw || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      } else {
        pushToast(t('setup.runtime.migrationNone'))
      }
      return
    }
    // A blocked dry run exits nonzero but still emits the report that explains
    // the preflight failure. Treat parsing (report !== null), not exit status,
    // as the preview-validity signal.
    if (result.report == null || typeof result.previewId !== 'string' || !result.previewId) {
      pushToast(t('setup.runtime.migrationSummaryFailed', { detail: result?.raw || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      return
    }
    migrationCandidate.value = { kind: String(candidate.kind ?? ''), path: candidate.path }
    migrationSummary.value = summarizeMigrationReport(result.report)
    migrationPreviewId.value = result.previewId
    migrationOverwrite.value = false
    migrationPhase.value = ''
    migrationOpen.value = true
    subscribeMigrationProgress()
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

function cancelMigration() {
  migrationOpen.value = false
  migrationCandidate.value = null
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationPhase.value = ''
  unsubscribeMigrationProgress()
}

async function runMigration() {
  if (!desktopBridge?.migrationRun || !migrationOpen.value || !migrationPreviewId.value) return
  const ok = await confirm({
    title: t('setup.runtime.migrationConfirmTitle'),
    body: t('setup.runtime.migrationConfirmBody'),
    primaryLabel: t('setup.runtime.migrationConfirmPrimary'),
  })
  if (!ok) return
  migrationBusy.value = true
  // The run quiesces the gateway and restarts it behind the boot splash, so
  // this page's RPC connection is expected to drop mid-run. Surface the
  // restart notice up front. The main process persists the terminal result so
  // the replacement renderer can surface it the next time this panel mounts.
  pushToast(t('setup.runtime.migrationStarted'))
  try {
    const result = await desktopBridge.migrationRun({
      overwrite: migrationOverwrite.value,
      previewId: migrationPreviewId.value,
    })
    if (result?.aborted) return
    await desktopBridge.migrationTakeLastResult?.().catch(() => null)
    if (!result?.ok) {
      pushToast(t('setup.runtime.migrationFailed', { detail: result?.detail || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      return
    }
    pushToast(t('setup.runtime.migrationDone'))
    cancelMigration()
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function showLastMigrationResult() {
  if (!desktopBridge?.migrationTakeLastResult) return
  try {
    const result = await desktopBridge.migrationTakeLastResult()
    if (!result) return
    if (result.ok) {
      pushToast(t('setup.runtime.migrationDone'))
    } else {
      pushToast(t('setup.runtime.migrationFailed', {
        detail: result.detail || t('setup.runtime.uninstallCheckLog'),
      }), { tone: 'danger' })
    }
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  }
}

onMounted(() => {
  void loadStatus()
  void showLastMigrationResult()
})
onUnmounted(unsubscribeMigrationProgress)
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.runtime.title') }}</h3>
      <p class="control-section__desc">{{ t('setup.runtime.desc') }}</p>
    </div>

    <div class="runtime-grid">
      <GatewayStatusBlock :label="t('setup.runtime.gateway')" :value="loading ? t('setup.runtime.loading') : statusLabel" :hint="gatewayError || url" />
      <GatewayStatusBlock :label="t('setup.runtime.title')" :value="t('setup.runtime.local')" :hint="t('setup.runtime.localProcess')" />
      <GatewayStatusBlock :label="t('setup.runtime.gatewayLog')" :value="logAvailable ? t('setup.runtime.available') : t('setup.runtime.unavailable')" :hint="logHint" />
    </div>

    <div class="runtime-actions">
      <button type="button" class="btn btn--ghost" :disabled="loading || busy" @click="loadStatus">
        <Icon name="refresh" :size="15" />
        <span>{{ t('setup.runtime.refresh') }}</span>
      </button>
      <button v-if="canRevealLog" type="button" class="btn btn--ghost" :disabled="!logAvailable" @click="revealLog">
        <Icon name="logs" :size="15" />
        <span>{{ t('setup.runtime.revealLog') }}</span>
      </button>
      <button v-if="canRestart" type="button" class="btn btn--ghost" :disabled="busy" @click="restartGateway">
        <Icon name="refresh" :size="15" />
        <span>{{ t('setup.runtime.restartRuntime') }}</span>
      </button>
    </div>

    <SettingsUpdatePanel />

    <div v-if="canReset" class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.resetLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.resetDesc') }}</span>
      </div>
      <div class="control-row__control">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="resetSetup">
          {{ t('setup.runtime.resetButton') }}
        </button>
      </div>
    </div>

    <div v-if="canMigrate" class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.migrationLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.migrationDesc') }}</span>
      </div>
      <div class="control-row__control">
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="busy || migrationBusy || migrationOpen"
          data-testid="runtime-migration-open"
          @click="openMigration"
        >
          {{ t('setup.runtime.migrationButton') }}
        </button>
      </div>
    </div>

    <div
      v-if="migrationOpen && migrationSummary && migrationCandidate"
      class="migration-summary"
      data-testid="runtime-migration-summary"
    >
      <div class="migration-summary__head">
        <span class="migration-summary__title">{{ t('setup.runtime.migrationSummaryTitle') }}</span>
        <span class="migration-summary__kind">{{ migrationCandidate.kind }}</span>
      </div>
      <code class="migration-summary__path">{{ migrationCandidate.path }}</code>
      <ul class="migration-summary__facts">
        <li>{{ migrationCountsText }}</li>
        <li>{{ t('setup.runtime.migrationPausedJobs', { n: migrationSummary.pausedJobs }) }}</li>
        <li>{{ migrationDiskText }}</li>
      </ul>
      <ul v-if="migrationSummary.errorNotes.length" class="migration-summary__errors">
        <li v-for="note in migrationSummary.errorNotes" :key="note">{{ note }}</li>
      </ul>
      <ul v-if="migrationSummary.notes.length" class="migration-summary__notes">
        <li v-for="note in migrationSummary.notes" :key="note">{{ note }}</li>
      </ul>
      <label
        v-if="migrationSummary.needsOverwrite"
        class="migration-summary__overwrite"
        data-testid="runtime-migration-overwrite"
      >
        <input v-model="migrationOverwrite" type="checkbox" />
        <span>{{ t('setup.runtime.migrationOverwrite') }}</span>
      </label>
      <p v-if="migrationPhase" class="migration-summary__phase" role="status" aria-live="polite">
        {{ t('setup.runtime.migrationPhase', { phase: migrationPhase }) }}
      </p>
      <div class="migration-summary__actions">
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="migrationBusy"
          data-testid="runtime-migration-cancel"
          @click="cancelMigration"
        >
          {{ t('setup.runtime.migrationCancel') }}
        </button>
        <button
          type="button"
          class="btn"
          :disabled="migrationBusy || migrationHasBlockingErrors || (migrationSummary.needsOverwrite && !migrationOverwrite)"
          data-testid="runtime-migration-run"
          @click="runMigration"
        >
          {{ t('setup.runtime.migrationImport') }}
        </button>
      </div>
    </div>

    <div v-if="canUninstall" class="control-row danger-zone">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.uninstallLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.uninstallDesc') }}</span>
      </div>
      <div class="control-row__control danger-zone__actions">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(false)">
          {{ t('setup.runtime.uninstallKeepData') }}
        </button>
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(true)">
          {{ t('setup.runtime.uninstallPurge') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.runtime-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.runtime-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.runtime-reset {
  color: var(--danger);
}

.danger-zone__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

/* Inline dry-run summary + confirm block for the legacy-home import */
.migration-summary {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
}

.migration-summary__head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
}

.migration-summary__title {
  font-weight: 700;
}

.migration-summary__kind {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.migration-summary__path {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  word-break: break-all;
}

.migration-summary__facts,
.migration-summary__errors,
.migration-summary__notes {
  margin: 0;
  padding-left: var(--sp-4);
  font-size: var(--fs-sm);
}

.migration-summary__errors {
  color: var(--danger);
}

.migration-summary__notes {
  color: var(--text-muted);
}

.migration-summary__overwrite {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
}

.migration-summary__phase {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.migration-summary__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
}
</style>
