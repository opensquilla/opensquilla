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
import {
  formatEstimatedActivity,
  profileSourceLabelKey,
  profileSourceGroup,
  type ProfileSourceKind,
} from '@/utils/profileSourceKind'

const { t, locale } = useI18n()

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
interface MigrationTerminalResult {
  ok: boolean
  migrationApplied?: boolean
  restartOk?: boolean
  requiresProviderSetup?: boolean
  source?: string
  sourceKind?: ProfileSourceKind
  targetReplaced?: boolean
  detail?: string
}

interface MigrationCandidate {
  kind: string
  path: string
  version?: string | null
  estimated_activity_at?: string | null
  session_count?: number | null
  size_bytes?: number | null
  previously_imported?: boolean
}

interface MigrationBridge {
  migrationSummary?: (payload?: { source?: string }) => Promise<{
    ok: boolean
    candidates?: MigrationCandidate[]
    candidate: MigrationCandidate | null
    report: unknown | null
    previewId?: string
    raw?: string
    requiresSelection?: boolean
  }>
  migrationRun?: (opts: { overwrite?: boolean; previewId: string }) => Promise<
    MigrationTerminalResult & {
    aborted?: boolean
    report?: unknown
  }>
  migrationBrowseSource?: (payload: { kind: ProfileSourceKind }) => Promise<{
    ok: boolean
    aborted?: boolean
    candidate?: MigrationCandidate | null
    detail?: string
    error?: string
  }>
  migrationTakeLastResult?: () => Promise<MigrationTerminalResult | null>
  migrationPeekLastResult?: () => Promise<MigrationTerminalResult | null>
  migrationDismissLastResult?: () => Promise<{ ok: boolean }>
  revealRecoveryPath?: (payload: { target: 'backups' }) => Promise<boolean>
  onMigrationProgress?: (cb: (state: { phase: string; detail?: string }) => void) => () => void
}

const MANUAL_MIGRATION_SOURCE_KINDS: ProfileSourceKind[] = [
  'cli-home',
  'desktop-home',
  'windows-portable',
]

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
const migrationCandidates = ref<MigrationCandidate[]>([])
const migrationCandidate = ref<MigrationCandidate | null>(null)
const migrationSummary = shallowRef<MigrationReportSummary | null>(null)
const migrationPreviewId = ref('')
const migrationOverwrite = ref(false)
const migrationPhase = ref('')
const migrationLastResult = shallowRef<MigrationTerminalResult | null>(null)
let migrationProgressUnsub: (() => void) | null = null

const migrationCandidateGroups = computed(() => ([
  {
    key: 'supported',
    label: t('setup.runtime.migrationSupportedSources'),
    candidates: migrationCandidates.value.filter((candidate) => (
      profileSourceGroup(candidate.kind) === 'supported'
    )),
  },
  {
    key: 'historical',
    label: t('setup.runtime.migrationHistoricalSources'),
    candidates: migrationCandidates.value.filter((candidate) => (
      profileSourceGroup(candidate.kind) === 'historical'
    )),
  },
  {
    key: 'other',
    label: t('setup.runtime.migrationOtherSources'),
    candidates: migrationCandidates.value.filter((candidate) => (
      profileSourceGroup(candidate.kind) === 'unknown'
    )),
  },
]).filter((group) => group.candidates.length > 0))

const migrationCountsText = computed(() => {
  const summary = migrationSummary.value
  if (!summary) return ''
  const c = summary.itemCounts
  const parts: string[] = []
  if (c.planned) parts.push(t('setup.runtime.migrationCountPlanned', { n: c.planned }))
  if (c.migrated) parts.push(t('setup.runtime.migrationCountMigrated', { n: c.migrated }))
  if (c.skipped) parts.push(t('setup.runtime.migrationCountSkipped', { n: c.skipped }))
  if (summary.errorNotes.length) {
    parts.push(t('setup.runtime.migrationCountError', {
      n: summary.errorNotes.length,
    }))
  }
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
  return summary.errorNotes.length > 0
})

function migrationSourceLabel(kind: string): string {
  return t(profileSourceLabelKey(kind))
}

function migrationActivityLabel(value?: string | null): string {
  if (!value) return t('setup.runtime.migrationCandidateActivityUnavailable')
  const relative = formatEstimatedActivity(value, locale.value)
  return relative
    ? t('setup.runtime.migrationCandidateActivityEstimate', { value: relative })
    : t('setup.runtime.migrationCandidateActivityUnavailable')
}

async function copyMigrationPath(path: string) {
  try {
    await navigator.clipboard.writeText(path)
    pushToast(t('setup.runtime.migrationPathCopied'))
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  }
}

function isMigrationCandidate(value: unknown): value is MigrationCandidate {
  return value !== null
    && typeof value === 'object'
    && typeof (value as MigrationCandidate).path === 'string'
    && Boolean((value as MigrationCandidate).path)
    && typeof (value as MigrationCandidate).kind === 'string'
}

function uniqueMigrationCandidates(candidates: MigrationCandidate[]): MigrationCandidate[] {
  const seen = new Set<string>()
  return candidates.filter((candidate) => {
    const key = `${candidate.kind}\u0000${candidate.path}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

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
    const detected = Array.isArray(result.candidates)
      ? result.candidates.filter(isMigrationCandidate)
      : []
    if (isMigrationCandidate(result.candidate)) detected.push(result.candidate)
    const candidates = uniqueMigrationCandidates(detected)

    if (result.requiresSelection || candidates.length > 0) {
      migrationCandidates.value = candidates
      migrationCandidate.value = null
      migrationSummary.value = null
      migrationPreviewId.value = ''
      migrationOverwrite.value = false
      migrationPhase.value = ''
      migrationOpen.value = true
      subscribeMigrationProgress()
      return
    }

    if (!result?.ok) {
      pushToast(t('setup.runtime.migrationSummaryFailed', {
        detail: result?.raw || t('setup.runtime.uninstallCheckLog'),
      }), { tone: 'danger' })
    } else {
      pushToast(t('setup.runtime.migrationNone'))
    }
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function previewMigrationCandidate(candidate: MigrationCandidate) {
  if (!desktopBridge?.migrationSummary) return
  migrationBusy.value = true
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationOverwrite.value = false
  migrationPhase.value = ''
  try {
    const result = await desktopBridge.migrationSummary({ source: candidate.path })
    if (
      result.report == null
      || typeof result.previewId !== 'string'
      || !result.previewId
      || !isMigrationCandidate(result.candidate)
      || result.candidate.path !== candidate.path
    ) {
      pushToast(t('setup.runtime.migrationSummaryFailed', {
        detail: result.raw || t('setup.runtime.uninstallCheckLog'),
      }), { tone: 'danger' })
      return
    }
    migrationCandidate.value = result.candidate
    migrationSummary.value = summarizeMigrationReport(result.report)
    migrationPreviewId.value = result.previewId
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function browseMigrationSource(kind: ProfileSourceKind) {
  if (!desktopBridge?.migrationBrowseSource) return
  migrationBusy.value = true
  try {
    const result = await desktopBridge.migrationBrowseSource({ kind })
    if (result.aborted) return
    if (!result.ok || !isMigrationCandidate(result.candidate)) {
      pushToast(t('setup.runtime.migrationSummaryFailed', {
        detail: result.detail || result.error || t('setup.runtime.uninstallCheckLog'),
      }), { tone: 'danger' })
      return
    }
    migrationCandidates.value = uniqueMigrationCandidates([
      ...migrationCandidates.value,
      result.candidate,
    ])
    await previewMigrationCandidate(result.candidate)
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

function cancelMigration() {
  migrationOpen.value = false
  migrationCandidates.value = []
  migrationCandidate.value = null
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationPhase.value = ''
  unsubscribeMigrationProgress()
}

function backToMigrationSources() {
  migrationCandidate.value = null
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationOverwrite.value = false
  migrationPhase.value = ''
}

async function runMigration() {
  if (!desktopBridge?.migrationRun || !migrationOpen.value || !migrationPreviewId.value) return
  // Replacement has one trusted native confirmation in Electron after the
  // preview is revalidated. Empty-target imports use the shared Web UI dialog.
  if (!migrationOverwrite.value) {
    const ok = await confirm({
      title: t('setup.runtime.migrationConfirmTitle'),
      body: t('setup.runtime.migrationConfirmBody'),
      primaryLabel: t('setup.runtime.migrationConfirmPrimary'),
    })
    if (!ok) return
  }
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
    if (!result?.ok) {
      pushToast(t('setup.runtime.migrationFailed', { detail: result?.detail || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      return
    }
    migrationLastResult.value = result
    pushToast(t('setup.runtime.migrationDone'))
    cancelMigration()
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function showLastMigrationResult() {
  const readResult = desktopBridge?.migrationPeekLastResult
    ?? desktopBridge?.migrationTakeLastResult
  if (!readResult) return
  try {
    const result = await readResult()
    if (!result) return
    migrationLastResult.value = result
    if (result.ok) {
      pushToast(t('setup.runtime.migrationDone'))
    } else {
      pushToast(t('setup.runtime.migrationFailed', {
        detail: result.detail || t('setup.runtime.uninstallCheckLog'),
      }), { tone: 'danger' })
      await desktopBridge?.migrationDismissLastResult?.().catch(() => null)
      migrationLastResult.value = null
    }
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  }
}

async function dismissLastMigrationResult() {
  try {
    await desktopBridge?.migrationDismissLastResult?.()
  } finally {
    migrationLastResult.value = null
  }
}

async function revealMigrationBackups() {
  try {
    await desktopBridge?.revealRecoveryPath?.({ target: 'backups' })
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
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

    <div
      v-if="migrationLastResult?.ok"
      class="migration-complete"
      role="status"
      data-testid="runtime-migration-complete"
    >
      <strong>{{ t('setup.runtime.migrationCompleteTitle') }}</strong>
      <p>{{ t('setup.runtime.migrationCompleteCopied') }}</p>
      <p v-if="migrationLastResult.source">
        {{ t('setup.runtime.migrationCompleteSource', { path: migrationLastResult.source }) }}
      </p>
      <p>{{ t('setup.runtime.migrationCompleteIndependent') }}</p>
      <p v-if="migrationLastResult.targetReplaced">
        {{ t('setup.runtime.migrationCompleteReplacement') }}
      </p>
      <div class="migration-complete__actions">
        <button
          v-if="migrationLastResult.targetReplaced && desktopBridge?.revealRecoveryPath"
          type="button"
          class="btn btn--ghost"
          @click="revealMigrationBackups"
        >
          {{ t('setup.runtime.migrationCompleteShowBackup') }}
        </button>
        <button type="button" class="btn btn--ghost" @click="dismissLastMigrationResult">
          {{ t('setup.runtime.migrationCompleteDismiss') }}
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
      v-if="migrationOpen"
      class="migration-summary"
      data-testid="runtime-migration-summary"
      :aria-busy="migrationBusy"
    >
      <template v-if="!migrationCandidate || !migrationSummary">
        <div class="migration-summary__head">
          <span class="migration-summary__title">{{ t('setup.runtime.migrationChooseSource') }}</span>
        </div>
        <p class="migration-summary__source-help">
          {{ t('setup.runtime.migrationChooseSourceDesc') }}
        </p>
        <section
          v-for="group in migrationCandidateGroups"
          :key="group.key"
          class="migration-candidate-group"
          :data-testid="`runtime-migration-${group.key}`"
        >
          <h4>{{ group.label }}</h4>
          <ul class="migration-candidates">
            <li v-for="candidate in group.candidates" :key="`${candidate.kind}:${candidate.path}`">
              <button
                type="button"
                class="migration-candidate"
                :disabled="migrationBusy"
                :aria-label="t('setup.runtime.migrationPreviewSource', { path: candidate.path })"
                @click="previewMigrationCandidate(candidate)"
              >
                <span class="migration-candidate__head">
                  <strong>{{ migrationSourceLabel(candidate.kind) }}</strong>
                  <span>
                    {{ candidate.version || t('setup.runtime.migrationCandidateVersionUnavailable') }}
                  </span>
                </span>
                <code>{{ candidate.path }}</code>
                <span class="migration-candidate__meta">
                  <span v-if="candidate.session_count != null">
                    {{ t('setup.runtime.migrationCandidateSessions', { n: candidate.session_count }) }}
                  </span>
                  <span v-else>{{ t('setup.runtime.migrationCandidateSessionsUnavailable') }}</span>
                  <span>
                    {{ candidate.size_bytes != null
                      ? formatByteSize(candidate.size_bytes)
                      : t('setup.runtime.migrationCandidateSizeUnavailable') }}
                  </span>
                  <span>{{ migrationActivityLabel(candidate.estimated_activity_at) }}</span>
                  <span v-if="candidate.previously_imported">
                    {{ t('setup.runtime.migrationCandidatePreviouslyImported') }}
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </section>
        <div class="migration-summary__actions">
          <template v-if="desktopBridge?.migrationBrowseSource">
            <button
              v-for="kind in MANUAL_MIGRATION_SOURCE_KINDS"
              :key="kind"
              type="button"
              class="btn btn--ghost"
              :data-testid="`runtime-migration-browse-${kind}`"
              :disabled="migrationBusy"
              @click="browseMigrationSource(kind)"
            >
              {{ t('setup.runtime.migrationBrowseSourceKind', {
                source: migrationSourceLabel(kind),
              }) }}
            </button>
          </template>
          <button
            type="button"
            class="btn btn--ghost"
            :disabled="migrationBusy"
            data-testid="runtime-migration-cancel"
            @click="cancelMigration"
          >
            {{ t('setup.runtime.migrationCancel') }}
          </button>
        </div>
      </template>
      <template v-else>
        <div class="migration-summary__head">
          <span class="migration-summary__title">{{ t('setup.runtime.migrationSummaryTitle') }}</span>
          <span class="migration-summary__kind">
            {{ migrationSourceLabel(migrationCandidate.kind) }}
          </span>
        </div>
        <div class="migration-summary__path-row">
          <code class="migration-summary__path">{{ migrationCandidate.path }}</code>
          <button
            type="button"
            class="btn btn--ghost"
            data-testid="runtime-migration-copy-path"
            @click="copyMigrationPath(migrationCandidate.path)"
          >
            {{ t('setup.runtime.migrationCopyPath') }}
          </button>
        </div>
        <ul class="migration-summary__content" data-testid="runtime-migration-content">
          <li>{{ t('setup.runtime.migrationContentIdentity') }}</li>
          <li>
            {{ t('setup.runtime.migrationContentChats', {
              n: migrationCandidate.session_count ?? 0,
            }) }}
          </li>
          <li>{{ t('setup.runtime.migrationContentSettings') }}</li>
          <li>{{ t('setup.runtime.migrationContentAssets') }}</li>
          <li>{{ t('setup.runtime.migrationContentJobs', { n: migrationSummary.pausedJobs }) }}</li>
        </ul>
        <ul v-if="migrationSummary.errorNotes.length" class="migration-summary__errors">
          <li v-for="note in migrationSummary.errorNotes" :key="note">{{ note }}</li>
        </ul>
        <div
          v-if="migrationSummary.needsOverwrite"
          class="migration-summary__replacement"
          data-testid="runtime-migration-replacement"
        >
          <strong>{{ t('setup.runtime.migrationReplacementTitle') }}</strong>
          <p v-if="migrationSummary.replacementReason">
            {{ migrationSummary.replacementReason }}
          </p>
          <label data-testid="runtime-migration-overwrite">
            <input v-model="migrationOverwrite" type="checkbox" />
            <span>{{ t('setup.runtime.migrationOverwrite') }}</span>
          </label>
        </div>
        <details class="migration-summary__technical" data-testid="runtime-migration-technical">
          <summary>{{ t('setup.runtime.migrationTechnicalDetails') }}</summary>
          <ul class="migration-summary__facts">
            <li>{{ migrationCountsText }}</li>
            <li>{{ migrationDiskText }}</li>
          </ul>
          <ul v-if="migrationSummary.notes.length" class="migration-summary__notes">
            <li v-for="note in migrationSummary.notes" :key="note">{{ note }}</li>
          </ul>
        </details>
        <p v-if="migrationPhase" class="migration-summary__phase" role="status" aria-live="polite">
          {{ t('setup.runtime.migrationPhase', { phase: migrationPhase }) }}
        </p>
        <div class="migration-summary__actions">
          <button
            v-if="migrationCandidates.length > 0 || desktopBridge?.migrationBrowseSource"
            type="button"
            class="btn btn--ghost"
            :disabled="migrationBusy"
            @click="backToMigrationSources"
          >
            {{ t('setup.runtime.migrationBackToSources') }}
          </button>
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
      </template>
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

.migration-complete {
  display: grid;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--success, var(--ok));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--success, var(--ok)) 8%, var(--bg-elevated));
}

.migration-complete p,
.migration-candidate-group h4 {
  margin: 0;
  font-size: var(--fs-sm);
}

.migration-complete__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

/* Inline source selection, dry-run summary, and confirmation. */
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

.migration-summary__source-help {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.migration-candidates {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.migration-candidate-group {
  display: grid;
  gap: var(--sp-2);
}

.migration-candidate {
  display: grid;
  width: 100%;
  gap: var(--sp-1);
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: inherit;
  background: var(--bg);
  text-align: left;
  cursor: pointer;
}

.migration-candidate:hover,
.migration-candidate:focus-visible {
  border-color: var(--accent);
}

.migration-candidate__head,
.migration-candidate__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.migration-candidate code {
  overflow-wrap: anywhere;
  font-size: var(--fs-xs);
}

.migration-candidate__meta {
  color: var(--text-muted);
  font-size: var(--fs-xs);
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

.migration-summary__path-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.migration-summary__path-row code {
  min-width: 0;
  flex: 1;
}

.migration-summary__facts,
.migration-summary__content,
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

.migration-summary__replacement {
  display: grid;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--warn);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--warn) 8%, var(--bg-elevated));
  font-size: var(--fs-sm);
}

.migration-summary__replacement p {
  margin: 0;
}

.migration-summary__replacement label {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.migration-summary__technical summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.migration-summary__phase {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.migration-summary__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--sp-2);
}
</style>
