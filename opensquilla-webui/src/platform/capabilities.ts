import type { PlatformCapabilities, PlatformId } from './types'

export const webCapabilities: PlatformCapabilities = {
  isDesktop: false,
  ownsGateway: false,
  canManageLocalApiKeys: false,
  canRevealGatewayLog: false,
  canRestartGateway: false,
  hasDesktopOnboarding: false,
  hasWebConfig: true,
}

export const desktopCapabilities: PlatformCapabilities = {
  isDesktop: true,
  ownsGateway: true,
  canManageLocalApiKeys: true,
  canRevealGatewayLog: true,
  canRestartGateway: true,
  hasDesktopOnboarding: true,
  hasWebConfig: false,
}

export function detectPlatformId(): PlatformId {
  return typeof window !== 'undefined' && window.opensquillaDesktop ? 'desktop' : 'web'
}
