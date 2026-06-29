/// <reference types="vite/client" />

import type {
  ArtifactNativeOpenResult,
  ArtifactOpenRequest,
  DesktopSettings,
  DesktopSettingsPayload,
} from './platform/types'

declare global {
  interface OpenSquillaDesktopApi {
    getOsLocale: () => Promise<string | undefined>
    getGatewayStatus: () => Promise<DesktopSettings['gateway']>
    revealGatewayLog: () => Promise<boolean>
    getDesktopSettings: () => Promise<DesktopSettings>
    saveDesktopSettings: (payload: DesktopSettingsPayload) => Promise<DesktopSettings>
    resetDesktopSettings: () => Promise<{ ok: boolean }>
    openArtifact: (payload: ArtifactOpenRequest) => Promise<ArtifactNativeOpenResult>
    getOnboardingDefaults: () => Promise<unknown>
    saveOnboarding: (payload: unknown) => Promise<unknown>
    cancelOnboarding: () => Promise<unknown>
    getBootState: () => Promise<unknown>
    retryStartup: () => Promise<unknown>
    quitApp: () => Promise<unknown>
    onBootStatus: (callback: (payload: unknown) => void) => () => void
    onBootError: (callback: (payload: unknown) => void) => () => void
  }

  interface Window {
    opensquillaDesktop?: OpenSquillaDesktopApi
  }
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

export {}
