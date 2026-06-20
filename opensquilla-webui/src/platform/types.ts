export type PlatformId = 'web' | 'desktop'

export interface GatewayStatus {
  url: string
  port: number
  owned: boolean
  status: 'starting' | 'ready' | 'stopped' | 'error'
  logPath: string
  error?: string
}

export interface DesktopSettings {
  provider: string
  model: string
  baseUrl: string
  apiKeyConfigured: boolean
  searchProvider: string
  searchApiKeyEnv: string
  searchApiKeyConfigured: boolean
  searchProviders?: SearchProviderOption[]
  gateway: GatewayStatus
}

export interface SearchProviderOption {
  providerId: string
  label: string
  envKey?: string
  requiresApiKey?: boolean
  note?: string
  keyPlaceholder?: string
}

export interface DesktopSettingsPayload {
  provider?: string
  model?: string
  baseUrl?: string
  apiKey?: string
  searchProvider?: string
  searchApiKey?: string
}

export interface PlatformCapabilities {
  isDesktop: boolean
  ownsGateway: boolean
  canManageLocalApiKeys: boolean
  canRevealGatewayLog: boolean
  canRestartGateway: boolean
  hasDesktopOnboarding: boolean
  hasWebConfig: boolean
}

export interface PlatformGatewayApi {
  getStatus(): Promise<GatewayStatus>
  revealLog?: () => Promise<boolean>
  retryStartup?: () => Promise<unknown>
}

export interface PlatformSettingsApi {
  getDesktopSettings?: () => Promise<DesktopSettings>
  saveDesktopSettings?: (payload: DesktopSettingsPayload) => Promise<DesktopSettings>
  resetDesktopSettings?: () => Promise<{ ok: boolean }>
}

export interface PlatformOnboardingApi {
  getDefaults?: () => Promise<unknown>
  save?: (payload: unknown) => Promise<unknown>
  cancel?: () => Promise<unknown>
}

export interface Platform {
  id: PlatformId
  capabilities: PlatformCapabilities
  gateway: PlatformGatewayApi
  settings: PlatformSettingsApi
  onboarding: PlatformOnboardingApi
}
