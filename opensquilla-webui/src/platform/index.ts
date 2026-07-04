import { detectPlatformId } from './capabilities'
import { createDesktopPlatform } from './desktop'
import type { Platform } from './types'
import { createWebPlatform } from './web'

let cachedPlatform: Platform | null = null

export function getPlatform(): Platform {
  if (cachedPlatform) return cachedPlatform
  cachedPlatform = detectPlatformId() === 'desktop'
    ? createDesktopPlatform()
    : createWebPlatform()
  return cachedPlatform
}

export function usePlatform(): Platform {
  return getPlatform()
}

export type {
  ArtifactNativeOpenResult,
  ArtifactOpenRequest,
  DesktopSettings,
  DesktopSettingsPayload,
  DesktopUpdateState,
  DesktopUpdateStatus,
  GatewayStatus,
  Platform,
  PlatformCapabilities,
  PlatformFilesApi,
  PlatformGatewayApi,
  PlatformId,
  PlatformOnboardingApi,
  PlatformUpdatesApi,
  PlatformSettingsApi,
  SearchProviderOption,
} from './types'
