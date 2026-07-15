<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
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
// owns its local gateway process, so this surfaces status/log/restart plus the
// inventory-driven profile cleanup flow. Web never renders this (desktopOnly
// section).
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

type CleanupMode = 'reset-current-settings' | 'delete-current-profile' | 'delete-all-user-data'
interface CleanupItem {
  kind: string
  path: string
  exists: boolean
  identity: string | null
}
interface CleanupReport {
  schema_version: 1
  outcome: 'ready' | 'blocked' | 'complete' | 'partial'
  stable_code: string
  mode: CleanupMode
  items: CleanupItem[]
  transaction_id: string
  revision: number
  scope_fingerprint: string
}
interface CleanupBridge {
  inspectDesktopCleanup?: (payload: { mode: CleanupMode }) => Promise<{
    ok: boolean
    previewId: string | null
    report: CleanupReport
    profile: { kind: 'primary' | 'recovery'; recoveryId: string | null }
  }>
  discardDesktopCleanup?: (payload: { previewId: string }) => Promise<boolean>
  applyDesktopCleanup?: (payload: {
    previewId: string
    acknowledged: boolean
    confirmation: string
  }) => Promise<{
    ok: boolean
    aborted?: boolean
    scheduled?: boolean
    partial?: boolean
    previewId?: string | null
    report?: CleanupReport
    profile?: { kind: 'primary' | 'recovery'; recoveryId: string | null }
    detail?: string
  }>
  revealDesktopUserData?: () => Promise<boolean>
}

// Cross-installation transfer rides the same preload bridge (also desktop-only and
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
  failureCode?: string
  failureStage?: 'preflight' | 'apply' | 'restart'
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
  getDesktopProfileKind?: () => Promise<unknown>
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
  globalThis as unknown as { opensquillaDesktop?: CleanupBridge & MigrationBridge }
).opensquillaDesktop
const canCleanup = computed(() => Boolean(
  desktopBridge?.inspectDesktopCleanup
  && desktopBridge?.discardDesktopCleanup
  && desktopBridge?.applyDesktopCleanup,
))
const hasMigrationBridge = computed(
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

const cleanupOpen = ref(false)
const cleanupBusy = ref(false)
const cleanupPreviewId = ref('')
const cleanupReport = shallowRef<CleanupReport | null>(null)
const cleanupProfile = ref<{ kind: 'primary' | 'recovery'; recoveryId: string | null } | null>(null)
const cleanupAcknowledged = ref(false)
const cleanupConfirmation = ref('')
const cleanupTitleEl = ref<HTMLElement | null>(null)
const cleanupReturnFocusEl = ref<HTMLElement | null>(null)
const DELETE_ALL_CONFIRMATION = 'DELETE ALL OPENSQUILLA DATA'

const cleanupExistingCount = computed(() => (
  cleanupReport.value?.items.filter((item) => item.exists).length ?? 0
))
const cleanupNeedsAcknowledgement = computed(() => (
  cleanupReport.value?.outcome === 'ready'
  && Boolean(cleanupPreviewId.value)
  && cleanupReport.value?.mode !== 'reset-current-settings'
))
const cleanupCanApply = computed(() => {
  const report = cleanupReport.value
  if (!report || report.outcome !== 'ready' || !cleanupPreviewId.value) return false
  if (cleanupNeedsAcknowledgement.value && !cleanupAcknowledged.value) return false
  return report.mode !== 'delete-all-user-data'
    || cleanupConfirmation.value === DELETE_ALL_CONFIRMATION
})
const cleanupModeTitle = computed(() => {
  const mode = cleanupReport.value?.mode
  return mode ? t(`setup.runtime.cleanup.${mode}.title`) : ''
})
const cleanupModeWarning = computed(() => {
  const mode = cleanupReport.value?.mode
  return mode ? t(`setup.runtime.cleanup.${mode}.warning`) : ''
})
const cleanupApplyLabel = computed(() => {
  const mode = cleanupReport.value?.mode
  return mode ? t(`setup.runtime.cleanup.${mode}.apply`) : ''
})

async function openCleanup(mode: CleanupMode, trigger?: EventTarget | null) {
  if (!desktopBridge?.inspectDesktopCleanup) return
  if (trigger instanceof HTMLElement) cleanupReturnFocusEl.value = trigger
  cleanupBusy.value = true
  cleanupOpen.value = false
  cleanupPreviewId.value = ''
  cleanupReport.value = null
  cleanupAcknowledged.value = false
  cleanupConfirmation.value = ''
  try {
    const result = await desktopBridge.inspectDesktopCleanup({ mode })
    cleanupReport.value = result.report
    cleanupProfile.value = result.profile
    cleanupPreviewId.value = result.previewId || ''
    cleanupOpen.value = true
    await nextTick()
    cleanupTitleEl.value?.focus()
  } catch (err) {
    pushToast(t('setup.runtime.cleanup.inspectFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  } finally {
    cleanupBusy.value = false
  }
}

function clearCleanupState() {
  cleanupOpen.value = false
  cleanupPreviewId.value = ''
  cleanupReport.value = null
  cleanupProfile.value = null
  cleanupAcknowledged.value = false
  cleanupConfirmation.value = ''
}

async function closeCleanupAndRestoreFocus() {
  const returnFocus = cleanupReturnFocusEl.value
  clearCleanupState()
  cleanupReturnFocusEl.value = null
  await nextTick()
  returnFocus?.focus()
}

async function cancelCleanup() {
  const previewId = cleanupPreviewId.value
  if (previewId && desktopBridge?.discardDesktopCleanup) {
    cleanupBusy.value = true
    try {
      await desktopBridge.discardDesktopCleanup({ previewId })
    } catch (err) {
      pushToast(t('setup.runtime.cleanup.applyFailed', {
        detail: err instanceof Error ? err.message : String(err),
      }), { tone: 'danger' })
      cleanupBusy.value = false
      return
    }
    cleanupBusy.value = false
  }
  await closeCleanupAndRestoreFocus()
}

async function presentCleanupResult(result: {
  previewId?: string | null
  report?: CleanupReport
  profile?: { kind: 'primary' | 'recovery'; recoveryId: string | null }
}) {
  if (result.report) cleanupReport.value = result.report
  cleanupPreviewId.value = result.previewId || ''
  if (result.profile) cleanupProfile.value = result.profile
  cleanupAcknowledged.value = false
  cleanupConfirmation.value = ''
  cleanupOpen.value = Boolean(cleanupReport.value)
  await nextTick()
  cleanupTitleEl.value?.focus()
}

async function revealCleanupLocation() {
  if (!desktopBridge?.revealDesktopUserData) return
  try {
    await desktopBridge.revealDesktopUserData()
  } catch (err) {
    pushToast(t('setup.runtime.cleanup.revealFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  }
}

async function applyCleanup() {
  const report = cleanupReport.value
  if (!desktopBridge?.applyDesktopCleanup || !report || !cleanupCanApply.value) return
  if (report.mode === 'reset-current-settings') {
    const approved = await confirm({
      title: t('setup.runtime.cleanup.resetConfirmTitle'),
      body: t('setup.runtime.cleanup.resetConfirmBody'),
      primaryLabel: cleanupApplyLabel.value,
    })
    if (!approved) return
  }
  cleanupBusy.value = true
  try {
    const result = await desktopBridge.applyDesktopCleanup({
      previewId: cleanupPreviewId.value,
      acknowledged: cleanupAcknowledged.value,
      confirmation: cleanupConfirmation.value,
    })
    if (result.aborted) {
      await presentCleanupResult(result)
      return
    }
    if (!result.ok) {
      await presentCleanupResult(result)
      pushToast(t(
        result.partial
          ? 'setup.runtime.cleanup.partial'
          : 'setup.runtime.cleanup.applyFailed',
        { detail: result.detail || result.report?.stable_code || '' },
      ), { tone: 'danger' })
      return
    }
    pushToast(t(
      result.scheduled
        ? 'setup.runtime.cleanup.deleteAllScheduled'
        : report.mode === 'reset-current-settings'
          ? 'setup.runtime.cleanup.resetDone'
          : 'setup.runtime.cleanup.deleteDone',
    ))
    await closeCleanupAndRestoreFocus()
  } catch (err) {
    pushToast(t('setup.runtime.cleanup.applyFailed', {
      detail: err instanceof Error ? err.message : String(err),
    }), { tone: 'danger' })
  } finally {
    cleanupBusy.value = false
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
const migrationProfileKind = ref<'primary' | 'recovery' | 'unknown'>('unknown')
const migrationTitleEl = ref<HTMLElement | null>(null)
const migrationTriggerEl = ref<HTMLButtonElement | null>(null)
let migrationProgressUnsub: (() => void) | null = null

const canMigrate = computed(() => (
  migrationProfileKind.value === 'primary' && hasMigrationBridge.value
))
const migrationUnavailableInRecovery = computed(() => (
  migrationProfileKind.value === 'recovery' && hasMigrationBridge.value
))

const RECOVERY_MIGRATION_DETAILS = new Set([
  'Import source selection is available only in the primary profile.',
  'Recovery profiles cannot import another profile.',
  'Return to the primary profile before importing data.',
])

const MIGRATION_FAILURE_DETAIL_KEYS: Record<string, string> = {
  source_snapshot_locked: 'setup.runtime.migrationFailureLocked',
  source_snapshot_changed: 'setup.runtime.migrationFailureChanged',
  source_snapshot_unreadable: 'setup.runtime.migrationFailureUnreadable',
  migration_apply_failed: 'setup.runtime.migrationFailureApply',
  gateway_restart_failed: 'setup.runtime.migrationFailureRestart',
}

function localizedMigrationDetail(value: unknown, failureCode?: string): string {
  const failureKey = failureCode ? MIGRATION_FAILURE_DETAIL_KEYS[failureCode] : undefined
  if (failureKey) return t(failureKey)
  const detail = typeof value === 'string' ? value.trim() : ''
  return RECOVERY_MIGRATION_DETAILS.has(detail)
    ? t('setup.runtime.migrationRecoveryProfile')
    : detail || t('setup.runtime.uninstallCheckLog')
}

const migrationFailureReason = computed(() => localizedMigrationDetail(
  migrationLastResult.value?.detail,
  migrationLastResult.value?.failureCode,
))

async function loadMigrationProfileContext(): Promise<void> {
  try {
    const kind = await desktopBridge?.getDesktopProfileKind?.()
    migrationProfileKind.value = kind === 'primary' || kind === 'recovery' ? kind : 'unknown'
  } catch {
    // Fail closed: without a verified primary profile, do not expose a profile writer.
    migrationProfileKind.value = 'unknown'
  }
}

async function focusMigrationTitle(): Promise<void> {
  await nextTick()
  migrationTitleEl.value?.focus()
}

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
const migrationRunLabel = computed(() => t(
  migrationSummary.value?.needsOverwrite
    ? 'setup.runtime.migrationBackupAndReplace'
    : 'setup.runtime.migrationCopyAndUse',
))

function migrationSourceLabel(kind: string): string {
  return t(profileSourceLabelKey(kind))
}

function migrationActivityLabel(value?: string | null): string {
  if (!value) return ''
  const relative = formatEstimatedActivity(value, locale.value)
  return relative
    ? t('setup.runtime.migrationCandidateActivityEstimate', { value: relative })
    : ''
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

// Row click: dry-run summary over the bridge, then the inline transfer confirmation.
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
      await focusMigrationTitle()
      return
    }

    if (!result?.ok) {
      pushToast(t('setup.runtime.migrationSummaryFailed', {
        detail: localizedMigrationDetail(result?.raw),
      }), { tone: 'danger' })
    } else {
      pushToast(t('setup.runtime.migrationNone'))
    }
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
    }), { tone: 'danger' })
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
        detail: localizedMigrationDetail(result.raw),
      }), { tone: 'danger' })
      return
    }
    migrationCandidate.value = result.candidate
    migrationSummary.value = summarizeMigrationReport(result.report)
    migrationPreviewId.value = result.previewId
    await focusMigrationTitle()
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
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
        detail: localizedMigrationDetail(result.detail || result.error),
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
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
    }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function cancelMigration(restoreFocus = true) {
  migrationOpen.value = false
  migrationCandidates.value = []
  migrationCandidate.value = null
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationPhase.value = ''
  unsubscribeMigrationProgress()
  if (restoreFocus) {
    await nextTick()
    migrationTriggerEl.value?.focus()
  }
}

async function backToMigrationSources() {
  migrationCandidate.value = null
  migrationSummary.value = null
  migrationPreviewId.value = ''
  migrationOverwrite.value = false
  migrationPhase.value = ''
  await focusMigrationTitle()
}

async function runMigration() {
  if (!desktopBridge?.migrationRun || !migrationOpen.value || !migrationPreviewId.value) return
  // Replacement has one trusted native confirmation in Electron after the
  // preview is revalidated. Empty-target copies use the shared Web UI dialog.
  if (!migrationOverwrite.value) {
    const ok = await confirm({
      title: t('setup.runtime.migrationConfirmTitle'),
      body: t('setup.runtime.migrationConfirmBody'),
      primaryLabel: t('setup.runtime.migrationConfirmPrimary'),
    })
    if (!ok) return
  }
  migrationBusy.value = true
  // Validation and preparation happen before any target replacement. The main
  // process persists the terminal result so a replacement renderer can show it.
  pushToast(t('setup.runtime.migrationStarted'))
  try {
    const result = await desktopBridge.migrationRun({
      overwrite: migrationOverwrite.value,
      previewId: migrationPreviewId.value,
    })
    if (result?.aborted) return
    migrationLastResult.value = result
    if (!result?.ok) {
      pushToast(t('setup.runtime.migrationFailed', {
        detail: localizedMigrationDetail(result?.detail, result?.failureCode),
      }), { tone: 'danger' })
      await cancelMigration(false)
      return
    }
    pushToast(t('setup.runtime.migrationDone'))
    await cancelMigration(false)
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', {
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
    }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function showLastMigrationResult() {
  if (migrationProfileKind.value !== 'primary') return
  const readResult = desktopBridge?.migrationPeekLastResult
    ?? desktopBridge?.migrationTakeLastResult
  if (!readResult) return
  try {
    const result = await readResult()
    if (!result) return
    migrationLastResult.value = result
    if (result.ok) {
      pushToast(t('setup.runtime.migrationDone'))
    }
  } catch (err) {
    pushToast(t('setup.runtime.migrationFailed', {
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
    }), { tone: 'danger' })
  }
}

async function dismissLastMigrationResult() {
  try {
    await desktopBridge?.migrationDismissLastResult?.()
  } finally {
    migrationLastResult.value = null
    await nextTick()
    migrationTriggerEl.value?.focus()
  }
}

async function recheckLastMigrationSource() {
  const source = migrationLastResult.value?.source
  if (!source || !desktopBridge?.migrationSummary) return
  migrationBusy.value = true
  try {
    const result = await desktopBridge.migrationSummary({ source })
    if (
      result.report == null
      || typeof result.previewId !== 'string'
      || !result.previewId
      || !isMigrationCandidate(result.candidate)
      || result.candidate.path !== source
    ) {
      pushToast(t('setup.runtime.migrationSummaryFailed', {
        detail: localizedMigrationDetail(result.raw),
      }), { tone: 'danger' })
      return
    }
    const detected = Array.isArray(result.candidates)
      ? result.candidates.filter(isMigrationCandidate)
      : []
    migrationCandidates.value = uniqueMigrationCandidates([...detected, result.candidate])
    migrationCandidate.value = result.candidate
    migrationSummary.value = summarizeMigrationReport(result.report)
    migrationPreviewId.value = result.previewId
    migrationOverwrite.value = false
    migrationPhase.value = ''
    migrationOpen.value = true
    subscribeMigrationProgress()
    await focusMigrationTitle()
  } catch (err) {
    pushToast(t('setup.runtime.migrationSummaryFailed', {
      detail: localizedMigrationDetail(err instanceof Error ? err.message : String(err)),
    }), { tone: 'danger' })
  } finally {
    migrationBusy.value = false
  }
}

async function restartAfterMigration() {
  await restartGateway()
  if (gateway.value?.status === 'ready') await dismissLastMigrationResult()
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
  void loadMigrationProfileContext().then(() => {
    if (migrationProfileKind.value === 'primary') void showLastMigrationResult()
  })
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

    <div
      v-if="migrationProfileKind === 'primary' && migrationLastResult?.ok"
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
    <div
      v-else-if="migrationProfileKind === 'primary' && migrationLastResult && !migrationLastResult.migrationApplied"
      class="migration-complete migration-result--failure"
      role="alert"
      data-testid="runtime-migration-not-applied"
    >
      <strong>{{ t('setup.runtime.migrationNotAppliedTitle') }}</strong>
      <p>{{ t('setup.runtime.migrationNotAppliedUnchanged') }}</p>
      <p v-if="migrationLastResult.source">
        {{ t('setup.runtime.migrationCompleteSource', { path: migrationLastResult.source }) }}
      </p>
      <p>{{ migrationFailureReason }}</p>
      <div class="migration-complete__actions">
        <button
          v-if="migrationLastResult.source && desktopBridge?.migrationSummary"
          type="button"
          class="btn btn--ghost"
          :disabled="migrationBusy"
          data-testid="runtime-migration-recheck"
          @click="recheckLastMigrationSource"
        >
          {{ t('setup.runtime.migrationRecheckSource') }}
        </button>
        <button type="button" class="btn btn--ghost" @click="dismissLastMigrationResult">
          {{ t('setup.runtime.migrationCompleteDismiss') }}
        </button>
      </div>
    </div>
    <div
      v-else-if="migrationProfileKind === 'primary' && migrationLastResult"
      class="migration-complete migration-result--failure"
      role="alert"
      data-testid="runtime-migration-applied-restart-failed"
    >
      <strong>{{ t('setup.runtime.migrationAppliedRestartTitle') }}</strong>
      <p>{{ t('setup.runtime.migrationAppliedRestartCommitted') }}</p>
      <p v-if="migrationLastResult.source">
        {{ t('setup.runtime.migrationCompleteSource', { path: migrationLastResult.source }) }}
      </p>
      <p>{{ migrationFailureReason }}</p>
      <div class="migration-complete__actions">
        <button
          v-if="!migrationLastResult.restartOk && canRestart"
          type="button"
          class="btn btn--ghost"
          :disabled="busy"
          data-testid="runtime-migration-restart"
          @click="restartAfterMigration"
        >
          {{ t('setup.runtime.restartRuntime') }}
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
          ref="migrationTriggerEl"
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
      v-else-if="migrationUnavailableInRecovery"
      class="control-row"
      data-testid="runtime-migration-recovery-message"
    >
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.migrationLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.migrationRecoveryProfile') }}</span>
      </div>
    </div>

    <div
      v-if="migrationOpen"
      class="migration-summary"
      data-testid="runtime-migration-summary"
      :aria-busy="migrationBusy"
      aria-labelledby="runtime-migration-title"
    >
      <template v-if="!migrationCandidate || !migrationSummary">
        <div class="migration-summary__head">
          <h4
            id="runtime-migration-title"
            ref="migrationTitleEl"
            class="migration-summary__title"
            tabindex="-1"
            data-testid="runtime-migration-title"
          >
            {{ t('setup.runtime.migrationChooseSource') }}
          </h4>
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
                :aria-label="t('setup.runtime.migrationPreviewSource', {
                  source: migrationSourceLabel(candidate.kind),
                  path: candidate.path,
                })"
                @click="previewMigrationCandidate(candidate)"
              >
                <span class="migration-candidate__head">
                  <strong>{{ migrationSourceLabel(candidate.kind) }}</strong>
                  <span v-if="candidate.version">{{ candidate.version }}</span>
                </span>
                <code>{{ candidate.path }}</code>
                <span class="migration-candidate__meta">
                  <span v-if="candidate.session_count != null">
                    {{ t('setup.runtime.migrationCandidateSessions', { n: candidate.session_count }) }}
                  </span>
                  <span v-if="candidate.size_bytes != null">
                    {{ formatByteSize(candidate.size_bytes) }}
                  </span>
                  <span v-if="candidate.estimated_activity_at">
                    {{ migrationActivityLabel(candidate.estimated_activity_at) }}
                  </span>
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
            @click="cancelMigration()"
          >
            {{ t('setup.runtime.migrationCancel') }}
          </button>
        </div>
      </template>
      <template v-else>
        <div class="migration-summary__head">
          <h4
            id="runtime-migration-title"
            ref="migrationTitleEl"
            class="migration-summary__title"
            tabindex="-1"
            data-testid="runtime-migration-title"
          >
            {{ t('setup.runtime.migrationSummaryTitle') }}
          </h4>
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
          <li v-if="migrationCandidate.session_count != null">
            {{ t('setup.runtime.migrationContentChats', {
              n: migrationCandidate.session_count,
            }) }}
          </li>
          <li v-else>{{ t('setup.runtime.migrationContentChatsUnknown') }}</li>
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
            @click="cancelMigration()"
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
            {{ migrationRunLabel }}
          </button>
        </div>
      </template>
    </div>

    <div v-if="canCleanup" class="control-row danger-zone">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.cleanup.label') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.cleanup.desc') }}</span>
      </div>
      <div
        class="control-row__control danger-zone__actions"
        role="group"
        :aria-label="t('setup.runtime.cleanup.actionsLabel')"
      >
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="busy || cleanupBusy"
          data-testid="runtime-cleanup-reset"
          @click="openCleanup('reset-current-settings', $event.currentTarget)"
        >
          {{ t('setup.runtime.cleanup.resetAction') }}
        </button>
        <button
          type="button"
          class="btn btn--ghost runtime-reset"
          :disabled="busy || cleanupBusy"
          data-testid="runtime-cleanup-profile"
          @click="openCleanup('delete-current-profile', $event.currentTarget)"
        >
          {{ t('setup.runtime.cleanup.profileAction') }}
        </button>
        <button
          type="button"
          class="btn btn--ghost runtime-reset"
          :disabled="busy || cleanupBusy"
          data-testid="runtime-cleanup-all"
          @click="openCleanup('delete-all-user-data', $event.currentTarget)"
        >
          {{ t('setup.runtime.cleanup.allAction') }}
        </button>
      </div>
    </div>

    <section
      v-if="cleanupOpen && cleanupReport"
      class="cleanup-summary"
      aria-labelledby="cleanup-summary-title"
      data-testid="runtime-cleanup-summary"
    >
      <div class="cleanup-summary__head">
        <h4 id="cleanup-summary-title" ref="cleanupTitleEl" tabindex="-1">
          {{ cleanupModeTitle }}
        </h4>
        <span class="cleanup-summary__profile">
          {{ cleanupProfile?.kind === 'recovery'
            ? t('setup.runtime.cleanup.recoveryProfile')
            : t('setup.runtime.cleanup.primaryProfile') }}
        </span>
      </div>
      <p class="cleanup-summary__warning">{{ cleanupModeWarning }}</p>
      <p class="cleanup-summary__count">
        {{ t('setup.runtime.cleanup.inventoryCount', {
          existing: cleanupExistingCount,
          total: cleanupReport.items.length,
        }) }}
      </p>
      <ul class="cleanup-summary__items" :aria-label="t('setup.runtime.cleanup.inventoryLabel')">
        <li v-for="item in cleanupReport.items" :key="`${item.kind}:${item.path}`">
          <span class="cleanup-summary__item-kind">{{ item.kind }}</span>
          <code>{{ item.path }}</code>
          <span :class="item.exists ? 'cleanup-summary__present' : 'cleanup-summary__missing'">
            {{ item.exists
              ? t('setup.runtime.cleanup.present')
              : t('setup.runtime.cleanup.missing') }}
          </span>
        </li>
      </ul>
      <div
        v-if="cleanupReport.outcome === 'blocked'"
        class="cleanup-summary__blocked"
        role="alert"
      >
        <strong>{{ t('setup.runtime.cleanup.blocked') }}</strong>
        <code>{{ cleanupReport.stable_code }}</code>
        <p>{{ t('setup.runtime.cleanup.blockedHelp') }}</p>
      </div>
      <label v-if="cleanupNeedsAcknowledgement" class="cleanup-summary__ack">
        <input v-model="cleanupAcknowledged" type="checkbox" />
        <span>{{ t('setup.runtime.cleanup.acknowledge') }}</span>
      </label>
      <label
        v-if="cleanupReport.outcome === 'ready' && cleanupPreviewId && cleanupReport.mode === 'delete-all-user-data'"
        class="cleanup-summary__phrase"
      >
        <span>{{ t('setup.runtime.cleanup.typePhrase', { phrase: DELETE_ALL_CONFIRMATION }) }}</span>
        <input
          v-model="cleanupConfirmation"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :aria-label="t('setup.runtime.cleanup.phraseLabel')"
        />
      </label>
      <div class="cleanup-summary__actions">
        <button type="button" class="btn btn--ghost" :disabled="cleanupBusy" @click="revealCleanupLocation">
          {{ t('setup.runtime.cleanup.showLocation') }}
        </button>
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="cleanupBusy"
          data-testid="runtime-cleanup-cancel"
          @click="cancelCleanup"
        >
          {{ t('setup.runtime.cleanup.cancel') }}
        </button>
        <button
          v-if="cleanupReport.outcome === 'ready' && cleanupPreviewId"
          type="button"
          class="btn"
          :disabled="cleanupBusy || !cleanupCanApply"
          data-testid="runtime-cleanup-apply"
          @click="applyCleanup"
        >
          {{ cleanupApplyLabel }}
        </button>
        <button
          v-else
          type="button"
          class="btn"
          :disabled="cleanupBusy"
          @click="openCleanup(cleanupReport.mode)"
        >
          {{ t('setup.runtime.cleanup.retry') }}
        </button>
      </div>
      <p class="cleanup-summary__status" role="status" aria-live="polite">
        {{ cleanupBusy ? t('setup.runtime.cleanup.working') : '' }}
      </p>
    </section>
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

.migration-result--failure {
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-elevated));
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

.cleanup-summary {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--border));
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
}

.cleanup-summary__head,
.cleanup-summary__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.cleanup-summary__head h4,
.cleanup-summary__warning,
.cleanup-summary__count,
.cleanup-summary__blocked p,
.cleanup-summary__status {
  margin: 0;
}

.cleanup-summary__head h4:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.cleanup-summary__profile,
.cleanup-summary__count,
.cleanup-summary__missing {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.cleanup-summary__warning,
.cleanup-summary__blocked,
.cleanup-summary__present {
  color: var(--danger);
}

.cleanup-summary__items {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-height: 240px;
  overflow: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cleanup-summary__items li {
  display: grid;
  grid-template-columns: minmax(110px, auto) minmax(160px, 1fr) auto;
  align-items: baseline;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
}

.cleanup-summary__items code {
  overflow-wrap: anywhere;
}

.cleanup-summary__item-kind {
  font-weight: 650;
}

.cleanup-summary__blocked {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}

.cleanup-summary__ack,
.cleanup-summary__phrase {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
}

.cleanup-summary__phrase {
  flex-direction: column;
}

.cleanup-summary__phrase input {
  width: min(100%, 420px);
}

@media (max-width: 640px) {
  .cleanup-summary__items li {
    grid-template-columns: 1fr auto;
  }

  .cleanup-summary__items code {
    grid-column: 1 / -1;
  }
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
  margin: 0;
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
