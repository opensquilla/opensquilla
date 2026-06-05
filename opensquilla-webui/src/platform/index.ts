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
  DesktopSettings,
  DesktopSettingsPayload,
  GatewayStatus,
  Platform,
  PlatformCapabilities,
  PlatformGatewayApi,
  PlatformId,
  PlatformOnboardingApi,
  PlatformSettingsApi,
} from './types'
