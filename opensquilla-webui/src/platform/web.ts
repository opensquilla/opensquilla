import { webCapabilities } from './capabilities'
import type { GatewayStatus, Platform } from './types'

const unavailableGateway: GatewayStatus = {
  url: '',
  port: 0,
  owned: false,
  status: 'stopped',
  logPath: '',
}

export function createWebPlatform(): Platform {
  return {
    id: 'web',
    capabilities: webCapabilities,
    async getOsLocale() {
      return undefined
    },
    gateway: {
      async getStatus() {
        return { ...unavailableGateway }
      },
    },
    settings: {},
    onboarding: {},
    files: {},
  }
}
