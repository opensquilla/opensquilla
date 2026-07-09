import { desktopCapabilities } from './capabilities'
import type { CliInvocation, DesktopUpdateState, DesktopUpdateStatus, Platform } from './types'

function requireDesktopApi(): OpenSquillaDesktopApi {
  const api = window.opensquillaDesktop
  if (!api) throw new Error('OpenSquilla desktop API is unavailable.')
  return api
}

const UPDATE_STATUSES = new Set<DesktopUpdateStatus>([
  'idle',
  'checking',
  'available',
  'downloading',
  'downloaded',
  'not-available',
  'error',
  'applying',
])

function idleUpdateState(canNativeInstall: boolean): DesktopUpdateState {
  return {
    status: 'idle',
    currentVersion: '',
    latestVersion: null,
    progress: null,
    checkedAt: null,
    error: null,
    snoozedUntil: null,
    canNativeInstall,
    releaseUrl: null,
  }
}

function normalizeUpdateState(payload: unknown, canNativeInstall: boolean): DesktopUpdateState {
  const raw = payload && typeof payload === 'object'
    ? payload as Partial<Record<keyof DesktopUpdateState, unknown>>
    : {}
  const status = String(raw.status || '')
  const progress = typeof raw.progress === 'number' && Number.isFinite(raw.progress)
    ? Math.max(0, Math.min(100, raw.progress))
    : null
  return {
    status: UPDATE_STATUSES.has(status as DesktopUpdateStatus) ? status as DesktopUpdateStatus : 'idle',
    currentVersion: typeof raw.currentVersion === 'string' ? raw.currentVersion : '',
    latestVersion: typeof raw.latestVersion === 'string' && raw.latestVersion ? raw.latestVersion : null,
    progress,
    checkedAt: typeof raw.checkedAt === 'string' && raw.checkedAt ? raw.checkedAt : null,
    error: typeof raw.error === 'string' && raw.error ? raw.error : null,
    snoozedUntil: typeof raw.snoozedUntil === 'string' && raw.snoozedUntil ? raw.snoozedUntil : null,
    canNativeInstall: typeof raw.canNativeInstall === 'boolean' ? raw.canNativeInstall : canNativeInstall,
    releaseUrl: typeof raw.releaseUrl === 'string' && raw.releaseUrl ? raw.releaseUrl : null,
  }
}

async function nativeUpdateCapability(api: OpenSquillaDesktopApi): Promise<boolean> {
  if (typeof api.isAutoUpdateEnabled !== 'function') return true
  try {
    return await api.isAutoUpdateEnabled()
  } catch {
    return true
  }
}

async function desktopUpdateFallbackState(api: OpenSquillaDesktopApi): Promise<DesktopUpdateState> {
  return idleUpdateState(await nativeUpdateCapability(api))
}

export function createDesktopPlatform(): Platform {
  return {
    id: 'desktop',
    capabilities: desktopCapabilities,
    getOsLocale: () => requireDesktopApi().getOsLocale(),
    async setNativeTheme(payload) {
      const api = requireDesktopApi()
      if (typeof api.setNativeTheme !== 'function') return undefined
      return api.setNativeTheme(payload)
    },
    async nativeAutoUpdateEnabled() {
      const api = requireDesktopApi()
      // Older shells without this bridge are macOS-only with native update on;
      // default to true there so the web banner never double-notifies.
      return nativeUpdateCapability(api)
    },
    gateway: {
      getStatus: () => requireDesktopApi().getGatewayStatus(),
      revealLog: () => requireDesktopApi().revealGatewayLog(),
      retryStartup: () => requireDesktopApi().retryStartup(),
      async getCliInvocation(): Promise<CliInvocation | null> {
        const api = requireDesktopApi()
        if (typeof api.getCliInvocation !== 'function') return null
        try {
          const raw = await api.getCliInvocation() as Partial<CliInvocation> | null
          if (!raw || typeof raw.prefix !== 'string' || !raw.prefix.trim()) return null
          return { mode: raw.mode === 'dev' ? 'dev' : 'bundled', prefix: raw.prefix }
        } catch {
          return null
        }
      },
    },
    settings: {
      getDesktopSettings: () => requireDesktopApi().getDesktopSettings(),
      saveDesktopSettings: (payload) => requireDesktopApi().saveDesktopSettings(payload),
      resetDesktopSettings: () => requireDesktopApi().resetDesktopSettings(),
    },
    onboarding: {
      getDefaults: () => requireDesktopApi().getOnboardingDefaults(),
      save: (payload) => requireDesktopApi().saveOnboarding(payload),
      cancel: () => requireDesktopApi().cancelOnboarding(),
    },
    files: {
      openArtifact: (payload) => requireDesktopApi().openArtifact(payload),
    },
    updates: {
      async getState() {
        const api = requireDesktopApi()
        if (typeof api.getUpdateState !== 'function') return desktopUpdateFallbackState(api)
        return normalizeUpdateState(await api.getUpdateState(), await nativeUpdateCapability(api))
      },
      async check() {
        const api = requireDesktopApi()
        if (typeof api.checkForUpdates !== 'function') return desktopUpdateFallbackState(api)
        return normalizeUpdateState(await api.checkForUpdates(), await nativeUpdateCapability(api))
      },
      async download() {
        const api = requireDesktopApi()
        if (typeof api.downloadUpdate !== 'function') return desktopUpdateFallbackState(api)
        return normalizeUpdateState(await api.downloadUpdate(), await nativeUpdateCapability(api))
      },
      async relaunch() {
        const api = requireDesktopApi()
        if (typeof api.relaunchToUpdate !== 'function') return desktopUpdateFallbackState(api)
        return normalizeUpdateState(await api.relaunchToUpdate(), await nativeUpdateCapability(api))
      },
      async dismiss() {
        const api = requireDesktopApi()
        if (typeof api.dismissUpdate !== 'function') return desktopUpdateFallbackState(api)
        return normalizeUpdateState(await api.dismissUpdate(), await nativeUpdateCapability(api))
      },
      onState(callback) {
        const api = requireDesktopApi()
        if (typeof api.onUpdateState !== 'function') return () => undefined
        return api.onUpdateState((payload) => {
          void nativeUpdateCapability(api).then((canNativeInstall) => {
            callback(normalizeUpdateState(payload, canNativeInstall))
          })
        })
      },
    },
  }
}
