import { desktopCapabilities } from './capabilities'
import type { Platform } from './types'

function requireDesktopApi(): OpenSquillaDesktopApi {
  const api = window.opensquillaDesktop
  if (!api) throw new Error('OpenSquilla desktop API is unavailable.')
  return api
}

export function createDesktopPlatform(): Platform {
  return {
    id: 'desktop',
    capabilities: desktopCapabilities,
    getOsLocale: () => requireDesktopApi().getOsLocale(),
    async nativeAutoUpdateEnabled() {
      const api = requireDesktopApi()
      // Older shells without this bridge are macOS-only with native update on;
      // default to true there so the web banner never double-notifies.
      if (typeof api.isAutoUpdateEnabled !== 'function') return true
      try {
        return await api.isAutoUpdateEnabled()
      } catch {
        return true
      }
    },
    gateway: {
      getStatus: () => requireDesktopApi().getGatewayStatus(),
      revealLog: () => requireDesktopApi().revealGatewayLog(),
      retryStartup: () => requireDesktopApi().retryStartup(),
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
  }
}
