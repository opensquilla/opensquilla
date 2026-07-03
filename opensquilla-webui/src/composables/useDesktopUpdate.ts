import { computed, ref } from 'vue'
import { getPlatform, type DesktopUpdateState } from '@/platform'

const idleUpdateState: DesktopUpdateState = {
  status: 'idle',
  currentVersion: '',
  latestVersion: null,
  progress: null,
  checkedAt: null,
  error: null,
  snoozedUntil: null,
  canNativeInstall: false,
  releaseUrl: null,
}

const TOPBAR_STATUSES = new Set(['available', 'downloading', 'downloaded', 'error'])

const state = ref<DesktopUpdateState>({ ...idleUpdateState })
const ready = ref(false)
const loading = ref(false)
const actionBusy = ref(false)

let initialized = false
let unsubscribe: (() => void) | null = null

function updateState(next: DesktopUpdateState) {
  state.value = { ...idleUpdateState, ...next }
  ready.value = true
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function snoozeActive(value: DesktopUpdateState): boolean {
  if (!value.snoozedUntil) return false
  const expiresAt = Date.parse(value.snoozedUntil)
  return Number.isFinite(expiresAt) && expiresAt > Date.now()
}

async function runAction(action: () => Promise<DesktopUpdateState>) {
  actionBusy.value = true
  try {
    updateState(await action())
  } catch (err) {
    updateState({
      ...state.value,
      status: 'error',
      error: errorMessage(err),
      progress: null,
    })
  } finally {
    actionBusy.value = false
  }
}

async function refreshDesktopUpdate() {
  const platform = getPlatform()
  if (!platform.capabilities.isDesktop) {
    updateState({ ...idleUpdateState })
    return
  }
  loading.value = true
  try {
    updateState(await platform.updates.getState())
  } catch (err) {
    updateState({
      ...idleUpdateState,
      status: 'error',
      error: errorMessage(err),
      canNativeInstall: true,
    })
  } finally {
    loading.value = false
  }
}

function initDesktopUpdate() {
  if (initialized) return
  initialized = true
  const platform = getPlatform()
  if (platform.capabilities.isDesktop) {
    unsubscribe = platform.updates.onState(updateState)
  }
  void refreshDesktopUpdate()
}

export function useDesktopUpdate() {
  const platform = getPlatform()
  const isNativeDesktopUpdate = computed(() => platform.capabilities.isDesktop && state.value.canNativeInstall)
  const visible = computed(() =>
    isNativeDesktopUpdate.value &&
    TOPBAR_STATUSES.has(state.value.status) &&
    !snoozeActive(state.value),
  )
  const latestVersion = computed(() => state.value.latestVersion || state.value.currentVersion || '')

  return {
    state,
    ready,
    loading,
    actionBusy,
    visible,
    latestVersion,
    isNativeDesktopUpdate,
    init: initDesktopUpdate,
    refresh: refreshDesktopUpdate,
    check: () => runAction(() => platform.updates.check()),
    download: () => runAction(() => platform.updates.download()),
    relaunch: () => runAction(() => platform.updates.relaunch()),
    dismiss: () => runAction(() => platform.updates.dismiss()),
  }
}

export function stopDesktopUpdateSubscriptionForTests() {
  unsubscribe?.()
  unsubscribe = null
  initialized = false
}
