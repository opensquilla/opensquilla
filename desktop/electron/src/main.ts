import { app, BrowserWindow, dialog, Menu, ipcMain, nativeTheme, safeStorage, shell } from 'electron'
import electronUpdater from 'electron-updater'
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { createWriteStream, existsSync, mkdirSync } from 'node:fs'
import { access, constants, readFile, readdir, rm, stat, unlink, writeFile } from 'node:fs/promises'
import net from 'node:net'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { secretStorageBackendForPolicy, shouldUseChromiumMockKeychainForPolicy } from './secret-storage-policy.js'

interface GatewayState {
  url: string
  port: number
  owned: boolean
  status: 'starting' | 'ready' | 'stopped' | 'error'
  logPath: string
  error?: string
}

type SecretEncryption = 'safeStorage' | 'plain'
type RouterMode = 'recommended' | 'openrouter-mix' | 'disabled'
type TextRouterTier = 't0' | 't1' | 't2' | 't3'

interface ProviderCatalogEntry {
  id: string
  label: string
  model: string
  baseUrl: string
  apiKeyEnv: string
  requiresApiKey: boolean
  routerSupported: boolean
  deployment: 'cloud' | 'local'
  note: string
}

interface SearchProviderCatalogEntry {
  providerId: string
  label: string
  envKey: string
  requiresApiKey: boolean
  note: string
  keyPlaceholder: string
}

interface RouterTier {
  provider: string
  model: string
  description?: string
  supportsImage?: boolean
  imageOnly?: boolean
  thinkingLevel?: string
}

interface DesktopConnection {
  provider: string
  model: string
  baseUrl: string
  apiKeyEnv: string
  encryptedApiKey?: string
  routerMode: RouterMode
  routerDefaultTier: TextRouterTier
  routerTiers: Record<string, RouterTier>
  searchProvider: string
  searchApiKeyEnv: string
  encryptedSearchApiKey?: string
  encryption: SecretEncryption
  createdAt: string
  updatedAt: string
}

interface OnboardingPayload {
  provider?: unknown
  model?: unknown
  baseUrl?: unknown
  apiKey?: unknown
  routerMode?: unknown
  routerDefaultTier?: unknown
  routerTiers?: unknown
  searchProvider?: unknown
  searchApiKey?: unknown
}

interface DesktopSettingsPayload extends OnboardingPayload {}

interface DesktopSettingsSnapshot {
  provider: string
  model: string
  baseUrl: string
  apiKeyConfigured: boolean
  routerMode: RouterMode
  routerDefaultTier: TextRouterTier
  routerTiers: Record<string, RouterTier>
  searchProvider: string
  searchApiKeyEnv: string
  searchApiKeyConfigured: boolean
  searchProviders: SearchProviderCatalogEntry[]
  providers?: { providerId: string; label: string; model: string; baseUrl: string }[]
  gateway: GatewayState
}

interface RuntimeLaunch {
  command: string
  args: string[]
  cwd: string
  mode: 'bundled' | 'dev'
}

type BootPhaseId = 'profile' | 'gateway-start' | 'gateway-health' | 'control' | 'ready'

interface BootStatus {
  phaseId: BootPhaseId
  label: string
  at: string
}

interface BootError {
  message: string
  at: string
}

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(__dirname, '..')
const defaultRepoRoot = resolve(packageRoot, '..', '..')
const repoRoot = process.env.OPENSQUILLA_DESKTOP_REPO_ROOT
  ? resolve(process.env.OPENSQUILLA_DESKTOP_REPO_ROOT)
  : defaultRepoRoot

let mainWindow: BrowserWindow | null = null
let onboardingWindow: BrowserWindow | null = null
let gatewayProcess: ChildProcessWithoutNullStreams | null = null
let isQuitting = false
let gatewayStartPromise: Promise<GatewayState> | null = null
let resolveOnboarding: ((credential: DesktopConnection) => void) | null = null
let rejectOnboarding: ((error: Error) => void) | null = null
let secretStorageBackendCache: SecretEncryption | null = null
let macCodeSignatureDiagnosticCache: string | null = null
let bootStatus: BootStatus = {
  phaseId: 'profile',
  label: 'Preparing desktop profile',
  at: new Date().toISOString(),
}
let bootError: BootError | null = null

const gatewayState: GatewayState = {
  url: '',
  port: 0,
  owned: false,
  status: 'stopped',
  logPath: '',
}

function desktopHome(): string {
  return join(app.getPath('userData'), 'opensquilla')
}

function desktopConfigPath(): string {
  return join(desktopHome(), 'config.toml')
}

function desktopStateDir(): string {
  return join(desktopHome(), 'state')
}

function credentialPath(): string {
  return join(app.getPath('userData'), 'desktop-credential.json')
}

function bootPagePath(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'boot.html')
    : join(packageRoot, 'src', 'boot.html')
}

function appIconPath(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'app.asar', 'assets', 'icon.png')
    : join(packageRoot, 'assets', 'icon.png')
}

function sendBootStatus(phaseId: BootPhaseId): void {
  bootStatus = { phaseId, label: desktopT('boot.' + phaseId), at: new Date().toISOString() }
  bootError = null
  mainWindow?.webContents.send('desktop:boot:status', bootStatus)
}

function sendBootError(error: unknown): void {
  bootError = {
    message: error instanceof Error ? error.message : String(error),
    at: new Date().toISOString(),
  }
  mainWindow?.webContents.send('desktop:boot:error', bootError)
}

const TEXT_ROUTER_TIERS: TextRouterTier[] = ['t0', 't1', 't2', 't3']
const ROUTER_PROFILE_IDS = new Set(['openrouter', 'dashscope', 'deepseek', 'gemini', 'volcengine', 'openai', 'zhipu', 'moonshot'])

const PROVIDER_CATALOG: ProviderCatalogEntry[] = [
  {
    id: 'openrouter',
    label: 'OpenRouter',
    model: 'deepseek/deepseek-v4-pro',
    baseUrl: 'https://openrouter.ai/api/v1',
    apiKeyEnv: 'OPENROUTER_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'Best default for mixed model routing.',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    model: 'gpt-5.4-mini',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyEnv: 'OPENAI_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'OpenAI-only tier profile.',
  },
  {
    id: 'openai_responses',
    label: 'OpenAI (Responses API)',
    model: 'gpt-5.4-mini',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyEnv: 'OPENAI_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'OpenAI Responses-API shape (chat + responses).',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    model: 'claude-sonnet-4-5',
    baseUrl: 'https://api.anthropic.com',
    apiKeyEnv: 'ANTHROPIC_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Direct Claude access without SquillaRouter tiers.',
  },
  {
    id: 'dashscope',
    label: 'Aliyun DashScope',
    model: 'qwen3.6-plus',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    apiKeyEnv: 'DASHSCOPE_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'Qwen tier profile for Mainland-friendly access.',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    model: 'deepseek-v4-flash',
    baseUrl: 'https://api.deepseek.com',
    apiKeyEnv: 'DEEPSEEK_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'DeepSeek-only fast and pro routing.',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    model: 'gemini-2.5-flash',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    apiKeyEnv: 'GEMINI_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'Gemini OpenAI-compatible tier profile.',
  },
  {
    id: 'moonshot',
    label: 'Moonshot AI',
    model: 'kimi-k2.5',
    baseUrl: 'https://api.moonshot.ai/v1',
    apiKeyEnv: 'MOONSHOT_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'Kimi text and image-capable routes.',
  },
  {
    id: 'ollama',
    label: 'Ollama (local)',
    model: '',
    baseUrl: 'http://localhost:11434',
    apiKeyEnv: '',
    requiresApiKey: false,
    routerSupported: false,
    deployment: 'local',
    note: 'Local direct model path.',
  },
  {
    id: 'qianfan',
    label: 'Baidu Qianfan',
    model: '',
    baseUrl: 'https://qianfan.baidubce.com/v2',
    apiKeyEnv: 'QIANFAN_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Direct provider model id required.',
  },
  {
    id: 'volcengine',
    label: 'Volcengine Ark',
    model: 'doubao-seed-2-0-lite-260215',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    apiKeyEnv: 'VOLCENGINE_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'Doubao tier profile.',
  },
  {
    id: 'zhipu',
    label: 'Zhipu (Z.AI)',
    model: 'glm-5',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    apiKeyEnv: 'ZAI_API_KEY',
    requiresApiKey: true,
    routerSupported: true,
    deployment: 'cloud',
    note: 'GLM tier profile.',
  },
]

const PROVIDER_BY_ID = new Map(PROVIDER_CATALOG.map((provider) => [provider.id, provider]))

const SEARCH_PROVIDER_CATALOG: SearchProviderCatalogEntry[] = [
  {
    providerId: 'duckduckgo',
    label: 'DuckDuckGo',
    envKey: '',
    requiresApiKey: false,
    note: 'No key required. Good default for getting started.',
    keyPlaceholder: 'not required',
  },
  {
    providerId: 'bocha',
    label: 'Bocha',
    envKey: 'BOCHA_SEARCH_API_KEY',
    requiresApiKey: true,
    note: 'Web search with inline summaries and freshness support.',
    keyPlaceholder: 'BOCHA_SEARCH_API_KEY',
  },
  {
    providerId: 'brave',
    label: 'Brave Search',
    envKey: 'BRAVE_SEARCH_API_KEY',
    requiresApiKey: true,
    note: 'Managed search access with freshness support.',
    keyPlaceholder: 'BRAVE_SEARCH_API_KEY',
  },
  {
    providerId: 'tavily',
    label: 'Tavily',
    envKey: 'TAVILY_API_KEY',
    requiresApiKey: true,
    note: 'Freshness-oriented web search for current research.',
    keyPlaceholder: 'TAVILY_API_KEY',
  },
  {
    providerId: 'exa',
    label: 'Exa',
    envKey: 'EXA_API_KEY',
    requiresApiKey: true,
    note: 'Semantic and content-oriented search for research workflows.',
    keyPlaceholder: 'EXA_API_KEY',
  },
]

const SEARCH_PROVIDER_BY_ID = new Map(
  SEARCH_PROVIDER_CATALOG.map((provider) => [provider.providerId, provider]),
)

const ROUTER_PROFILES: Record<string, Record<string, RouterTier>> = {
  openrouter: {
    t0: { provider: 'openrouter', model: 'deepseek/deepseek-v4-flash', description: 'Fast everyday work', thinkingLevel: 'high' },
    t1: { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', description: 'Balanced agent work', thinkingLevel: 'high' },
    t2: { provider: 'openrouter', model: 'z-ai/glm-5.2', description: 'Complex reasoning', thinkingLevel: 'high' },
    t3: { provider: 'openrouter', model: 'anthropic/claude-opus-4.8', description: 'Highest quality review and planning', thinkingLevel: 'high' },
    image_model: { provider: 'openrouter', model: 'moonshotai/kimi-k2.6', description: 'Vision route for image attachments', supportsImage: true, imageOnly: true, thinkingLevel: 'medium' },
  },
  openai: {
    t0: { provider: 'openai', model: 'gpt-5.4-nano', description: 'Fast simple work', thinkingLevel: 'none' },
    t1: { provider: 'openai', model: 'gpt-5.4-mini', description: 'Balanced agent work', thinkingLevel: 'low' },
    t2: { provider: 'openai', model: 'gpt-5.5', description: 'Complex text tasks', thinkingLevel: 'medium' },
    t3: { provider: 'openai', model: 'gpt-5.5', description: 'Deep reasoning', thinkingLevel: 'high' },
  },
  dashscope: {
    t0: { provider: 'dashscope', model: 'qwen3.6-flash', description: 'Fast simple work' },
    t1: { provider: 'dashscope', model: 'qwen3.6-plus', description: 'Balanced agent work' },
    t2: { provider: 'dashscope', model: 'qwen3-max', description: 'Complex text tasks' },
    t3: { provider: 'dashscope', model: 'qwen3-max', description: 'Deep reasoning' },
  },
  deepseek: {
    t0: { provider: 'deepseek', model: 'deepseek-v4-flash', description: 'Fast simple work' },
    t1: { provider: 'deepseek', model: 'deepseek-v4-flash', description: 'Balanced agent work' },
    t2: { provider: 'deepseek', model: 'deepseek-v4-pro', description: 'Complex text tasks' },
    t3: { provider: 'deepseek', model: 'deepseek-v4-pro', description: 'Deep reasoning' },
  },
  gemini: {
    t0: { provider: 'gemini', model: 'gemini-2.5-flash-lite', description: 'Fast simple work' },
    t1: { provider: 'gemini', model: 'gemini-2.5-flash', description: 'Balanced agent work' },
    t2: { provider: 'gemini', model: 'gemini-2.5-pro', description: 'Complex text tasks' },
    t3: { provider: 'gemini', model: 'gemini-2.5-pro', description: 'Deep reasoning' },
  },
  moonshot: {
    t0: { provider: 'moonshot', model: 'kimi-k2.5', description: 'Fast simple work' },
    t1: { provider: 'moonshot', model: 'kimi-k2.5', description: 'Balanced agent work' },
    t2: { provider: 'moonshot', model: 'kimi-k2.6', description: 'Complex text and image work', supportsImage: true },
    t3: { provider: 'moonshot', model: 'kimi-k2.6', description: 'Deep reasoning and image work', supportsImage: true },
  },
  volcengine: {
    t0: { provider: 'volcengine', model: 'doubao-seed-2-0-mini-260215', description: 'Fast simple work' },
    t1: { provider: 'volcengine', model: 'doubao-seed-2-0-lite-260215', description: 'Balanced agent work' },
    t2: { provider: 'volcengine', model: 'doubao-seed-2-0-pro-260215', description: 'Complex text tasks' },
    t3: { provider: 'volcengine', model: 'doubao-seed-2-0-code-preview-260215', description: 'Code-heavy deep reasoning' },
  },
  zhipu: {
    t0: { provider: 'zhipu', model: 'glm-4.7-flashx', description: 'Fast simple work' },
    t1: { provider: 'zhipu', model: 'glm-5', description: 'Balanced agent work' },
    t2: { provider: 'zhipu', model: 'glm-5.1', description: 'Complex text tasks' },
    t3: { provider: 'zhipu', model: 'glm-5.1', description: 'Deep reasoning' },
  },
}

function cloneRouterTiers(tiers: Record<string, RouterTier>): Record<string, RouterTier> {
  return Object.fromEntries(Object.entries(tiers).map(([name, tier]) => [name, { ...tier }]))
}

function providerDefaults(provider: string): { model: string; baseUrl: string; apiKeyEnv: string; requiresApiKey: boolean; routerSupported: boolean } {
  const defaults = PROVIDER_BY_ID.get(provider) || PROVIDER_BY_ID.get('openrouter')!
  return {
    model: defaults.model,
    baseUrl: defaults.baseUrl,
    apiKeyEnv: defaults.apiKeyEnv,
    requiresApiKey: defaults.requiresApiKey,
    routerSupported: defaults.routerSupported,
  }
}

function normalizeProvider(raw: unknown): string {
  // Preserve any configured provider id; the desktop UI and gateway both accept
  // ids beyond the local catalog, and collapsing them to openrouter silently
  // loses the user's choice on load/save.
  return String(raw || '').trim().toLowerCase() || 'openrouter'
}

function normalizeTextTier(raw: unknown): TextRouterTier {
  const value = String(raw || '').trim().toLowerCase()
  return TEXT_ROUTER_TIERS.includes(value as TextRouterTier) ? value as TextRouterTier : 't1'
}

function normalizeRouterMode(raw: unknown, provider: string): RouterMode {
  const value = String(raw || '').trim().toLowerCase()
  if (value === 'disabled') return 'disabled'
  if (value === 'openrouter-mix' && provider === 'openrouter') return 'openrouter-mix'
  if (ROUTER_PROFILE_IDS.has(provider)) return 'recommended'
  return 'disabled'
}

function defaultRouterTiers(provider: string, mode: RouterMode): Record<string, RouterTier> {
  if (mode === 'disabled') return {}
  if (mode === 'openrouter-mix') return cloneRouterTiers(ROUTER_PROFILES.openrouter)
  return cloneRouterTiers(ROUTER_PROFILES[provider] || ROUTER_PROFILES.openrouter)
}

function normalizeRouterTiers(raw: unknown, fallback: Record<string, RouterTier>): Record<string, RouterTier> {
  if (!raw || typeof raw !== 'object') return cloneRouterTiers(fallback)
  const source = raw as Record<string, unknown>
  const out = cloneRouterTiers(fallback)
  for (const [name, value] of Object.entries(source)) {
    if (!value || typeof value !== 'object') continue
    const tier = value as Record<string, unknown>
    const provider = String(tier.provider || out[name]?.provider || '').trim()
    const model = String(tier.model || out[name]?.model || '').trim()
    if (!provider || !model) continue
    out[name] = {
      ...out[name],
      provider,
      model,
      description: String(tier.description || out[name]?.description || ''),
      supportsImage: Boolean(tier.supportsImage ?? tier.supports_image ?? out[name]?.supportsImage),
      imageOnly: Boolean(tier.imageOnly ?? tier.image_only ?? out[name]?.imageOnly),
      thinkingLevel: String(tier.thinkingLevel ?? tier.thinking_level ?? out[name]?.thinkingLevel ?? ''),
    }
  }
  return out
}

function routerDefaultModel(tiers: Record<string, RouterTier>, defaultTier: TextRouterTier): string {
  return tiers[defaultTier]?.model || tiers.t1?.model || tiers.t0?.model || ''
}

function searchProviderDefaults(provider: string): SearchProviderCatalogEntry {
  return SEARCH_PROVIDER_BY_ID.get(provider) || SEARCH_PROVIDER_BY_ID.get('duckduckgo')!
}

function normalizeSearchProvider(raw: unknown): string {
  const provider = String(raw || '').trim().toLowerCase()
  return SEARCH_PROVIDER_BY_ID.has(provider) ? provider : 'duckduckgo'
}

function tomlString(value: string): string {
  return JSON.stringify(value)
}

function routerTierTomlLines(name: string, tier: RouterTier): string[] {
  const lines = [
    `[squilla_router.tiers.${name}]`,
    `provider = ${tomlString(tier.provider)}`,
    `model = ${tomlString(tier.model)}`,
  ]
  if (tier.description) lines.push(`description = ${tomlString(tier.description)}`)
  if (tier.supportsImage !== undefined) lines.push(`supports_image = ${tier.supportsImage ? 'true' : 'false'}`)
  if (tier.imageOnly !== undefined) lines.push(`image_only = ${tier.imageOnly ? 'true' : 'false'}`)
  if (tier.thinkingLevel) lines.push(`thinking_level = ${tomlString(tier.thinkingLevel)}`)
  return lines
}

function routerConfigTomlLines(credential: DesktopConnection): string[] {
  if (credential.routerMode === 'disabled') {
    return [
      '[squilla_router]',
      'enabled = false',
    ]
  }
  const tierLines = Object.entries(credential.routerTiers)
    .filter(([, tier]) => tier.provider && tier.model)
    .flatMap(([name, tier]) => ['', ...routerTierTomlLines(name, tier)])
  return [
    '[squilla_router]',
    'enabled = true',
    'rollout_phase = "full"',
    `default_tier = ${tomlString(credential.routerDefaultTier)}`,
    ...(credential.routerMode === 'recommended' ? [`tier_profile = ${tomlString(credential.provider)}`] : []),
    ...tierLines,
  ]
}

function plainSecret(secret: string): { value: string; encryption: SecretEncryption } {
  return {
    value: Buffer.from(secret, 'utf8').toString('base64'),
    encryption: 'plain',
  }
}

function macCodeSignatureDiagnostic(): string {
  if (macCodeSignatureDiagnosticCache !== null) return macCodeSignatureDiagnosticCache
  if (process.platform !== 'darwin' || !app.isPackaged) return ''
  const result = spawnSync('/usr/bin/codesign', ['-dv', '--verbose=4', process.execPath], { encoding: 'utf8' })
  macCodeSignatureDiagnosticCache = `${result.stdout || ''}\n${result.stderr || ''}`
  return macCodeSignatureDiagnosticCache
}

function configureChromiumKeychainPolicy(): void {
  if (shouldUseChromiumMockKeychainForPolicy({
    envMode: process.env.OPENSQUILLA_DESKTOP_SECRET_STORAGE,
    platform: process.platform,
    appPackaged: app.isPackaged,
    codesignDiagnostic: macCodeSignatureDiagnostic(),
  })) {
    app.commandLine.appendSwitch('use-mock-keychain')
  }
}

function desktopSecretStorageBackend(): SecretEncryption {
  if (secretStorageBackendCache) return secretStorageBackendCache
  const selected = secretStorageBackendForPolicy({
    envMode: process.env.OPENSQUILLA_DESKTOP_SECRET_STORAGE,
    platform: process.platform,
    appPackaged: app.isPackaged,
    codesignDiagnostic: macCodeSignatureDiagnostic(),
  })
  secretStorageBackendCache = selected === 'safeStorage' && safeStorage.isEncryptionAvailable() ? 'safeStorage' : 'plain'
  return secretStorageBackendCache
}

function encryptSecret(secret: string): { value: string; encryption: SecretEncryption } {
  if (desktopSecretStorageBackend() === 'safeStorage') {
    try {
      return {
        value: safeStorage.encryptString(secret).toString('base64'),
        encryption: 'safeStorage',
      }
    } catch {
      return plainSecret(secret)
    }
  }
  return plainSecret(secret)
}

function decryptSecret(encryptedValue: string | undefined, encryption: SecretEncryption): string {
  if (!encryptedValue) return ''
  const payload = Buffer.from(encryptedValue, 'base64')
  if (encryption === 'safeStorage') {
    if (desktopSecretStorageBackend() !== 'safeStorage') {
      throw new Error('Saved desktop credential requires macOS Keychain, but this local build uses plain credential storage.')
    }
    return safeStorage.decryptString(payload)
  }
  return payload.toString('utf8')
}

function decryptApiKey(record: DesktopConnection): string {
  if (!record.encryptedApiKey) return ''
  return decryptSecret(record.encryptedApiKey, record.encryption)
}

function decryptSearchApiKey(record: DesktopConnection): string {
  if (!record.encryptedSearchApiKey) return ''
  return decryptSecret(record.encryptedSearchApiKey, record.encryption)
}

function isConnectionReady(record: DesktopConnection): boolean {
  try {
    return !providerDefaults(record.provider).requiresApiKey || Boolean(decryptApiKey(record))
  } catch {
    return false
  }
}

async function loadDesktopCredential(): Promise<DesktopConnection | null> {
  try {
    const raw = await readFile(credentialPath(), 'utf8')
    const parsed = JSON.parse(raw) as Partial<DesktopConnection>
    const provider = normalizeProvider(parsed.provider)
    const defaults = providerDefaults(provider)
    const routerMode = normalizeRouterMode(parsed.routerMode, provider)
    const routerDefaultTier = normalizeTextTier(parsed.routerDefaultTier)
    const defaultTiers = defaultRouterTiers(provider, routerMode)
    const routerTiers = normalizeRouterTiers(parsed.routerTiers, defaultTiers)
    const searchProvider = normalizeSearchProvider(parsed.searchProvider)
    const searchDefaults = searchProviderDefaults(searchProvider)
    return {
      provider,
      model: parsed.model || routerDefaultModel(routerTiers, routerDefaultTier) || defaults.model,
      baseUrl: parsed.baseUrl || defaults.baseUrl,
      apiKeyEnv: parsed.apiKeyEnv || defaults.apiKeyEnv,
      encryptedApiKey: parsed.encryptedApiKey || '',
      routerMode,
      routerDefaultTier,
      routerTiers,
      searchProvider,
      searchApiKeyEnv: parsed.searchApiKeyEnv || searchDefaults.envKey,
      encryptedSearchApiKey: parsed.encryptedSearchApiKey || '',
      encryption: parsed.encryption === 'safeStorage' ? 'safeStorage' : 'plain',
      createdAt: parsed.createdAt || new Date().toISOString(),
      updatedAt: parsed.updatedAt || new Date().toISOString(),
    }
  } catch {
    return null
  }
}

async function saveDesktopCredential(payload: OnboardingPayload): Promise<DesktopConnection> {
  const existing = await loadDesktopCredential()
  const provider = normalizeProvider(payload.provider ?? existing?.provider)
  const defaults = providerDefaults(provider)
  const routerMode = normalizeRouterMode(payload.routerMode ?? existing?.routerMode, provider)
  const routerDefaultTier = normalizeTextTier(payload.routerDefaultTier ?? existing?.routerDefaultTier)
  const defaultTiers = defaultRouterTiers(provider, routerMode)
  const existingTiers = existing && existing.provider === provider && existing.routerMode === routerMode
    ? existing.routerTiers
    : defaultTiers
  const routerTiers = normalizeRouterTiers(payload.routerTiers ?? existingTiers, defaultTiers)
  const searchProvider = normalizeSearchProvider(payload.searchProvider ?? existing?.searchProvider)
  const searchDefaults = searchProviderDefaults(searchProvider)
  const apiKey = String(payload.apiKey || '').trim()
  const routerModel = routerDefaultModel(routerTiers, routerDefaultTier)
  const directModel = String(payload.model || existing?.model || defaults.model).trim()
  const model = routerMode === 'disabled'
    ? directModel
    : routerModel || directModel
  const baseUrl = String(payload.baseUrl || existing?.baseUrl || defaults.baseUrl).trim() || defaults.baseUrl
  const searchApiKey = String(payload.searchApiKey || '').trim()
  const resolvedApiKey = apiKey || (existing && provider === existing.provider ? decryptApiKey(existing) : '')
  const resolvedSearchApiKey = searchDefaults.requiresApiKey
    ? searchApiKey || (existing && searchProvider === existing.searchProvider ? decryptSearchApiKey(existing) : '')
    : ''
  const apiKeySecret = resolvedApiKey ? encryptSecret(resolvedApiKey) : null
  const searchApiKeySecret = resolvedSearchApiKey ? encryptSecret(resolvedSearchApiKey) : null
  const encryptedApiKey = apiKeySecret?.value || ''
  const encryptedSearchApiKey = searchApiKeySecret?.value || ''
  const encryption = apiKeySecret?.encryption || searchApiKeySecret?.encryption || 'plain'

  if (defaults.requiresApiKey && !encryptedApiKey) throw new Error('API key is required.')
  if (!routerModel && routerMode !== 'disabled') throw new Error('Router tiers require a default model.')
  if (!model) throw new Error('Model is required.')
  if (searchDefaults.requiresApiKey && !encryptedSearchApiKey) {
    throw new Error(`${searchDefaults.label} search API key is required.`)
  }

  const now = new Date().toISOString()
  const credential: DesktopConnection = {
    provider,
    model,
    baseUrl,
    apiKeyEnv: defaults.apiKeyEnv,
    encryptedApiKey,
    routerMode,
    routerDefaultTier,
    routerTiers,
    searchProvider,
    searchApiKeyEnv: searchDefaults.envKey,
    encryptedSearchApiKey,
    encryption,
    createdAt: existing?.createdAt || now,
    updatedAt: now,
  }

  mkdirSync(app.getPath('userData'), { recursive: true })
  await writeFile(credentialPath(), JSON.stringify(credential, null, 2), { mode: 0o600 })
  await writeDesktopConfig(credential)
  return credential
}

async function writeDesktopConfig(credential: DesktopConnection): Promise<void> {
  mkdirSync(desktopHome(), { recursive: true })
  mkdirSync(desktopStateDir(), { recursive: true })
  const config = [
    `state_dir = ${tomlString(desktopStateDir())}`,
    `search_provider = ${tomlString(credential.searchProvider)}`,
    ...(credential.searchApiKeyEnv ? [`search_api_key_env = ${tomlString(credential.searchApiKeyEnv)}`] : []),
    // search_max_results is intentionally omitted so the gateway's own default
    // governs instead of pinning it to a hardcoded value. Note this writer
    // regenerates the whole config file, so it still does not preserve a value
    // set through the control UI — that broader limitation of the desktop config
    // writer is tracked separately.
    '',
    '[llm]',
    `provider = ${tomlString(credential.provider)}`,
    `model = ${tomlString(credential.model)}`,
    ...(credential.apiKeyEnv ? [`api_key_env = ${tomlString(credential.apiKeyEnv)}`] : []),
    `base_url = ${tomlString(credential.baseUrl)}`,
    '',
    ...routerConfigTomlLines(credential),
    '',
    '[control_ui]',
    'enabled = true',
    'base_path = "/control"',
    '',
  ].join('\n')
  await writeFile(desktopConfigPath(), config, { mode: 0o600 })
}

function settingsSnapshot(connection: DesktopConnection | null): DesktopSettingsSnapshot {
  const provider = normalizeProvider(connection?.provider)
  const defaults = providerDefaults(provider)
  const routerMode = normalizeRouterMode(connection?.routerMode, provider)
  const routerDefaultTier = normalizeTextTier(connection?.routerDefaultTier)
  const routerTiers = normalizeRouterTiers(connection?.routerTiers, defaultRouterTiers(provider, routerMode))
  const searchProvider = normalizeSearchProvider(connection?.searchProvider)
  const searchDefaults = searchProviderDefaults(searchProvider)
  return {
    provider,
    model: connection?.model || routerDefaultModel(routerTiers, routerDefaultTier) || defaults.model,
    baseUrl: connection?.baseUrl || defaults.baseUrl,
    apiKeyConfigured: Boolean(connection?.encryptedApiKey),
    routerMode,
    routerDefaultTier,
    routerTiers,
    searchProvider,
    searchApiKeyEnv: connection?.searchApiKeyEnv || searchDefaults.envKey,
    searchApiKeyConfigured: Boolean(connection?.encryptedSearchApiKey),
    searchProviders: SEARCH_PROVIDER_CATALOG,
    providers: PROVIDER_CATALOG.map((entry) => ({
      providerId: entry.id,
      label: entry.label,
      model: entry.model,
      baseUrl: entry.baseUrl,
    })),
    gateway: { ...gatewayState },
  }
}

async function loadDesktopSettings(): Promise<DesktopSettingsSnapshot> {
  return settingsSnapshot(await loadDesktopCredential())
}

async function saveDesktopSettings(payload: DesktopSettingsPayload): Promise<DesktopSettingsSnapshot> {
  const connection = await saveDesktopCredential(payload)
  return settingsSnapshot(connection)
}

async function resetDesktopSettings(): Promise<void> {
  // Drop the credential AND the generated config so the next launch re-runs
  // onboarding and reseeds a clean config (the config is now the RPC-owned
  // source of truth, so it is no longer regenerated on every boot).
  await rm(credentialPath(), { force: true })
  await rm(desktopConfigPath(), { force: true })
}

interface ArtifactOpenRequest {
  data?: ArrayBuffer | Uint8Array
  name?: unknown
  mime?: unknown
}

const MIME_EXTENSIONS: Record<string, string> = {
  'application/pdf': '.pdf',
  'text/html': '.html',
  'application/xhtml+xml': '.xhtml',
  'text/plain': '.txt',
  'text/markdown': '.md',
  'text/csv': '.csv',
  'application/json': '.json',
  'application/xml': '.xml',
  'text/xml': '.xml',
  'application/zip': '.zip',
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/gif': '.gif',
  'image/webp': '.webp',
  'image/svg+xml': '.svg',
}

// basename() already drops directory components; here we only neutralize path
// separators and OS-reserved characters, preserving unicode letters, dots,
// dashes and spaces so the extension (and a readable name) survive. The unique
// prefix added at write time means a leading-dot or reserved name cannot escape
// the temp directory or shadow a dotfile.
function safeArtifactFileName(raw: unknown): string {
  const base = basename(String(raw ?? '')).trim()
  const cleaned = base.replace(/[/\\:*?"<>|\x00-\x1f]+/g, '_')
  return cleaned || 'artifact'
}

function artifactMimeKey(mime: unknown): string {
  return String(mime ?? '').split(';', 1)[0].trim().toLowerCase()
}

// When the name carries no extension, fall back to one implied by the MIME type
// so shell.openPath can still associate a default application.
function artifactExtension(name: string, mime: unknown): string {
  if (/\.[A-Za-z0-9]{1,8}$/.test(name)) return ''
  return MIME_EXTENSIONS[artifactMimeKey(mime)] || ''
}

// Best-effort prune so opened artifacts do not accumulate unboundedly in temp.
async function pruneArtifactCache(dir: string): Promise<void> {
  try {
    const now = Date.now()
    const entries = await readdir(dir)
    await Promise.all(entries.map(async (entry) => {
      const full = join(dir, entry)
      try {
        const info = await stat(full)
        if (now - info.mtimeMs > 60 * 60 * 1000) await unlink(full)
      } catch {}
    }))
  } catch {}
}

async function openArtifactWithDefaultApp(payload: ArtifactOpenRequest): Promise<{ ok: boolean; message?: string }> {
  const raw = payload?.data
  if (!raw) return { ok: false, message: 'No artifact data to open.' }
  try {
    const bytes = raw instanceof Uint8Array ? raw : new Uint8Array(raw)
    const dir = join(app.getPath('temp'), 'opensquilla-artifacts')
    mkdirSync(dir, { recursive: true, mode: 0o700 })
    void pruneArtifactCache(dir)
    const name = safeArtifactFileName(payload?.name)
    // A random prefix guarantees a unique, non-colliding, non-dotfile path even
    // for two opens in the same millisecond.
    const filePath = join(dir, `${randomUUID()}-${name}${artifactExtension(name, payload?.mime)}`)
    await writeFile(filePath, Buffer.from(bytes), { mode: 0o600 })
    const error = await shell.openPath(filePath)
    if (error) return { ok: false, message: error }
    return { ok: true }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  }
}

// --- Desktop native-shell i18n (English + Simplified Chinese, v1) ---
// The embedded Web UI carries its own vue-i18n layer; this small catalog covers
// the main-process surfaces that live OUTSIDE the BrowserWindow (app-authored
// menu group labels and the onboarding window title), keyed off the OS locale.
// Role-based menu items (Cut/Copy/Paste/…) are localized by Electron itself.
type DesktopLocale = 'en' | 'zh-Hans' | 'ja' | 'fr' | 'de' | 'es'
let desktopLocale: DesktopLocale = 'en'

function resolveDesktopLocale(): DesktopLocale {
  const preferred = typeof app.getPreferredSystemLanguages === 'function'
    ? app.getPreferredSystemLanguages()
    : []
  for (const raw of [...preferred, app.getLocale()]) {
    if (typeof raw !== 'string') continue
    const t = raw.toLowerCase()
    if (t.startsWith('zh')) return 'zh-Hans'
    for (const code of ['ja', 'fr', 'de', 'es'] as const) {
      if (t === code || t.startsWith(code + '-')) return code
    }
  }
  return 'en'
}

const DESKTOP_MESSAGES: Record<DesktopLocale, Record<string, string>> = {
  en: {
    'menu.edit': 'Edit',
    'menu.view': 'View',
    'menu.window': 'Window',
    'menu.checkForUpdates': 'Check for Updates…',
    'update.newVersionTitle': 'A new version is available',
    'update.newVersionDetail': 'OpenSquilla {version} is available. Download it now?',
    'update.download': 'Download',
    'update.later': 'Later',
    'update.readyTitle': 'Update ready to install',
    'update.readyDetail': 'OpenSquilla {version} has been downloaded. Restart to finish updating?',
    'update.restartNow': 'Restart now',
    'update.upToDateTitle': "You're up to date",
    'update.upToDateDetail': 'OpenSquilla {version} is the latest version.',
    'update.errorTitle': 'Update check failed',
    'update.moveToApplications': 'Move OpenSquilla to your Applications folder to enable automatic updates, then try again.',
    'window.onboarding': 'Set up OpenSquilla',
    'boot.profile': 'Preparing desktop profile',
    'boot.gateway-start': 'Starting local runtime',
    'boot.gateway-health': 'Checking gateway health',
    'boot.control': 'Loading Control UI',
    'boot.ready': 'Ready',
    'onboarding.title': 'Set up OpenSquilla',
    'onboarding.rail.title': 'Desktop setup',
    'onboarding.rail.subtitle': 'Configure the local runtime in the same order as the guided CLI.',
    'onboarding.rail.foot': 'OpenSquilla keeps this profile local to this device.',
    'onboarding.aria.setupSteps': 'Setup steps',
    'onboarding.aria.setupDepth': 'Setup depth',
    'onboarding.aria.routerMode': 'Router mode',
    'onboarding.aria.searchProvider': 'Search provider',
    'onboarding.nav.mode.title': 'Mode',
    'onboarding.nav.mode.sub': 'Setup depth',
    'onboarding.nav.provider.title': 'Provider',
    'onboarding.nav.provider.sub': 'Model access',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': 'Routing mode',
    'onboarding.nav.tiers.title': 'Tiers',
    'onboarding.nav.tiers.sub': 'Default models',
    'onboarding.nav.search.title': 'Search',
    'onboarding.nav.search.sub': 'Optional web access',
    'onboarding.step1.badge': 'Start',
    'onboarding.step1.heading': 'Choose setup depth',
    'onboarding.step1.subtitle': 'Start with the shortest working path, or open the full router and tier controls now.',
    'onboarding.step1.simpleTitle': 'Simple setup',
    'onboarding.step1.simpleDesc': 'Pick one provider, add its key, choose search, and start OpenSquilla with defaults.',
    'onboarding.step1.advancedTitle': 'Advanced setup',
    'onboarding.step1.advancedDesc': 'Review Smart Router mode, tier defaults, and direct model details before startup.',
    'onboarding.step1.note': 'You can change provider, router, and search settings later from the desktop Settings page.',
    'onboarding.step1.quit': 'Quit',
    'onboarding.step1.continue': 'Continue',
    'onboarding.step2.badge': 'Required',
    'onboarding.step2.heading': 'Connect a provider',
    'onboarding.step2.subtitle': 'This is the account the local runtime uses for model calls. OpenRouter is the default; more providers stay tucked away until you need them.',
    'onboarding.step2.apiKey': 'API key',
    'onboarding.step2.endpointSummary': 'Endpoint and direct model',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Direct model',
    'onboarding.step2.back': 'Back',
    'onboarding.step2.next': 'Next',
    'onboarding.step3.badge': 'Routing',
    'onboarding.step3.heading': 'Select Smart Router mode',
    'onboarding.step3.subtitle': 'Choose whether OpenSquilla should route work across tier defaults or call one model directly.',
    'onboarding.step3.back': 'Back',
    'onboarding.step3.next': 'Next',
    'onboarding.step4.badge': 'Models',
    'onboarding.step4.heading': 'Review tier models',
    'onboarding.step4.subtitle': 'Pick the default text tier and keep the CLI defaults, or customize the model ids before startup.',
    'onboarding.step4.back': 'Back',
    'onboarding.step4.next': 'Next',
    'onboarding.step5.badge': 'Optional',
    'onboarding.step5.heading': 'Choose web search',
    'onboarding.step5.subtitle': 'Search is optional. Start without another key, or connect a runtime-supported search provider.',
    'onboarding.step5.searchKey': 'Search API key',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo is enough to start.',
    'onboarding.step5.back': 'Back',
    'onboarding.step5.finish': 'Start OpenSquilla',
    'onboarding.more.show': 'More providers',
    'onboarding.more.hide': 'Hide providers',
  },
  'zh-Hans': {
    'menu.edit': '编辑',
    'menu.view': '视图',
    'menu.window': '窗口',
    'menu.checkForUpdates': '检查更新…',
    'update.newVersionTitle': '有新版本可用',
    'update.newVersionDetail': 'OpenSquilla {version} 已发布，现在下载吗？',
    'update.download': '下载',
    'update.later': '稍后',
    'update.readyTitle': '更新已就绪',
    'update.readyDetail': 'OpenSquilla {version} 已下载完成。是否重启以完成更新？',
    'update.restartNow': '立即重启',
    'update.upToDateTitle': '已是最新版本',
    'update.upToDateDetail': 'OpenSquilla {version} 已是最新版本。',
    'update.errorTitle': '检查更新失败',
    'update.moveToApplications': '请先将 OpenSquilla 移动到"应用程序"文件夹以启用自动更新，然后重试。',
    'window.onboarding': '设置 OpenSquilla',
    'boot.profile': '正在准备桌面配置',
    'boot.gateway-start': '正在启动本地运行时',
    'boot.gateway-health': '正在检查网关健康状态',
    'boot.control': '正在加载控制界面',
    'boot.ready': '就绪',
    'onboarding.title': '设置 OpenSquilla',
    'onboarding.rail.title': '桌面设置',
    'onboarding.rail.subtitle': '按照引导式 CLI 的相同顺序配置本地运行时。',
    'onboarding.rail.foot': 'OpenSquilla 将此配置保留在本设备本地。',
    'onboarding.aria.setupSteps': '设置步骤',
    'onboarding.aria.setupDepth': '设置深度',
    'onboarding.aria.routerMode': '路由模式',
    'onboarding.aria.searchProvider': '搜索提供商',
    'onboarding.nav.mode.title': '模式',
    'onboarding.nav.mode.sub': '设置深度',
    'onboarding.nav.provider.title': '提供商',
    'onboarding.nav.provider.sub': '模型访问',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': '路由模式',
    'onboarding.nav.tiers.title': '层级',
    'onboarding.nav.tiers.sub': '默认模型',
    'onboarding.nav.search.title': '搜索',
    'onboarding.nav.search.sub': '可选的网络访问',
    'onboarding.step1.badge': '开始',
    'onboarding.step1.heading': '选择设置深度',
    'onboarding.step1.subtitle': '从最短的可用路径开始，或者现在就打开完整的路由器和层级控件。',
    'onboarding.step1.simpleTitle': '简单设置',
    'onboarding.step1.simpleDesc': '选择一个提供商，添加其密钥，选择搜索，然后使用默认设置启动 OpenSquilla。',
    'onboarding.step1.advancedTitle': '高级设置',
    'onboarding.step1.advancedDesc': '在启动前查看 Smart Router 模式、层级默认值和直连模型详情。',
    'onboarding.step1.note': '稍后可在桌面设置页面更改提供商、路由器和搜索设置。',
    'onboarding.step1.quit': '退出',
    'onboarding.step1.continue': '继续',
    'onboarding.step2.badge': '必填',
    'onboarding.step2.heading': '连接提供商',
    'onboarding.step2.subtitle': '这是本地运行时用于模型调用的账户。默认使用 OpenRouter；其他提供商会收起，需要时再展开。',
    'onboarding.step2.apiKey': 'API 密钥',
    'onboarding.step2.endpointSummary': '端点和直连模型',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': '直连模型',
    'onboarding.step2.back': '返回',
    'onboarding.step2.next': '下一步',
    'onboarding.step3.badge': '路由',
    'onboarding.step3.heading': '选择 Smart Router 模式',
    'onboarding.step3.subtitle': '选择 OpenSquilla 是按层级默认值分配工作，还是直接调用单个模型。',
    'onboarding.step3.back': '返回',
    'onboarding.step3.next': '下一步',
    'onboarding.step4.badge': '模型',
    'onboarding.step4.heading': '查看层级模型',
    'onboarding.step4.subtitle': '选择默认文本层级并保留 CLI 默认值，或在启动前自定义模型 id。',
    'onboarding.step4.back': '返回',
    'onboarding.step4.next': '下一步',
    'onboarding.step5.badge': '可选',
    'onboarding.step5.heading': '选择网络搜索',
    'onboarding.step5.subtitle': '搜索为可选项。可以不添加其他密钥直接开始，或连接运行时支持的搜索提供商。',
    'onboarding.step5.searchKey': '搜索 API 密钥',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo 足以开始使用。',
    'onboarding.step5.back': '返回',
    'onboarding.step5.finish': '启动 OpenSquilla',
    'onboarding.more.show': '更多提供商',
    'onboarding.more.hide': '收起提供商',
  },
  ja: {
    'menu.edit': '編集',
    'menu.view': '表示',
    'menu.window': 'ウインドウ',
    'menu.checkForUpdates': 'アップデートを確認…',
    'update.newVersionTitle': '新しいバージョンが利用可能です',
    'update.newVersionDetail': 'OpenSquilla {version} が利用可能です。今すぐダウンロードしますか？',
    'update.download': 'ダウンロード',
    'update.later': '後で',
    'update.readyTitle': 'アップデートの準備が完了しました',
    'update.readyDetail': 'OpenSquilla {version} をダウンロードしました。再起動して更新を完了しますか？',
    'update.restartNow': '今すぐ再起動',
    'update.upToDateTitle': '最新の状態です',
    'update.upToDateDetail': 'OpenSquilla {version} が最新バージョンです。',
    'update.errorTitle': 'アップデートの確認に失敗しました',
    'update.moveToApplications': '自動アップデートを有効にするには、OpenSquilla を「アプリケーション」フォルダに移動してから再試行してください。',
    'window.onboarding': 'OpenSquilla をセットアップ',
    'boot.profile': 'デスクトッププロファイルを準備しています',
    'boot.gateway-start': 'ローカルランタイムを起動しています',
    'boot.gateway-health': 'ゲートウェイの稼働状況を確認しています',
    'boot.control': 'コントロール UI を読み込んでいます',
    'boot.ready': '準備完了',
    'onboarding.title': 'OpenSquilla をセットアップ',
    'onboarding.rail.title': 'デスクトップ設定',
    'onboarding.rail.subtitle': 'ガイド付き CLI と同じ順序でローカルランタイムを設定します。',
    'onboarding.rail.foot': 'OpenSquilla はこのプロファイルをこのデバイス内に保持します。',
    'onboarding.aria.setupSteps': 'セットアップ手順',
    'onboarding.aria.setupDepth': 'セットアップの詳細度',
    'onboarding.aria.routerMode': 'ルーターモード',
    'onboarding.aria.searchProvider': '検索プロバイダー',
    'onboarding.nav.mode.title': 'モード',
    'onboarding.nav.mode.sub': 'セットアップの詳細度',
    'onboarding.nav.provider.title': 'プロバイダー',
    'onboarding.nav.provider.sub': 'モデルアクセス',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': 'ルーティングモード',
    'onboarding.nav.tiers.title': 'ティア',
    'onboarding.nav.tiers.sub': 'デフォルトモデル',
    'onboarding.nav.search.title': '検索',
    'onboarding.nav.search.sub': '任意のウェブアクセス',
    'onboarding.step1.badge': '開始',
    'onboarding.step1.heading': 'セットアップの詳細度を選択',
    'onboarding.step1.subtitle': '最短で動作する経路から始めるか、ここでルーターとティアの設定をすべて開きます。',
    'onboarding.step1.simpleTitle': 'シンプルセットアップ',
    'onboarding.step1.simpleDesc': 'プロバイダーを 1 つ選び、キーを追加して検索を選択し、デフォルト設定で OpenSquilla を起動します。',
    'onboarding.step1.advancedTitle': '詳細セットアップ',
    'onboarding.step1.advancedDesc': '起動前に Smart Router モード、ティアのデフォルト、直接モデルの詳細を確認します。',
    'onboarding.step1.note': 'プロバイダー、ルーター、検索の設定は後でデスクトップの設定ページから変更できます。',
    'onboarding.step1.quit': '終了',
    'onboarding.step1.continue': '続行',
    'onboarding.step2.badge': '必須',
    'onboarding.step2.heading': 'プロバイダーを接続',
    'onboarding.step2.subtitle': 'これはローカルランタイムがモデル呼び出しに使用するアカウントです。OpenRouter がデフォルトで、その他のプロバイダーは必要になるまで隠れています。',
    'onboarding.step2.apiKey': 'API キー',
    'onboarding.step2.endpointSummary': 'エンドポイントと直接モデル',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': '直接モデル',
    'onboarding.step2.back': '戻る',
    'onboarding.step2.next': '次へ',
    'onboarding.step3.badge': 'ルーティング',
    'onboarding.step3.heading': 'Smart Router モードを選択',
    'onboarding.step3.subtitle': 'OpenSquilla がティアのデフォルトで作業を振り分けるか、1 つのモデルを直接呼び出すかを選択します。',
    'onboarding.step3.back': '戻る',
    'onboarding.step3.next': '次へ',
    'onboarding.step4.badge': 'モデル',
    'onboarding.step4.heading': 'ティアのモデルを確認',
    'onboarding.step4.subtitle': 'デフォルトのテキストティアを選んで CLI のデフォルトを維持するか、起動前にモデル id をカスタマイズします。',
    'onboarding.step4.back': '戻る',
    'onboarding.step4.next': '次へ',
    'onboarding.step5.badge': '任意',
    'onboarding.step5.heading': 'ウェブ検索を選択',
    'onboarding.step5.subtitle': '検索は任意です。別のキーなしで開始するか、ランタイムが対応する検索プロバイダーを接続します。',
    'onboarding.step5.searchKey': '検索 API キー',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo で始めるには十分です。',
    'onboarding.step5.back': '戻る',
    'onboarding.step5.finish': 'OpenSquilla を起動',
    'onboarding.more.show': 'その他のプロバイダー',
    'onboarding.more.hide': 'プロバイダーを隠す',
  },
  fr: {
    'menu.edit': 'Édition',
    'menu.view': 'Affichage',
    'menu.window': 'Fenêtre',
    'menu.checkForUpdates': 'Rechercher les mises à jour…',
    'update.newVersionTitle': 'Une nouvelle version est disponible',
    'update.newVersionDetail': 'OpenSquilla {version} est disponible. Télécharger maintenant ?',
    'update.download': 'Télécharger',
    'update.later': 'Plus tard',
    'update.readyTitle': 'Mise à jour prête à installer',
    'update.readyDetail': 'OpenSquilla {version} a été téléchargée. Redémarrer pour terminer la mise à jour ?',
    'update.restartNow': 'Redémarrer maintenant',
    'update.upToDateTitle': 'Vous êtes à jour',
    'update.upToDateDetail': 'OpenSquilla {version} est la dernière version.',
    'update.errorTitle': 'Échec de la recherche de mises à jour',
    'update.moveToApplications': 'Déplacez OpenSquilla dans votre dossier Applications pour activer les mises à jour automatiques, puis réessayez.',
    'window.onboarding': 'Configurer OpenSquilla',
    'boot.profile': 'Préparation du profil de bureau',
    'boot.gateway-start': 'Démarrage du runtime local',
    'boot.gateway-health': 'Vérification de l\'état de la passerelle',
    'boot.control': 'Chargement de l\'interface de contrôle',
    'boot.ready': 'Prêt',
    'onboarding.title': 'Configurer OpenSquilla',
    'onboarding.rail.title': 'Configuration du bureau',
    'onboarding.rail.subtitle': 'Configurez le runtime local dans le même ordre que la CLI guidée.',
    'onboarding.rail.foot': 'OpenSquilla conserve ce profil en local sur cet appareil.',
    'onboarding.aria.setupSteps': 'Étapes de configuration',
    'onboarding.aria.setupDepth': 'Niveau de configuration',
    'onboarding.aria.routerMode': 'Mode du routeur',
    'onboarding.aria.searchProvider': 'Fournisseur de recherche',
    'onboarding.nav.mode.title': 'Mode',
    'onboarding.nav.mode.sub': 'Niveau de configuration',
    'onboarding.nav.provider.title': 'Fournisseur',
    'onboarding.nav.provider.sub': 'Accès aux modèles',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': 'Mode de routage',
    'onboarding.nav.tiers.title': 'Niveaux',
    'onboarding.nav.tiers.sub': 'Modèles par défaut',
    'onboarding.nav.search.title': 'Recherche',
    'onboarding.nav.search.sub': 'Accès web facultatif',
    'onboarding.step1.badge': 'Démarrer',
    'onboarding.step1.heading': 'Choisir le niveau de configuration',
    'onboarding.step1.subtitle': 'Commencez par le chemin fonctionnel le plus court, ou ouvrez dès maintenant tous les réglages de routeur et de niveaux.',
    'onboarding.step1.simpleTitle': 'Configuration simple',
    'onboarding.step1.simpleDesc': 'Choisissez un fournisseur, ajoutez sa clé, sélectionnez la recherche et démarrez OpenSquilla avec les valeurs par défaut.',
    'onboarding.step1.advancedTitle': 'Configuration avancée',
    'onboarding.step1.advancedDesc': 'Examinez le mode Smart Router, les niveaux par défaut et les détails du modèle direct avant le démarrage.',
    'onboarding.step1.note': 'Vous pourrez modifier les paramètres de fournisseur, de routeur et de recherche plus tard depuis la page Paramètres du bureau.',
    'onboarding.step1.quit': 'Quitter',
    'onboarding.step1.continue': 'Continuer',
    'onboarding.step2.badge': 'Requis',
    'onboarding.step2.heading': 'Connecter un fournisseur',
    'onboarding.step2.subtitle': 'C\'est le compte utilisé par le runtime local pour les appels de modèle. OpenRouter est le choix par défaut ; les autres fournisseurs restent masqués jusqu\'à ce que vous en ayez besoin.',
    'onboarding.step2.apiKey': 'Clé API',
    'onboarding.step2.endpointSummary': 'Point de terminaison et modèle direct',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Modèle direct',
    'onboarding.step2.back': 'Retour',
    'onboarding.step2.next': 'Suivant',
    'onboarding.step3.badge': 'Routage',
    'onboarding.step3.heading': 'Choisir le mode Smart Router',
    'onboarding.step3.subtitle': 'Choisissez si OpenSquilla doit répartir le travail entre les niveaux par défaut ou appeler un seul modèle directement.',
    'onboarding.step3.back': 'Retour',
    'onboarding.step3.next': 'Suivant',
    'onboarding.step4.badge': 'Modèles',
    'onboarding.step4.heading': 'Examiner les modèles par niveau',
    'onboarding.step4.subtitle': 'Choisissez le niveau de texte par défaut et conservez les valeurs par défaut de la CLI, ou personnalisez les id de modèle avant le démarrage.',
    'onboarding.step4.back': 'Retour',
    'onboarding.step4.next': 'Suivant',
    'onboarding.step5.badge': 'Facultatif',
    'onboarding.step5.heading': 'Choisir la recherche web',
    'onboarding.step5.subtitle': 'La recherche est facultative. Démarrez sans autre clé, ou connectez un fournisseur de recherche pris en charge par le runtime.',
    'onboarding.step5.searchKey': 'Clé API de recherche',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo suffit pour démarrer.',
    'onboarding.step5.back': 'Retour',
    'onboarding.step5.finish': 'Démarrer OpenSquilla',
    'onboarding.more.show': 'Plus de fournisseurs',
    'onboarding.more.hide': 'Masquer les fournisseurs',
  },
  de: {
    'menu.edit': 'Bearbeiten',
    'menu.view': 'Ansicht',
    'menu.window': 'Fenster',
    'menu.checkForUpdates': 'Nach Updates suchen…',
    'update.newVersionTitle': 'Eine neue Version ist verfügbar',
    'update.newVersionDetail': 'OpenSquilla {version} ist verfügbar. Jetzt herunterladen?',
    'update.download': 'Herunterladen',
    'update.later': 'Später',
    'update.readyTitle': 'Update bereit zur Installation',
    'update.readyDetail': 'OpenSquilla {version} wurde heruntergeladen. Neu starten, um das Update abzuschließen?',
    'update.restartNow': 'Jetzt neu starten',
    'update.upToDateTitle': 'Sie sind auf dem neuesten Stand',
    'update.upToDateDetail': 'OpenSquilla {version} ist die neueste Version.',
    'update.errorTitle': 'Update-Prüfung fehlgeschlagen',
    'update.moveToApplications': 'Verschieben Sie OpenSquilla in Ihren Programme-Ordner, um automatische Updates zu aktivieren, und versuchen Sie es erneut.',
    'window.onboarding': 'OpenSquilla einrichten',
    'boot.profile': 'Desktop-Profil wird vorbereitet',
    'boot.gateway-start': 'Lokale Laufzeitumgebung wird gestartet',
    'boot.gateway-health': 'Gateway-Zustand wird geprüft',
    'boot.control': 'Control-UI wird geladen',
    'boot.ready': 'Bereit',
    'onboarding.title': 'OpenSquilla einrichten',
    'onboarding.rail.title': 'Desktop-Einrichtung',
    'onboarding.rail.subtitle': 'Richten Sie die lokale Laufzeitumgebung in derselben Reihenfolge wie die geführte CLI ein.',
    'onboarding.rail.foot': 'OpenSquilla behält dieses Profil lokal auf diesem Gerät.',
    'onboarding.aria.setupSteps': 'Einrichtungsschritte',
    'onboarding.aria.setupDepth': 'Einrichtungstiefe',
    'onboarding.aria.routerMode': 'Router-Modus',
    'onboarding.aria.searchProvider': 'Suchanbieter',
    'onboarding.nav.mode.title': 'Modus',
    'onboarding.nav.mode.sub': 'Einrichtungstiefe',
    'onboarding.nav.provider.title': 'Anbieter',
    'onboarding.nav.provider.sub': 'Modellzugriff',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': 'Routing-Modus',
    'onboarding.nav.tiers.title': 'Stufen',
    'onboarding.nav.tiers.sub': 'Standardmodelle',
    'onboarding.nav.search.title': 'Suche',
    'onboarding.nav.search.sub': 'Optionaler Webzugriff',
    'onboarding.step1.badge': 'Start',
    'onboarding.step1.heading': 'Einrichtungstiefe wählen',
    'onboarding.step1.subtitle': 'Beginnen Sie mit dem kürzesten funktionierenden Weg, oder öffnen Sie jetzt die vollständigen Router- und Stufeneinstellungen.',
    'onboarding.step1.simpleTitle': 'Einfache Einrichtung',
    'onboarding.step1.simpleDesc': 'Wählen Sie einen Anbieter, fügen Sie seinen Schlüssel hinzu, wählen Sie die Suche und starten Sie OpenSquilla mit den Standardwerten.',
    'onboarding.step1.advancedTitle': 'Erweiterte Einrichtung',
    'onboarding.step1.advancedDesc': 'Prüfen Sie vor dem Start den Smart-Router-Modus, die Stufenstandards und die Details des direkten Modells.',
    'onboarding.step1.note': 'Sie können Anbieter-, Router- und Sucheinstellungen später auf der Desktop-Seite Einstellungen ändern.',
    'onboarding.step1.quit': 'Beenden',
    'onboarding.step1.continue': 'Weiter',
    'onboarding.step2.badge': 'Erforderlich',
    'onboarding.step2.heading': 'Anbieter verbinden',
    'onboarding.step2.subtitle': 'Dies ist das Konto, das die lokale Laufzeitumgebung für Modellaufrufe verwendet. OpenRouter ist die Standardeinstellung; weitere Anbieter bleiben ausgeblendet, bis Sie sie benötigen.',
    'onboarding.step2.apiKey': 'API-Schlüssel',
    'onboarding.step2.endpointSummary': 'Endpunkt und direktes Modell',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Direktes Modell',
    'onboarding.step2.back': 'Zurück',
    'onboarding.step2.next': 'Weiter',
    'onboarding.step3.badge': 'Routing',
    'onboarding.step3.heading': 'Smart-Router-Modus auswählen',
    'onboarding.step3.subtitle': 'Wählen Sie, ob OpenSquilla die Arbeit über die Stufenstandards verteilen oder ein einzelnes Modell direkt aufrufen soll.',
    'onboarding.step3.back': 'Zurück',
    'onboarding.step3.next': 'Weiter',
    'onboarding.step4.badge': 'Modelle',
    'onboarding.step4.heading': 'Stufenmodelle prüfen',
    'onboarding.step4.subtitle': 'Wählen Sie die Standard-Textstufe und behalten Sie die CLI-Standards bei, oder passen Sie die Modell-ids vor dem Start an.',
    'onboarding.step4.back': 'Zurück',
    'onboarding.step4.next': 'Weiter',
    'onboarding.step5.badge': 'Optional',
    'onboarding.step5.heading': 'Websuche wählen',
    'onboarding.step5.subtitle': 'Die Suche ist optional. Starten Sie ohne weiteren Schlüssel, oder verbinden Sie einen von der Laufzeitumgebung unterstützten Suchanbieter.',
    'onboarding.step5.searchKey': 'Such-API-Schlüssel',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo reicht für den Start.',
    'onboarding.step5.back': 'Zurück',
    'onboarding.step5.finish': 'OpenSquilla starten',
    'onboarding.more.show': 'Weitere Anbieter',
    'onboarding.more.hide': 'Anbieter ausblenden',
  },
  es: {
    'menu.edit': 'Edición',
    'menu.view': 'Ver',
    'menu.window': 'Ventana',
    'menu.checkForUpdates': 'Buscar actualizaciones…',
    'update.newVersionTitle': 'Hay una nueva versión disponible',
    'update.newVersionDetail': 'OpenSquilla {version} está disponible. ¿Descargar ahora?',
    'update.download': 'Descargar',
    'update.later': 'Más tarde',
    'update.readyTitle': 'Actualización lista para instalar',
    'update.readyDetail': 'OpenSquilla {version} se ha descargado. ¿Reiniciar para finalizar la actualización?',
    'update.restartNow': 'Reiniciar ahora',
    'update.upToDateTitle': 'Estás al día',
    'update.upToDateDetail': 'OpenSquilla {version} es la última versión.',
    'update.errorTitle': 'Error al buscar actualizaciones',
    'update.moveToApplications': 'Mueve OpenSquilla a tu carpeta de Aplicaciones para habilitar las actualizaciones automáticas e inténtalo de nuevo.',
    'window.onboarding': 'Configurar OpenSquilla',
    'boot.profile': 'Preparando el perfil de escritorio',
    'boot.gateway-start': 'Iniciando el runtime local',
    'boot.gateway-health': 'Comprobando el estado de la pasarela',
    'boot.control': 'Cargando la interfaz de control',
    'boot.ready': 'Listo',
    'onboarding.title': 'Configurar OpenSquilla',
    'onboarding.rail.title': 'Configuración de escritorio',
    'onboarding.rail.subtitle': 'Configura el runtime local en el mismo orden que la CLI guiada.',
    'onboarding.rail.foot': 'OpenSquilla mantiene este perfil local en este dispositivo.',
    'onboarding.aria.setupSteps': 'Pasos de configuración',
    'onboarding.aria.setupDepth': 'Nivel de configuración',
    'onboarding.aria.routerMode': 'Modo del enrutador',
    'onboarding.aria.searchProvider': 'Proveedor de búsqueda',
    'onboarding.nav.mode.title': 'Modo',
    'onboarding.nav.mode.sub': 'Nivel de configuración',
    'onboarding.nav.provider.title': 'Proveedor',
    'onboarding.nav.provider.sub': 'Acceso a modelos',
    'onboarding.nav.router.title': 'Smart Router',
    'onboarding.nav.router.sub': 'Modo de enrutamiento',
    'onboarding.nav.tiers.title': 'Niveles',
    'onboarding.nav.tiers.sub': 'Modelos predeterminados',
    'onboarding.nav.search.title': 'Búsqueda',
    'onboarding.nav.search.sub': 'Acceso web opcional',
    'onboarding.step1.badge': 'Inicio',
    'onboarding.step1.heading': 'Elige el nivel de configuración',
    'onboarding.step1.subtitle': 'Empieza por el camino funcional más corto, o abre ahora todos los controles de enrutador y niveles.',
    'onboarding.step1.simpleTitle': 'Configuración simple',
    'onboarding.step1.simpleDesc': 'Elige un proveedor, añade su clave, selecciona la búsqueda e inicia OpenSquilla con los valores predeterminados.',
    'onboarding.step1.advancedTitle': 'Configuración avanzada',
    'onboarding.step1.advancedDesc': 'Revisa el modo Smart Router, los valores predeterminados de niveles y los detalles del modelo directo antes del inicio.',
    'onboarding.step1.note': 'Puedes cambiar los ajustes de proveedor, enrutador y búsqueda más tarde desde la página Ajustes del escritorio.',
    'onboarding.step1.quit': 'Salir',
    'onboarding.step1.continue': 'Continuar',
    'onboarding.step2.badge': 'Obligatorio',
    'onboarding.step2.heading': 'Conectar un proveedor',
    'onboarding.step2.subtitle': 'Esta es la cuenta que usa el runtime local para las llamadas a modelos. OpenRouter es el predeterminado; los demás proveedores permanecen ocultos hasta que los necesites.',
    'onboarding.step2.apiKey': 'Clave API',
    'onboarding.step2.endpointSummary': 'Endpoint y modelo directo',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Modelo directo',
    'onboarding.step2.back': 'Atrás',
    'onboarding.step2.next': 'Siguiente',
    'onboarding.step3.badge': 'Enrutamiento',
    'onboarding.step3.heading': 'Selecciona el modo Smart Router',
    'onboarding.step3.subtitle': 'Elige si OpenSquilla debe distribuir el trabajo entre los valores predeterminados de niveles o llamar a un solo modelo directamente.',
    'onboarding.step3.back': 'Atrás',
    'onboarding.step3.next': 'Siguiente',
    'onboarding.step4.badge': 'Modelos',
    'onboarding.step4.heading': 'Revisa los modelos por nivel',
    'onboarding.step4.subtitle': 'Elige el nivel de texto predeterminado y mantén los valores predeterminados de la CLI, o personaliza los id de modelo antes del inicio.',
    'onboarding.step4.back': 'Atrás',
    'onboarding.step4.next': 'Siguiente',
    'onboarding.step5.badge': 'Opcional',
    'onboarding.step5.heading': 'Elige la búsqueda web',
    'onboarding.step5.subtitle': 'La búsqueda es opcional. Empieza sin otra clave, o conecta un proveedor de búsqueda compatible con el runtime.',
    'onboarding.step5.searchKey': 'Clave API de búsqueda',
    'onboarding.step5.searchHintDefault': 'DuckDuckGo es suficiente para empezar.',
    'onboarding.step5.back': 'Atrás',
    'onboarding.step5.finish': 'Iniciar OpenSquilla',
    'onboarding.more.show': 'Más proveedores',
    'onboarding.more.hide': 'Ocultar proveedores',
  },
}

// Runtime string bag for the onboarding inline <script>. These literals are
// built dynamically in the browser (validateStep messages, mode/provider/search
// hints, More/Hide toggles), so they cannot use desktopT() server-side. The bag
// is JSON-serialized into the page. Placeholders like {label} are substituted at
// runtime so word order stays correct per language.
const ONBOARDING_SCRIPT_MESSAGES: Record<DesktopLocale, Record<string, string>> = {
  en: {
    tierDefaultsAvailable: 'Tier defaults available.',
    modeOpenrouterMix: 'OpenRouter model mix',
    modeDirect: 'Direct model',
    modeDefaultTier: 'Default tier routing',
    providerHint: '{label} stores the key as {env}. {note}',
    noApiKey: 'no API key',
    autoBodyOpenrouter: 'Use the default OpenRouter tier settings.',
    autoBody: 'Route simple, normal, and hard work through the {label} tier profile.',
    autoTitle: 'Automatic tier routing',
    fixedTitle: 'Use one fixed model',
    fixedBody: 'Skip Smart Router and send every request to the direct model.',
    routerHintDisabled: 'Requests will use the direct model field from the provider step.',
    routerHintActive: '{mode} is active. The next step shows the exact t0-t3 and image model ids before saving.',
    directModelLabel: 'Direct model',
    noModel: 'No model',
    directModelNote: 'Smart Router is off. Every request uses this model directly.',
    defaultPill: 'default',
    providerField: 'Provider',
    modelField: 'Model',
    customizeTiers: 'Customize tier models',
    requiresApiKey: 'Requires an API key.',
    noKeyRequired: 'No key required.',
    searchAvailable: '{label} will be available to browser-capable agents.',
    searchHintDefault: 'DuckDuckGo is enough to start.',
    apiKeyRequired: '{label} API key is required.',
    directModelRequiredDisabled: 'Direct model is required when Smart Router is disabled.',
    defaultTierRequiresModel: 'Default router tier requires a model.',
    searchApiKeyRequired: '{label} search API key is required.',
    moreProviders: 'More providers',
    hideProviders: 'Hide providers',
    stepLabel: 'Step {n}',
  },
  'zh-Hans': {
    tierDefaultsAvailable: '提供层级默认值。',
    modeOpenrouterMix: 'OpenRouter 模型混合',
    modeDirect: '直连模型',
    modeDefaultTier: '默认层级路由',
    providerHint: '{label} 将密钥存储为 {env}。{note}',
    noApiKey: '无 API 密钥',
    autoBodyOpenrouter: '使用默认的 OpenRouter 层级设置。',
    autoBody: '通过 {label} 层级配置路由简单、普通和困难的工作。',
    autoTitle: '自动层级路由',
    fixedTitle: '使用一个固定模型',
    fixedBody: '跳过 Smart Router，将每个请求都发送到直连模型。',
    routerHintDisabled: '请求将使用提供商步骤中的直连模型字段。',
    routerHintActive: '{mode} 已启用。下一步将在保存前显示确切的 t0-t3 和图像模型 id。',
    directModelLabel: '直连模型',
    noModel: '无模型',
    directModelNote: 'Smart Router 已关闭。每个请求都直接使用此模型。',
    defaultPill: '默认',
    providerField: '提供商',
    modelField: '模型',
    customizeTiers: '自定义层级模型',
    requiresApiKey: '需要 API 密钥。',
    noKeyRequired: '无需密钥。',
    searchAvailable: '{label} 将可供具备浏览能力的 agent 使用。',
    searchHintDefault: 'DuckDuckGo 足以开始使用。',
    apiKeyRequired: '需要 {label} API 密钥。',
    directModelRequiredDisabled: '禁用 Smart Router 时需要直连模型。',
    defaultTierRequiresModel: '默认路由层级需要一个模型。',
    searchApiKeyRequired: '需要 {label} 搜索 API 密钥。',
    moreProviders: '更多提供商',
    hideProviders: '收起提供商',
    stepLabel: '步骤 {n}',
  },
  ja: {
    tierDefaultsAvailable: 'ティアのデフォルトを利用できます。',
    modeOpenrouterMix: 'OpenRouter モデルミックス',
    modeDirect: '直接モデル',
    modeDefaultTier: 'デフォルトティアルーティング',
    providerHint: '{label} はキーを {env} として保存します。{note}',
    noApiKey: 'API キーなし',
    autoBodyOpenrouter: 'デフォルトの OpenRouter ティア設定を使用します。',
    autoBody: '簡単・通常・難しい作業を {label} のティアプロファイル経由で振り分けます。',
    autoTitle: '自動ティアルーティング',
    fixedTitle: '固定モデルを 1 つ使用',
    fixedBody: 'Smart Router をスキップし、すべてのリクエストを直接モデルに送信します。',
    routerHintDisabled: 'リクエストはプロバイダー手順の直接モデルフィールドを使用します。',
    routerHintActive: '{mode} が有効です。次の手順では保存前に正確な t0-t3 と画像モデルの id を表示します。',
    directModelLabel: '直接モデル',
    noModel: 'モデルなし',
    directModelNote: 'Smart Router はオフです。すべてのリクエストでこのモデルを直接使用します。',
    defaultPill: 'デフォルト',
    providerField: 'プロバイダー',
    modelField: 'モデル',
    customizeTiers: 'ティアモデルをカスタマイズ',
    requiresApiKey: 'API キーが必要です。',
    noKeyRequired: 'キーは不要です。',
    searchAvailable: '{label} はブラウザ対応のエージェントで利用できるようになります。',
    searchHintDefault: 'DuckDuckGo で始めるには十分です。',
    apiKeyRequired: '{label} の API キーが必要です。',
    directModelRequiredDisabled: 'Smart Router を無効にする場合は直接モデルが必要です。',
    defaultTierRequiresModel: 'デフォルトのルーターティアにはモデルが必要です。',
    searchApiKeyRequired: '{label} の検索 API キーが必要です。',
    moreProviders: 'その他のプロバイダー',
    hideProviders: 'プロバイダーを隠す',
    stepLabel: 'ステップ {n}',
  },
  fr: {
    tierDefaultsAvailable: 'Valeurs de niveau par défaut disponibles.',
    modeOpenrouterMix: 'Mélange de modèles OpenRouter',
    modeDirect: 'Modèle direct',
    modeDefaultTier: 'Routage par niveau par défaut',
    providerHint: '{label} enregistre la clé sous {env}. {note}',
    noApiKey: 'aucune clé API',
    autoBodyOpenrouter: 'Utiliser les réglages de niveau OpenRouter par défaut.',
    autoBody: 'Acheminer le travail simple, normal et difficile via le profil de niveaux {label}.',
    autoTitle: 'Routage automatique par niveau',
    fixedTitle: 'Utiliser un seul modèle fixe',
    fixedBody: 'Ignorer Smart Router et envoyer chaque requête au modèle direct.',
    routerHintDisabled: 'Les requêtes utiliseront le champ de modèle direct de l\'étape fournisseur.',
    routerHintActive: '{mode} est actif. L\'étape suivante affiche les id exacts t0-t3 et du modèle d\'image avant l\'enregistrement.',
    directModelLabel: 'Modèle direct',
    noModel: 'Aucun modèle',
    directModelNote: 'Smart Router est désactivé. Chaque requête utilise directement ce modèle.',
    defaultPill: 'par défaut',
    providerField: 'Fournisseur',
    modelField: 'Modèle',
    customizeTiers: 'Personnaliser les modèles de niveau',
    requiresApiKey: 'Nécessite une clé API.',
    noKeyRequired: 'Aucune clé requise.',
    searchAvailable: '{label} sera disponible pour les agents capables de naviguer.',
    searchHintDefault: 'DuckDuckGo suffit pour démarrer.',
    apiKeyRequired: 'La clé API {label} est requise.',
    directModelRequiredDisabled: 'Un modèle direct est requis lorsque Smart Router est désactivé.',
    defaultTierRequiresModel: 'Le niveau de routeur par défaut nécessite un modèle.',
    searchApiKeyRequired: 'La clé API de recherche {label} est requise.',
    moreProviders: 'Plus de fournisseurs',
    hideProviders: 'Masquer les fournisseurs',
    stepLabel: 'Étape {n}',
  },
  de: {
    tierDefaultsAvailable: 'Stufenstandards verfügbar.',
    modeOpenrouterMix: 'OpenRouter-Modellmix',
    modeDirect: 'Direktes Modell',
    modeDefaultTier: 'Standard-Stufenrouting',
    providerHint: '{label} speichert den Schlüssel als {env}. {note}',
    noApiKey: 'kein API-Schlüssel',
    autoBodyOpenrouter: 'Die Standard-OpenRouter-Stufeneinstellungen verwenden.',
    autoBody: 'Einfache, normale und schwierige Arbeit über das {label}-Stufenprofil leiten.',
    autoTitle: 'Automatisches Stufenrouting',
    fixedTitle: 'Ein festes Modell verwenden',
    fixedBody: 'Smart Router überspringen und jede Anfrage an das direkte Modell senden.',
    routerHintDisabled: 'Anfragen verwenden das Feld für das direkte Modell aus dem Anbieterschritt.',
    routerHintActive: '{mode} ist aktiv. Der nächste Schritt zeigt vor dem Speichern die genauen t0-t3- und Bildmodell-ids.',
    directModelLabel: 'Direktes Modell',
    noModel: 'Kein Modell',
    directModelNote: 'Smart Router ist aus. Jede Anfrage verwendet dieses Modell direkt.',
    defaultPill: 'Standard',
    providerField: 'Anbieter',
    modelField: 'Modell',
    customizeTiers: 'Stufenmodelle anpassen',
    requiresApiKey: 'Erfordert einen API-Schlüssel.',
    noKeyRequired: 'Kein Schlüssel erforderlich.',
    searchAvailable: '{label} wird für browserfähige Agenten verfügbar sein.',
    searchHintDefault: 'DuckDuckGo reicht für den Start.',
    apiKeyRequired: 'Der API-Schlüssel für {label} ist erforderlich.',
    directModelRequiredDisabled: 'Ein direktes Modell ist erforderlich, wenn Smart Router deaktiviert ist.',
    defaultTierRequiresModel: 'Die Standard-Routerstufe erfordert ein Modell.',
    searchApiKeyRequired: 'Der Such-API-Schlüssel für {label} ist erforderlich.',
    moreProviders: 'Weitere Anbieter',
    hideProviders: 'Anbieter ausblenden',
    stepLabel: 'Schritt {n}',
  },
  es: {
    tierDefaultsAvailable: 'Valores de nivel predeterminados disponibles.',
    modeOpenrouterMix: 'Mezcla de modelos OpenRouter',
    modeDirect: 'Modelo directo',
    modeDefaultTier: 'Enrutamiento por nivel predeterminado',
    providerHint: '{label} guarda la clave como {env}. {note}',
    noApiKey: 'sin clave API',
    autoBodyOpenrouter: 'Usar los ajustes de nivel de OpenRouter predeterminados.',
    autoBody: 'Enrutar el trabajo simple, normal y difícil a través del perfil de niveles {label}.',
    autoTitle: 'Enrutamiento automático por nivel',
    fixedTitle: 'Usar un solo modelo fijo',
    fixedBody: 'Omitir Smart Router y enviar cada solicitud al modelo directo.',
    routerHintDisabled: 'Las solicitudes usarán el campo de modelo directo del paso del proveedor.',
    routerHintActive: '{mode} está activo. El siguiente paso muestra los id exactos t0-t3 y del modelo de imagen antes de guardar.',
    directModelLabel: 'Modelo directo',
    noModel: 'Sin modelo',
    directModelNote: 'Smart Router está desactivado. Cada solicitud usa este modelo directamente.',
    defaultPill: 'predeterminado',
    providerField: 'Proveedor',
    modelField: 'Modelo',
    customizeTiers: 'Personalizar modelos de nivel',
    requiresApiKey: 'Requiere una clave API.',
    noKeyRequired: 'No se requiere clave.',
    searchAvailable: '{label} estará disponible para los agentes con capacidad de navegación.',
    searchHintDefault: 'DuckDuckGo es suficiente para empezar.',
    apiKeyRequired: 'Se requiere la clave API de {label}.',
    directModelRequiredDisabled: 'Se requiere un modelo directo cuando Smart Router está desactivado.',
    defaultTierRequiresModel: 'El nivel de enrutador predeterminado requiere un modelo.',
    searchApiKeyRequired: 'Se requiere la clave API de búsqueda de {label}.',
    moreProviders: 'Más proveedores',
    hideProviders: 'Ocultar proveedores',
    stepLabel: 'Paso {n}',
  },
}

function onboardingMessages(locale: DesktopLocale): Record<string, string> {
  return { ...ONBOARDING_SCRIPT_MESSAGES.en, ...ONBOARDING_SCRIPT_MESSAGES[locale] }
}

function desktopT(key: string): string {
  return DESKTOP_MESSAGES[desktopLocale][key] ?? DESKTOP_MESSAGES.en[key] ?? key
}

function createApplicationMenu(): void {
  const appSubmenu: Electron.MenuItemConstructorOptions[] = [{ role: 'about' }]
  if (autoUpdateSupported()) {
    appSubmenu.push(
      { type: 'separator' },
      {
        label: desktopT('menu.checkForUpdates'),
        click: () => {
          void checkForUpdates(true)
        },
      },
    )
  }
  appSubmenu.push({ type: 'separator' }, { role: 'quit' })

  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: app.name,
      submenu: appSubmenu,
    },
    {
      label: desktopT('menu.edit'),
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'pasteAndMatchStyle' },
        { role: 'delete' },
        { type: 'separator' },
        { role: 'selectAll' },
      ],
    },
    {
      label: desktopT('menu.view'),
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
      ],
    },
    {
      label: desktopT('menu.window'),
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { role: 'front' },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function currentOnboardingWindow(): BrowserWindow | null {
  return onboardingWindow && !onboardingWindow.isDestroyed() ? onboardingWindow : null
}

function focusOnboardingWindow(): boolean {
  const window = currentOnboardingWindow()
  if (!window) return false
  if (window.isMinimized()) window.restore()
  window.show()
  window.focus()
  return true
}

function focusMainWindow(): boolean {
  if (focusOnboardingWindow()) return true
  if (!mainWindow || mainWindow.isDestroyed()) return false
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
  return true
}

function installEditingContextMenu(window: BrowserWindow): void {
  window.webContents.on('context-menu', (_event, params) => {
    if (!params.isEditable) return
    Menu.buildFromTemplate([
      { role: 'cut', enabled: params.editFlags.canCut },
      { role: 'copy', enabled: params.editFlags.canCopy },
      { role: 'paste', enabled: params.editFlags.canPaste },
      { type: 'separator' },
      { role: 'selectAll', enabled: params.editFlags.canSelectAll },
    ]).popup({ window })
  })
}

// Server-side HTML escape for localized strings interpolated into the
// onboarding template. Mirrors the browser-side escapeHtml() in the inline
// script so static translated text is safe in both text content and attributes.
function escapeHtmlServer(value: string): string {
  return String(value).replace(/[&<>"']/g, (char) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char] as string
  ))
}

// Localized server-rendered onboarding string, HTML-escaped for safe insertion.
function ot(key: string): string {
  return escapeHtmlServer(desktopT(key))
}

function onboardingHtml(): string {
  return `<!doctype html>
<html lang="${desktopLocale}">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;">
  <title>${ot('onboarding.title')}</title>
  <style>
    :root {
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
      --bg: #f5f2eb;
      --paper: rgba(255, 254, 249, 0.96);
      --ink: #20231f;
      --muted: #646961;
      --dim: #8c9189;
      --line: rgba(32, 35, 31, 0.12);
      --accent: #b84a12;
      --accent-dark: #8f3305;
      --accent-soft: rgba(184, 74, 18, 0.08);
      --green: #25633a;
      color: var(--ink);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      overflow: hidden;
      background: linear-gradient(135deg, #fbfaf6 0%, var(--bg) 52%, #ece8de 100%);
    }
    main {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr);
      padding: 24px;
      gap: 20px;
    }
    .rail {
      display: grid;
      grid-template-rows: auto 1fr auto;
      border-radius: 8px;
      background: rgba(255, 252, 246, 0.5);
      border: 1px solid rgba(30,34,30,0.09);
      padding: 20px;
    }
    .rail h1 {
      margin: 0 0 8px;
      font-size: 23px;
      font-weight: 650;
      line-height: 1.08;
      letter-spacing: 0;
    }
    .rail p {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.48;
    }
    .progress {
      align-self: center;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .step {
      appearance: none;
      display: grid;
      grid-template-columns: 26px 1fr;
      gap: 10px;
      align-items: center;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: var(--dim);
      cursor: pointer;
      min-height: 48px;
      padding: 5px;
      text-align: left;
    }
    .step:hover {
      background: rgba(255,255,255,0.5);
    }
    .step-index {
      width: 26px;
      height: 26px;
      display: grid;
      place-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(255,255,255,0.58);
      color: inherit;
      font-size: 11px;
      font-weight: 650;
    }
    .step strong {
      display: block;
      color: inherit;
      font-size: 13px;
      font-weight: 650;
    }
    .step span:last-child {
      display: block;
      margin-top: 1px;
      font-size: 11px;
      font-weight: 600;
    }
    .step.active, .step.done { color: var(--ink); }
    .step.simple-hidden {
      display: none;
    }
    .step.active .step-index {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      box-shadow: 0 9px 18px rgba(194, 65, 5, 0.2);
    }
    .step.done .step-index {
      border-color: rgba(35,106,58,0.32);
      background: rgba(35,106,58,0.1);
      color: var(--green);
    }
    .rail-foot {
      color: var(--dim);
      font-size: 11px;
      font-weight: 600;
      line-height: 1.4;
    }
    .deck {
      position: relative;
      min-width: 0;
      min-height: 0;
      display: grid;
      place-items: center;
    }
    .deck > .error {
      position: absolute;
      left: 30px;
      right: 30px;
      bottom: 18px;
      z-index: 3;
    }
    [hidden] {
      display: none !important;
    }
    .setup-card {
      position: absolute;
      top: 50%;
      left: 50%;
      width: min(780px, calc(100% - 34px));
      height: min(760px, calc(100vh - 48px));
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 18px;
      border: 1px solid rgba(30,34,30,0.1);
      border-radius: 8px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.9), rgba(255,254,249,0.96)),
        var(--paper);
      box-shadow: 0 24px 70px rgba(35, 32, 26, 0.13), inset 0 1px 0 rgba(255,255,255,0.8);
      opacity: 0;
      pointer-events: none;
      transform: translate(calc(-50% + 18px), -50%) scale(0.985);
      transition: opacity 180ms ease, transform 220ms cubic-bezier(.2,.8,.2,1);
      padding: 28px 28px 26px;
    }
    .setup-card.active {
      opacity: 1;
      pointer-events: auto;
      transform: translate(-50%, -50%) scale(1);
    }
    .setup-card.leaving {
      opacity: 0;
      pointer-events: none;
      transform: translate(calc(-50% - 18px), -50%) scale(0.985);
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      gap: 20px;
    }
    .eyebrow {
      margin: 0 0 9px;
      color: var(--accent);
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    h2 {
      margin: 0;
      max-width: 460px;
      font-size: 30px;
      font-weight: 650;
      line-height: 1.08;
      letter-spacing: 0;
    }
    p {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
      margin: 10px 0 0;
    }
    .card-badge {
      align-self: start;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.68);
      color: var(--muted);
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0.08em;
      padding: 7px 10px;
      text-transform: uppercase;
    }
    .card-body {
      display: grid;
      gap: 14px;
      align-content: start;
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
      padding-right: 2px;
    }
    .setup-card[data-screen="0"] .card-body,
    .setup-card[data-screen="1"] .card-body {
      overflow: visible;
    }
    .provider-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .provider-grid.single-provider {
      grid-template-columns: 1fr;
    }
    .setup-mode-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .setup-mode-grid .choice {
      min-height: 152px;
      padding: 18px;
      align-content: start;
    }
    .setup-mode-grid .choice strong {
      font-size: 18px;
      line-height: 1.15;
    }
    .setup-mode-grid .choice small {
      max-width: 250px;
      font-size: 12px;
      line-height: 1.45;
    }
    .provider, .choice, .tier-button {
      appearance: none;
      position: relative;
      display: grid;
      gap: 4px;
      min-height: 82px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.62);
      color: var(--ink);
      cursor: pointer;
      padding: 13px 12px;
      text-align: left;
      transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease, background 160ms ease;
    }
    .provider {
      min-height: 68px;
      padding: 11px 13px;
    }
    .provider:hover, .choice:hover, .tier-button:hover {
      border-color: rgba(184,74,18,0.3);
      transform: translateY(-1px);
    }
    .provider.active, .choice.active, .tier-button.active {
      border-color: var(--accent);
      background: #fffaf4;
      box-shadow: 0 12px 26px rgba(54, 42, 28, 0.065);
    }
    .provider.active::after, .choice.active::after, .tier-button.active::after {
      content: "";
      position: absolute;
      top: 10px;
      right: 10px;
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
    }
    .provider:disabled, .choice:disabled {
      opacity: 0.48;
      cursor: not-allowed;
      transform: none;
    }
    .provider strong, .choice strong, .tier-button strong {
      display: block;
      padding-right: 12px;
      font-size: 14px;
      font-weight: 650;
    }
    .provider small, .choice small, .tier-button small {
      color: var(--muted);
      display: block;
      padding-right: 5px;
      font-size: 11px;
      font-weight: 450;
      line-height: 1.38;
    }
    .provider-tag {
      width: fit-content;
      border: 1px solid rgba(184,74,18,0.14);
      border-radius: 999px;
      background: rgba(184,74,18,0.06);
      color: var(--accent-dark);
      font-size: 9px;
      font-weight: 750;
      letter-spacing: 0.06em;
      padding: 3px 6px;
      text-transform: uppercase;
    }
    .provider-more {
      position: relative;
      display: grid;
      gap: 8px;
    }
    .provider-more-toggle {
      width: 100%;
      min-height: 38px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border: 1px solid rgba(32,35,31,0.1);
      border-radius: 8px;
      background: rgba(255,255,255,0.48);
      color: #5f665e;
      font-size: 12px;
      font-weight: 700;
      padding: 0 12px;
      text-align: left;
    }
    .provider-more-toggle:hover {
      border-color: rgba(184,74,18,0.24);
      color: var(--ink);
    }
    .provider-more-list {
      position: absolute;
      z-index: 5;
      top: 43px;
      left: 0;
      right: 0;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 7px;
      border: 1px solid rgba(32,35,31,0.12);
      border-radius: 8px;
      background: rgba(255,254,249,0.98);
      box-shadow: 0 18px 42px rgba(35, 32, 26, 0.16);
      padding: 8px;
    }
    .provider-row {
      appearance: none;
      min-height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border: 1px solid rgba(32,35,31,0.1);
      border-radius: 8px;
      background: rgba(255,255,255,0.52);
      color: var(--ink);
      padding: 0 11px;
      text-align: left;
    }
    .provider-row strong {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 650;
    }
    .provider-row small {
      flex: none;
      color: var(--dim);
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .provider-row.active {
      border-color: var(--accent);
      background: #fffaf4;
      color: var(--accent-dark);
    }
    .choice-row, .tier-defaults {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .router-choice {
      display: grid;
      gap: 12px;
    }
    .router-primary {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .router-primary .choice {
      min-height: 112px;
      padding: 16px;
    }
    .router-primary .choice strong {
      font-size: 16px;
    }
    .router-subchoice {
      display: grid;
      gap: 8px;
      border: 1px solid rgba(32,35,31,0.1);
      border-radius: 8px;
      background: rgba(255,255,255,0.46);
      padding: 12px;
    }
    .router-subchoice > span {
      color: var(--dim);
      font-size: 11px;
      font-weight: 750;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .router-subgrid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .router-subgrid .choice {
      min-height: 72px;
      padding: 12px;
    }
    .tier-defaults {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .tier-button {
      min-height: 62px;
      min-width: 0;
      overflow: hidden;
    }
    .tier-button small {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    label {
      display: grid;
      gap: 8px;
      color: #565c54;
      font-size: 12px;
      font-weight: 600;
    }
    input, select {
      width: 100%;
      min-height: 42px;
      border: 1px solid #d8d1c3;
      border-radius: 8px;
      background: rgba(255,255,255,0.74);
      color: #1f231f;
      font: inherit;
      font-size: 14px;
      font-weight: 450;
      padding: 0 13px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(184, 68, 4, 0.12);
    }
    details {
      border: 1px solid #e2e0da;
      border-radius: 8px;
      background: rgba(255,255,255,0.46);
      padding: 11px 13px;
    }
    summary {
      color: #656b64;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
    }
    .field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .tier-list { display: grid; gap: 8px; }
    .tier-item {
      display: grid;
      grid-template-columns: 88px minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.55);
      padding: 11px 12px;
    }
    .tier-name { color: var(--accent-dark); font-size: 13px; font-weight: 750; }
    #tierBody { min-width: 0; }
    .tier-model { min-width: 0; }
    .tier-model strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 650;
    }
    .tier-model small { color: var(--muted); font-size: 11px; }
    .pill {
      border: 1px solid rgba(37,99,58,0.2);
      border-radius: 999px;
      background: rgba(37,99,58,0.08);
      color: var(--green);
      font-size: 10px;
      font-weight: 700;
      padding: 5px 8px;
      text-transform: uppercase;
    }
    .editor-grid { display: grid; gap: 12px; margin-top: 12px; }
    .editor-row {
      border-top: 1px solid rgba(32,35,31,0.08);
      padding-top: 11px;
    }
    .muted-line { color: var(--dim); font-size: 12px; }
    .note {
      border: 1px solid rgba(194,65,5,0.13);
      border-radius: 8px;
      background: rgba(194,65,5,0.055);
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
      line-height: 1.45;
      padding: 10px 12px;
    }
    .actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 42px;
    }
    button {
      min-height: 40px;
      border: 1px solid transparent;
      cursor: pointer;
      font-size: 14px;
      font-weight: 650;
      padding: 0 17px;
    }
    .secondary {
      background: transparent;
      color: #656b64;
    }
    .secondary:hover { color: var(--ink); }
    .primary {
      background: linear-gradient(135deg, var(--accent), var(--accent-dark));
      border-radius: 8px;
      color: #fff;
      box-shadow: 0 13px 28px rgba(194, 65, 5, 0.22);
      min-width: 150px;
    }
    .primary:hover {
      transform: translateY(-1px);
    }
    .primary:disabled { opacity: 0.55; cursor: not-allowed; }
    .error {
      min-height: 18px;
      color: #b42318;
      font-size: 12px;
      font-weight: 750;
    }
    @media (max-width: 680px) {
      main {
        grid-template-columns: 1fr;
        overflow: auto;
      }
      .rail { display: none; }
      .setup-card { position: relative; min-height: 620px; height: auto; }
      .provider-grid, .setup-mode-grid, .choice-row, .tier-defaults, .field-pair { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <aside class="rail">
      <section>
        <h1>${ot('onboarding.rail.title')}</h1>
        <p>${ot('onboarding.rail.subtitle')}</p>
      </section>
      <nav class="progress" aria-label="${ot('onboarding.aria.setupSteps')}">
        <button class="step active" type="button" data-step-label="0">
          <span class="step-index">1</span>
          <span><strong>${ot('onboarding.nav.mode.title')}</strong><span>${ot('onboarding.nav.mode.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="1">
          <span class="step-index">2</span>
          <span><strong>${ot('onboarding.nav.provider.title')}</strong><span>${ot('onboarding.nav.provider.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="2" data-advanced-step>
          <span class="step-index">3</span>
          <span><strong>${ot('onboarding.nav.router.title')}</strong><span>${ot('onboarding.nav.router.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="3" data-advanced-step>
          <span class="step-index">4</span>
          <span><strong>${ot('onboarding.nav.tiers.title')}</strong><span>${ot('onboarding.nav.tiers.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="4">
          <span class="step-index">5</span>
          <span><strong>${ot('onboarding.nav.search.title')}</strong><span>${ot('onboarding.nav.search.sub')}</span></span>
        </button>
      </nav>
      <div class="rail-foot">${ot('onboarding.rail.foot')}</div>
    </aside>
    <form id="setup-form" class="deck">
      <section class="setup-card active" data-screen="0">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 01</p>
            <h2>${ot('onboarding.step1.heading')}</h2>
            <p>${ot('onboarding.step1.subtitle')}</p>
          </div>
          <span class="card-badge">${ot('onboarding.step1.badge')}</span>
        </header>
        <div class="card-body">
          <div class="setup-mode-grid" role="radiogroup" aria-label="${ot('onboarding.aria.setupDepth')}">
            <button class="choice active" type="button" data-setup-mode="simple">
              <strong>${ot('onboarding.step1.simpleTitle')}</strong>
              <small>${ot('onboarding.step1.simpleDesc')}</small>
            </button>
            <button class="choice" type="button" data-setup-mode="advanced">
              <strong>${ot('onboarding.step1.advancedTitle')}</strong>
              <small>${ot('onboarding.step1.advancedDesc')}</small>
            </button>
          </div>
          <input id="setupMode" type="hidden" value="simple" />
          <div class="note">${ot('onboarding.step1.note')}</div>
        </div>
        <footer class="actions">
          <button class="secondary" type="button" id="cancel">${ot('onboarding.step1.quit')}</button>
          <button class="primary next-button" type="button">${ot('onboarding.step1.continue')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="1">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 02</p>
            <h2>${ot('onboarding.step2.heading')}</h2>
            <p>${ot('onboarding.step2.subtitle')}</p>
          </div>
          <span class="card-badge">${ot('onboarding.step2.badge')}</span>
        </header>
        <div class="card-body">
        <div class="provider-picker">
          <div class="provider-grid" id="providerGrid"></div>
          <div class="provider-more">
            <button class="provider-more-toggle" type="button" id="providerMoreToggle">
              <span>${ot('onboarding.more.show')}</span><span id="providerMoreCount"></span>
            </button>
            <div class="provider-more-list" id="providerMoreList" hidden></div>
          </div>
        </div>
        <input id="provider" type="hidden" value="openrouter" />
        <label>
          ${ot('onboarding.step2.apiKey')}
          <input id="apiKey" name="apiKey" type="password" autocomplete="off" placeholder="sk-..." />
        </label>
        <details>
          <summary>${ot('onboarding.step2.endpointSummary')}</summary>
          <div class="field-pair">
          <label>
            ${ot('onboarding.step2.baseUrl')}
            <input id="baseUrl" name="baseUrl" autocomplete="off" />
          </label>
          <label>
            ${ot('onboarding.step2.directModel')}
            <input id="model" name="model" autocomplete="off" />
          </label>
          </div>
        </details>
        <div class="note" id="providerHint"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">${ot('onboarding.step2.back')}</button>
          <button class="primary next-button" type="button">${ot('onboarding.step2.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="2">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 03</p>
            <h2>${ot('onboarding.step3.heading')}</h2>
            <p>${ot('onboarding.step3.subtitle')}</p>
          </div>
          <span class="card-badge">${ot('onboarding.step3.badge')}</span>
        </header>
        <div class="card-body">
          <div class="choice-row" id="routerModeGrid" role="radiogroup" aria-label="${ot('onboarding.aria.routerMode')}"></div>
          <input id="routerMode" type="hidden" value="recommended" />
          <div class="note" id="routerModeHint"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">${ot('onboarding.step3.back')}</button>
          <button class="primary next-button" type="button">${ot('onboarding.step3.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="3">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 04</p>
            <h2>${ot('onboarding.step4.heading')}</h2>
            <p>${ot('onboarding.step4.subtitle')}</p>
          </div>
          <span class="card-badge">${ot('onboarding.step4.badge')}</span>
        </header>
        <div class="card-body">
          <div id="tierBody"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">${ot('onboarding.step4.back')}</button>
          <button class="primary next-button" type="button">${ot('onboarding.step4.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="4">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 05</p>
            <h2>${ot('onboarding.step5.heading')}</h2>
            <p>${ot('onboarding.step5.subtitle')}</p>
          </div>
          <span class="card-badge">${ot('onboarding.step5.badge')}</span>
        </header>
        <div class="card-body">
        <div class="choice-row" id="searchProviderGrid" role="radiogroup" aria-label="${ot('onboarding.aria.searchProvider')}"></div>
        <input id="searchProvider" type="hidden" value="duckduckgo" />
        <label id="searchKeyLabel" hidden>
          ${ot('onboarding.step5.searchKey')}
          <input id="searchApiKey" name="searchApiKey" type="password" autocomplete="off" placeholder="SEARCH_API_KEY" />
        </label>
        <div class="note" id="searchHint">${ot('onboarding.step5.searchHintDefault')}</div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">${ot('onboarding.step5.back')}</button>
          <button class="primary" type="button" id="finish">${ot('onboarding.step5.finish')}</button>
        </footer>
      </section>
      <div class="error" id="error"></div>
    </form>
  </main>
  <script>
    const t = ${JSON.stringify(onboardingMessages(desktopLocale))};
    function fmt(key, vars) {
      let out = t[key] != null ? String(t[key]) : key;
      if (vars) for (const name of Object.keys(vars)) out = out.split('{' + name + '}').join(String(vars[name]));
      return out;
    }
    const providers = ${JSON.stringify(PROVIDER_CATALOG)};
    const searchProviders = ${JSON.stringify(SEARCH_PROVIDER_CATALOG)};
    const routerProfiles = ${JSON.stringify(ROUTER_PROFILES)};
    const textTiers = ${JSON.stringify(TEXT_ROUTER_TIERS)};
    const featuredProviderIds = ['openrouter'];
    let step = 0;
    let showMoreProviders = false;
    let routerTiers = clone(routerProfiles.openrouter);
    const setupMode = document.getElementById('setupMode');
    const provider = document.getElementById('provider');
    const baseUrl = document.getElementById('baseUrl');
    const model = document.getElementById('model');
    const providerHint = document.getElementById('providerHint');
    const routerMode = document.getElementById('routerMode');
    const routerModeHint = document.getElementById('routerModeHint');
    const routerModeGrid = document.getElementById('routerModeGrid');
    const tierBody = document.getElementById('tierBody');
    const searchHint = document.getElementById('searchHint');
    const errorBox = document.getElementById('error');
    const finish = document.getElementById('finish');
    const searchProvider = document.getElementById('searchProvider');
    const searchProviderGrid = document.getElementById('searchProviderGrid');
    const searchKeyLabel = document.getElementById('searchKeyLabel');
    function clone(value) {
      return JSON.parse(JSON.stringify(value || {}));
    }
    function currentProvider() {
      return providers.find((item) => item.id === provider.value) || providers[0];
    }
    function defaultModeFor(selected) {
      return selected.routerSupported ? 'recommended' : 'disabled';
    }
    function profileKeyForMode() {
      if (routerMode.value === 'openrouter-mix') return 'openrouter';
      return provider.value;
    }
    function modeLabel(mode) {
      if (mode === 'openrouter-mix') return t.modeOpenrouterMix;
      if (mode === 'disabled') return t.modeDirect;
      return t.modeDefaultTier;
    }
    function syncProviderDefaults(resetRouter) {
      const selected = currentProvider();
      baseUrl.value = selected.baseUrl || baseUrl.value;
      model.value = selected.model || model.value;
      providerHint.textContent = fmt('providerHint', { label: selected.label, env: selected.apiKeyEnv || t.noApiKey, note: selected.note });
      if (resetRouter) {
        routerMode.value = defaultModeFor(selected);
        routerTiers = clone(routerProfiles[profileKeyForMode()]);
      }
      renderRouterModes();
      renderTiers();
    }
    function renderProviderGrid() {
      const grid = document.getElementById('providerGrid');
      const moreList = document.getElementById('providerMoreList');
      const moreToggle = document.getElementById('providerMoreToggle');
      const moreCount = document.getElementById('providerMoreCount');
      const featured = providers.filter((item) => featuredProviderIds.includes(item.id));
      const more = providers.filter((item) => !featuredProviderIds.includes(item.id));
      grid.classList.toggle('single-provider', featured.length === 1);
      grid.innerHTML = featured.map((item) => (
        '<button class="provider' + (item.id === provider.value ? ' active' : '') + '" type="button" data-provider="' + item.id + '">' +
        '<span class="provider-tag">provider</span><strong>' + item.label + '</strong><small>' + (item.routerSupported ? t.tierDefaultsAvailable : item.note) + '</small></button>'
      )).join('');
      moreToggle.querySelector('span:first-child').textContent = showMoreProviders ? t.hideProviders : t.moreProviders;
      moreCount.textContent = String(more.length);
      moreList.hidden = !showMoreProviders;
      moreList.innerHTML = more.map((item) => (
        '<button class="provider-row' + (item.id === provider.value ? ' active' : '') + '" type="button" data-provider="' + item.id + '">' +
        '<strong>' + item.label + '</strong><small>provider</small></button>'
      )).join('');
      const bindProviderButton = (button) => {
        button.addEventListener('click', () => {
          provider.value = button.dataset.provider || 'openrouter';
          if (!featuredProviderIds.includes(provider.value)) showMoreProviders = true;
          renderProviderGrid();
          syncProviderDefaults(true);
        });
      };
      grid.querySelectorAll('.provider').forEach(bindProviderButton);
      moreList.querySelectorAll('.provider-row').forEach(bindProviderButton);
      moreToggle.onclick = () => {
        showMoreProviders = !showMoreProviders;
        renderProviderGrid();
      };
    }
    function renderRouterModes() {
      const selected = currentProvider();
      if ((routerMode.value === 'recommended' && !selected.routerSupported) || routerMode.value === 'openrouter-mix') {
        routerMode.value = defaultModeFor(selected);
      }
      const autoActive = routerMode.value !== 'disabled';
      const autoDisabled = !selected.routerSupported;
      const autoBody = selected.id === 'openrouter'
        ? t.autoBodyOpenrouter
        : fmt('autoBody', { label: selected.label });
      routerModeGrid.className = 'router-choice';
      routerModeGrid.innerHTML =
        '<div class="router-primary">' +
        '<button class="choice' + (autoActive ? ' active' : '') + '" type="button" data-router-primary="auto"' + (autoDisabled ? ' disabled' : '') + '>' +
        '<strong>' + escapeHtml(t.autoTitle) + '</strong><small>' + escapeHtml(autoBody) + '</small></button>' +
        '<button class="choice' + (routerMode.value === 'disabled' ? ' active' : '') + '" type="button" data-router-primary="disabled">' +
        '<strong>' + escapeHtml(t.fixedTitle) + '</strong><small>' + escapeHtml(t.fixedBody) + '</small></button>' +
        '</div>';
      routerModeGrid.querySelectorAll('[data-router-primary]').forEach((button) => {
        button.addEventListener('click', () => {
          routerMode.value = button.dataset.routerPrimary === 'disabled' ? 'disabled' : defaultModeFor(selected);
          routerTiers = clone(routerProfiles[profileKeyForMode()]);
          renderRouterModes();
          renderTiers();
        });
      });
      routerModeGrid.querySelectorAll('.choice').forEach((button) => {
        if (!button.dataset.routerMode) return;
        button.addEventListener('click', () => {
          routerMode.value = button.dataset.routerMode || 'recommended';
          routerTiers = clone(routerProfiles[profileKeyForMode()]);
          renderRouterModes();
          renderTiers();
        });
      });
      routerModeHint.textContent = routerMode.value === 'disabled'
        ? t.routerHintDisabled
        : fmt('routerHintActive', { mode: modeLabel(routerMode.value) });
    }
    function renderTiers() {
      if (routerMode.value === 'disabled') {
        tierBody.innerHTML =
          '<label>' + escapeHtml(t.directModelLabel) + '<input id="directModelActive" autocomplete="off" value="' + escapeAttr(model.value) + '" /></label>' +
          '<div class="note">' + escapeHtml(t.directModelNote) + '</div>';
        document.getElementById('directModelActive').addEventListener('input', (event) => {
          model.value = event.target.value;
        });
        return;
      }
      const defaultTier = document.getElementById('routerDefaultTier')?.value || 't1';
      const tierButtons = textTiers.map((tier) => (
        '<button class="tier-button' + (tier === defaultTier ? ' active' : '') + '" type="button" data-default-tier="' + tier + '">' +
        '<strong>' + tier.toUpperCase() + '</strong><small title="' + escapeAttr(routerTiers[tier]?.model || t.noModel) + '">' + escapeHtml(shortModel(routerTiers[tier]?.model || t.noModel)) + '</small></button>'
      )).join('');
      const names = Object.keys(routerTiers).filter((name) => textTiers.includes(name) || name === 'image_model');
      const tierList = names.map((name) => {
        const tier = routerTiers[name] || {};
        return '<div class="tier-item"><div class="tier-name">' + name + '</div><div class="tier-model"><strong>' + escapeHtml(tier.model || '') + '</strong><small>' + escapeHtml(tier.provider || '') + '</small></div>' +
          (name === defaultTier ? '<span class="pill">' + escapeHtml(t.defaultPill) + '</span>' : '<span></span>') + '</div>';
      }).join('');
      const editor = names.map((name) => {
        const tier = routerTiers[name] || {};
        return '<div class="editor-row"><div class="muted-line">' + name + '</div><div class="field-pair">' +
          '<label>' + escapeHtml(t.providerField) + '<input data-tier-provider="' + name + '" value="' + escapeAttr(tier.provider || '') + '" /></label>' +
          '<label>' + escapeHtml(t.modelField) + '<input data-tier-model="' + name + '" value="' + escapeAttr(tier.model || '') + '" /></label></div></div>';
      }).join('');
      tierBody.innerHTML =
        '<input id="routerDefaultTier" type="hidden" value="' + defaultTier + '" />' +
        '<div class="tier-defaults">' + tierButtons + '</div>' +
        '<div class="tier-list">' + tierList + '</div>' +
        '<details><summary>' + escapeHtml(t.customizeTiers) + '</summary><div class="editor-grid">' + editor + '</div></details>';
      tierBody.querySelectorAll('[data-default-tier]').forEach((button) => {
        button.addEventListener('click', () => {
          document.getElementById('routerDefaultTier').value = button.dataset.defaultTier || 't1';
          renderTiers();
        });
      });
      tierBody.querySelectorAll('[data-tier-provider], [data-tier-model]').forEach((input) => {
        input.addEventListener('input', () => {
          const tierName = input.dataset.tierProvider || input.dataset.tierModel;
          routerTiers[tierName] = routerTiers[tierName] || {};
          if (input.dataset.tierProvider) routerTiers[tierName].provider = input.value.trim();
          if (input.dataset.tierModel) routerTiers[tierName].model = input.value.trim();
        });
      });
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
    }
    function escapeAttr(value) {
      return escapeHtml(value);
    }
    function shortModel(value) {
      const text = String(value || '');
      const parts = text.split('/');
      return parts[parts.length - 1] || text;
    }
    function currentSearchProvider() {
      return searchProviders.find((item) => item.providerId === searchProvider.value) || searchProviders[0];
    }
    function renderSearchProviderGrid() {
      searchProviderGrid.innerHTML = searchProviders.map((item) => (
        '<button class="choice' + (item.providerId === searchProvider.value ? ' active' : '') + '" type="button" data-search-provider="' + escapeAttr(item.providerId) + '">' +
        '<strong>' + escapeHtml(item.label) + '</strong><small>' + escapeHtml(item.note || (item.requiresApiKey ? t.requiresApiKey : t.noKeyRequired)) + '</small></button>'
      )).join('');
      searchProviderGrid.querySelectorAll('[data-search-provider]').forEach((button) => {
        button.addEventListener('click', () => {
          searchProvider.value = button.dataset.searchProvider || 'duckduckgo';
          renderSearchProviderGrid();
          render();
        });
      });
    }
    function syncSearchProviderControls() {
      const selected = currentSearchProvider();
      searchKeyLabel.hidden = !selected.requiresApiKey;
      const input = document.getElementById('searchApiKey');
      if (input) input.placeholder = selected.keyPlaceholder || selected.envKey || 'SEARCH_API_KEY';
      searchHint.textContent = selected.note || (selected.requiresApiKey ? fmt('searchAvailable', { label: selected.label }) : t.searchHintDefault);
    }
    function isSimpleSetup() {
      return setupMode.value === 'simple';
    }
    function routeSteps() {
      return isSimpleSetup() ? [0, 1, 4] : [0, 1, 2, 3, 4];
    }
    function routePosition(targetStep) {
      return routeSteps().indexOf(targetStep);
    }
    function nextRouteStep(currentStep) {
      const route = routeSteps();
      const index = Math.max(0, route.indexOf(currentStep));
      return route[Math.min(route.length - 1, index + 1)];
    }
    function previousRouteStep(currentStep) {
      const route = routeSteps();
      const index = Math.max(0, route.indexOf(currentStep));
      return route[Math.max(0, index - 1)];
    }
    function setStep(nextStep) {
      const current = document.querySelector('.setup-card.active');
      const route = routeSteps();
      step = route.includes(nextStep) ? nextStep : route[0];
      document.querySelectorAll('.setup-card').forEach((screen) => {
        screen.classList.remove('active', 'leaving');
      });
      if (current) current.classList.add('leaving');
      document.querySelector('[data-screen="' + step + '"]').classList.add('active');
      render();
    }
    function render() {
      const route = routeSteps();
      const currentRouteIndex = route.indexOf(step);
      document.querySelectorAll('[data-advanced-step]').forEach((item) => {
        item.classList.toggle('simple-hidden', isSimpleSetup());
      });
      document.querySelectorAll('.step').forEach((item) => {
        const labelStep = Number(item.dataset.stepLabel || 0);
        const itemRouteIndex = route.indexOf(labelStep);
        const index = item.querySelector('.step-index');
        if (index && itemRouteIndex >= 0) index.textContent = String(itemRouteIndex + 1);
        item.classList.toggle('active', labelStep === step);
        item.classList.toggle('done', itemRouteIndex >= 0 && itemRouteIndex < currentRouteIndex);
      });
      document.querySelectorAll('.setup-card').forEach((screen) => {
        const screenStep = Number(screen.dataset.screen || 0);
        const screenRouteIndex = route.indexOf(screenStep);
        const eyebrow = screen.querySelector('.eyebrow');
        if (eyebrow && screenRouteIndex >= 0) {
          eyebrow.textContent = fmt('stepLabel', { n: String(screenRouteIndex + 1).padStart(2, '0') });
        }
      });
      if (step === 1) {
        syncProviderDefaults(false);
      }
      if (step === 2) renderRouterModes();
      if (step === 3) renderTiers();
      syncSearchProviderControls();
    }
    document.querySelectorAll('.step').forEach((button) => {
      button.addEventListener('click', () => {
        const target = Number(button.dataset.stepLabel || 0);
        const currentPosition = routePosition(step);
        const targetPosition = routePosition(target);
        if (targetPosition < 0) return;
        if (targetPosition > currentPosition) {
          const message = validateStep();
          if (message) {
            errorBox.textContent = message;
            return;
          }
        }
        errorBox.textContent = '';
        setStep(target);
      });
    });
    document.querySelectorAll('[data-setup-mode]').forEach((button) => {
      button.addEventListener('click', () => {
        setupMode.value = button.dataset.setupMode || 'simple';
        document.querySelectorAll('[data-setup-mode]').forEach((item) => item.classList.toggle('active', item === button));
        errorBox.textContent = '';
        render();
      });
    });
    function validateStep() {
      const selected = currentProvider();
      const selectedSearch = currentSearchProvider();
      if (step === 1 && selected.requiresApiKey && !document.getElementById('apiKey').value.trim()) return fmt('apiKeyRequired', { label: selected.label });
      if (step === 3 && routerMode.value === 'disabled' && !model.value.trim()) return t.directModelRequiredDisabled;
      if (step === 3 && routerMode.value !== 'disabled') {
        const defaultTier = document.getElementById('routerDefaultTier')?.value || 't1';
        if (!routerTiers[defaultTier] || !routerTiers[defaultTier].model) return t.defaultTierRequiresModel;
      }
      if (step === 4 && selectedSearch.requiresApiKey && !document.getElementById('searchApiKey').value.trim()) return fmt('searchApiKeyRequired', { label: selectedSearch.label });
      return '';
    }
    document.getElementById('cancel').addEventListener('click', () => {
      window.opensquillaDesktop.cancelOnboarding();
    });
    document.querySelectorAll('.back-button').forEach((button) => button.addEventListener('click', () => {
      errorBox.textContent = '';
      setStep(previousRouteStep(step));
    }));
    document.querySelectorAll('.next-button').forEach((button) => button.addEventListener('click', () => {
      errorBox.textContent = '';
      const message = validateStep();
      if (message) {
        errorBox.textContent = message;
        return;
      }
      setStep(nextRouteStep(step));
    }));
    finish.addEventListener('click', async () => {
      errorBox.textContent = '';
      for (const index of routeSteps()) {
        step = index;
        const message = validateStep();
        if (message) {
          setStep(index);
          errorBox.textContent = message;
          return;
        }
      }
      try {
        await window.opensquillaDesktop.saveOnboarding({
          provider: provider.value,
          apiKey: document.getElementById('apiKey').value,
          baseUrl: baseUrl.value,
          model: model.value,
          routerMode: routerMode.value,
          routerDefaultTier: document.getElementById('routerDefaultTier')?.value || 't1',
          routerTiers,
          searchProvider: searchProvider.value,
          searchApiKey: document.getElementById('searchApiKey').value,
        });
      } catch (error) {
        errorBox.textContent = error && error.message ? error.message : String(error);
      }
    });
    renderProviderGrid();
    renderSearchProviderGrid();
    syncProviderDefaults(true);
    render();
  </script>
</body>
</html>`
}

async function runOnboarding(): Promise<DesktopConnection> {
  const existing = await loadDesktopCredential()
  if (existing && isConnectionReady(existing)) {
    // Seed the gateway config from the saved credential only when it does not
    // exist yet. Once it exists the Control UI owns it via RPC, so regenerating
    // it from the credential template here would clobber provider/router/channel
    // edits made live in Settings on every boot.
    if (!(await pathExists(desktopConfigPath()))) {
      await writeDesktopConfig(existing)
    }
    return existing
  }

  return new Promise((resolveCredential, rejectCredential) => {
    resolveOnboarding = resolveCredential
    rejectOnboarding = rejectCredential
    const parentWindow = currentMainWindow()
    onboardingWindow = new BrowserWindow({
      width: 1040,
      height: 820,
      minWidth: 900,
      minHeight: 720,
      title: desktopT('window.onboarding'),
      icon: appIconPath(),
      resizable: true,
      parent: parentWindow ?? undefined,
      modal: Boolean(parentWindow),
      show: false,
      // Match the onboarding page's base so the first frame is not white.
      backgroundColor: '#f5f2eb',
      webPreferences: {
        preload: join(__dirname, 'preload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    })
    installEditingContextMenu(onboardingWindow)

    onboardingWindow.once('ready-to-show', () => {
      if (!onboardingWindow || onboardingWindow.isDestroyed()) return
      onboardingWindow.show()
      onboardingWindow?.focus()
    })
    onboardingWindow.on('closed', () => {
      onboardingWindow = null
      if (rejectOnboarding) {
        const reject = rejectOnboarding
        resolveOnboarding = null
        rejectOnboarding = null
        reject(new Error('OpenSquilla setup was closed.'))
      }
    })

    onboardingWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(onboardingHtml())}`).catch((error) => {
      rejectCredential(error instanceof Error ? error : new Error(String(error)))
    })
  })
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path, constants.F_OK)
    return true
  } catch {
    return false
  }
}

async function pathIsFile(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isFile()
  } catch {
    return false
  }
}

async function assertRepoRoot(): Promise<void> {
  const pyprojectPath = join(repoRoot, 'pyproject.toml')
  const webuiPath = join(repoRoot, 'src', 'opensquilla', 'gateway', 'static', 'dist', 'index.html')
  if (!(await pathExists(pyprojectPath))) {
    throw new Error(`OpenSquilla checkout not found at ${repoRoot}`)
  }
  if (!(await pathExists(webuiPath))) {
    throw new Error(
      `Built Control UI not found at ${webuiPath}. Run "cd opensquilla-webui && npm run build" first.`
    )
  }
}

function packagedRuntimeRoot(): string {
  if (app.isPackaged) return join(process.resourcesPath, 'runtime')
  return join(packageRoot, 'runtime')
}

function pathDelimiter(): string {
  return process.platform === 'win32' ? ';' : ':'
}

function splitPathValue(value?: string): string[] {
  return (value || '').split(pathDelimiter()).filter(Boolean)
}

function desktopNodeBinCandidates(): string[] {
  const candidates = process.platform === 'win32'
    ? [
        join(packagedRuntimeRoot(), 'node'),
        process.env.LOCALAPPDATA ? join(process.env.LOCALAPPDATA, 'Programs', 'nodejs') : '',
        process.env.ProgramFiles ? join(process.env.ProgramFiles, 'nodejs') : '',
        process.env['ProgramFiles(x86)'] ? join(process.env['ProgramFiles(x86)'], 'nodejs') : '',
      ]
    : [
        join(packagedRuntimeRoot(), 'node', 'bin'),
        join(app.getPath('home'), '.local', 'bin'),
        join(app.getPath('home'), '.npm-global', 'bin'),
        '/opt/homebrew/bin',
        '/usr/local/bin',
      ]
  const seen = new Set<string>()
  return candidates.filter((candidate) => {
    if (!candidate || seen.has(candidate) || !existsSync(candidate)) return false
    seen.add(candidate)
    return true
  })
}

function desktopChildPath(nodeBinCandidates = desktopNodeBinCandidates()): string {
  const currentPath = process.env.PATH || process.env.Path || ''
  const currentParts = splitPathValue(currentPath)
  const systemParts = process.platform === 'win32' ? [] : ['/usr/bin', '/bin', '/usr/sbin', '/sbin']
  const orderedParts = [...nodeBinCandidates, ...currentParts, ...systemParts]
  const seen = new Set<string>()
  const merged = orderedParts.filter((part) => {
    if (!part || seen.has(part)) return false
    seen.add(part)
    return true
  })
  return merged.join(pathDelimiter())
}

async function resolveGatewayRuntime(): Promise<RuntimeLaunch> {
  const binaryName = process.platform === 'win32' ? 'opensquilla-gateway.exe' : 'opensquilla-gateway'
  const runtimeRoot = join(packagedRuntimeRoot(), 'gateway')
  const onedirBinary = join(runtimeRoot, 'opensquilla-gateway', binaryName)
  const flatBinary = join(runtimeRoot, binaryName)
  const bundledBinary = (await pathIsFile(onedirBinary)) ? onedirBinary : flatBinary
  if (await pathIsFile(bundledBinary)) {
    return {
      command: bundledBinary,
      args: ['gateway', 'run'],
      cwd: dirname(bundledBinary),
      mode: 'bundled',
    }
  }

  await assertRepoRoot()
  return {
    command: 'uv',
    args: ['run', 'opensquilla', 'gateway', 'run'],
    cwd: repoRoot,
    mode: 'dev',
  }
}

function isPortOpen(port: number): Promise<boolean> {
  return new Promise((resolveOpen) => {
    const socket = net.createConnection({ host: '127.0.0.1', port })
    socket.setTimeout(350)
    socket.on('connect', () => {
      socket.destroy()
      resolveOpen(true)
    })
    socket.on('timeout', () => {
      socket.destroy()
      resolveOpen(false)
    })
    socket.on('error', () => resolveOpen(false))
  })
}

async function findGatewayPort(): Promise<number> {
  const envPort = Number(process.env.OPENSQUILLA_DESKTOP_GATEWAY_PORT || '')
  if (Number.isInteger(envPort) && envPort > 0) return envPort

  for (let port = 18791; port <= 18830; port += 1) {
    if (!(await isPortOpen(port))) return port
  }
  throw new Error('No free OpenSquilla desktop gateway port found in 18791-18830.')
}

async function healthCheck(url: string): Promise<boolean> {
  try {
    const response = await fetch(`${url}/healthz`, { signal: AbortSignal.timeout(1000) })
    if (!response.ok) return false
    const payload = await response.json().catch(() => null)
    return Boolean(payload && payload.ok === true)
  } catch {
    return false
  }
}

async function waitForGateway(url: string): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < 45_000) {
    if (await healthCheck(url)) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  throw new Error(`Gateway did not become healthy at ${url}`)
}

async function waitForControlUi(url: string): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < 45_000) {
    try {
      const response = await fetch(`${url}/control/`, { signal: AbortSignal.timeout(1500) })
      if (response.ok) return
    } catch {
      // The ASGI socket can become healthy just before static routes are ready.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  throw new Error(`Control UI did not become reachable at ${url}/control/`)
}

function hasGatewayProcessExited(process: ChildProcessWithoutNullStreams | null): boolean {
  return Boolean(process && (process.exitCode !== null || process.signalCode !== null))
}

async function reuseHealthyGatewayState(): Promise<GatewayState | null> {
  if (!gatewayState.url) return null
  if (gatewayState.status !== 'ready' && !gatewayProcess) return null

  if (await healthCheck(gatewayState.url)) {
    gatewayState.status = 'ready'
    gatewayState.error = undefined
    sendBootStatus('control')
    return gatewayState
  }

  if (gatewayProcess && gatewayState.owned && hasGatewayProcessExited(gatewayProcess)) {
    gatewayProcess = null
    gatewayState.status = 'stopped'
  }
  return null
}

async function startGateway(): Promise<GatewayState> {
  const reusableGateway = await reuseHealthyGatewayState()
  if (reusableGateway) return reusableGateway

  if (gatewayProcess && gatewayState.owned) {
    if (hasGatewayProcessExited(gatewayProcess)) {
      gatewayProcess = null
    } else {
      stopGateway()
    }
    gatewayState.status = 'stopped'
    gatewayState.error = undefined
  }

  const overrideUrl = process.env.OPENSQUILLA_DESKTOP_GATEWAY_URL
  const explicitPort = process.env.OPENSQUILLA_DESKTOP_GATEWAY_PORT
  if (overrideUrl) {
    sendBootStatus('gateway-health')
    gatewayState.url = overrideUrl.replace(/\/$/, '')
    gatewayState.port = Number(new URL(gatewayState.url).port || 0)
    gatewayState.owned = false
    gatewayState.status = (await healthCheck(gatewayState.url)) ? 'ready' : 'error'
    if (gatewayState.status !== 'ready') {
      throw new Error(`Configured gateway is not healthy: ${gatewayState.url}`)
    }
    return gatewayState
  }

  if (!app.isPackaged && !explicitPort && await healthCheck('http://127.0.0.1:18791')) {
    sendBootStatus('control')
    gatewayState.url = 'http://127.0.0.1:18791'
    gatewayState.port = 18791
    gatewayState.owned = false
    gatewayState.status = 'ready'
    return gatewayState
  }

  sendBootStatus('profile')
  const connection = await runOnboarding()
  const apiKey = decryptApiKey(connection)
  if (!apiKey) throw new Error('Saved desktop API key could not be read.')
  const searchApiKey = decryptSearchApiKey(connection)
  // Config is seeded (when missing) inside runOnboarding / the onboarding save,
  // and is otherwise the RPC-owned source of truth — so it is intentionally NOT
  // regenerated here on every boot.

  sendBootStatus('gateway-start')
  const runtime = await resolveGatewayRuntime()

  const port = await findGatewayPort()
  const url = `http://127.0.0.1:${port}`
  const logDir = join(app.getPath('userData'), 'logs')
  mkdirSync(logDir, { recursive: true })
  const logPath = join(logDir, 'gateway.log')
  const logStream = createWriteStream(logPath, { flags: 'a' })

  gatewayState.url = url
  gatewayState.port = port
  gatewayState.owned = true
  gatewayState.status = 'starting'
  gatewayState.logPath = logPath

  const nodeBinCandidates = desktopNodeBinCandidates()
  const childPath = desktopChildPath(nodeBinCandidates)
  const childEnv = {
    ...process.env,
    PATH: childPath,
    ...(process.platform === 'win32' ? { Path: childPath } : {}),
    [connection.apiKeyEnv]: apiKey,
    ...(connection.searchApiKeyEnv && searchApiKey ? { [connection.searchApiKeyEnv]: searchApiKey } : {}),
    OPENSQUILLA_DESKTOP: '1',
    OPENSQUILLA_INSTALL_METHOD: 'desktop',
    OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
    OPENSQUILLA_NODE_BIN_DIR: nodeBinCandidates.join(pathDelimiter()),
    OPENSQUILLA_STATE_DIR: desktopStateDir(),
    PYTHONUNBUFFERED: '1',
  }

  const child = spawn(
    runtime.command,
    [...runtime.args, '--port', String(port), '--bind', '127.0.0.1', '--config', desktopConfigPath()],
    {
      cwd: runtime.cwd,
      env: childEnv,
    }
  )
  gatewayProcess = child

  child.stdout.pipe(logStream, { end: false })
  child.stderr.pipe(logStream, { end: false })
  child.once('exit', (code, signal) => {
    const message = `gateway exited code=${code ?? 'null'} signal=${signal ?? 'null'}`
    const isCurrentGateway = gatewayProcess === child
    if (isCurrentGateway) gatewayProcess = null
    logStream.write(`\n[desktop] ${message}\n`)
    if (!isCurrentGateway) return
    if (isQuitting) {
      gatewayState.status = 'stopped'
      return
    }
    gatewayState.status = 'error'
    gatewayState.error = message
    sendBootError(gatewayState.error)
  })

  sendBootStatus('gateway-health')
  await waitForGateway(url)
  await waitForControlUi(url)
  sendBootStatus('control')
  gatewayState.status = 'ready'
  return gatewayState
}

async function loadControlUi(window: BrowserWindow, gatewayUrl: string): Promise<void> {
  const url = `${gatewayUrl}/control/`
  let lastError: Error | null = null
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    try {
      await window.loadURL(url)
      return
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      await new Promise((resolveWait) => setTimeout(resolveWait, 500))
    }
  }
  throw lastError ?? new Error(`Failed to load ${url}`)
}

function isCurrentWindowAtControlUi(window: BrowserWindow, gatewayUrl: string): boolean {
  const currentUrl = window.webContents.getURL()
  if (!currentUrl) return false

  try {
    const current = new URL(currentUrl)
    const gateway = new URL(gatewayUrl)
    return (
      current.origin === gateway.origin
      && (current.pathname === '/control' || current.pathname.startsWith('/control/'))
    )
  } catch {
    return false
  }
}

async function createMainWindow(): Promise<BrowserWindow> {
  if (mainWindow && !mainWindow.isDestroyed()) return mainWindow

  const window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: 'OpenSquilla',
    icon: appIconPath(),
    show: false,
    // Paint the window in the app's base color from the first frame so launch
    // never flashes white before the splash/app paints. The app theme defaults
    // to 'system', so match the OS; these are the base.css --bg tokens.
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#08080A' : '#F7F6F3',
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow = window
  installEditingContextMenu(window)

  window.webContents.setWindowOpenHandler(({ url }) => {
    // Forward real outbound links to the system browser; deny everything else.
    // Empty/blob/data popups (e.g. the web "open in new tab" artifact pattern)
    // must NOT reach shell.openExternal — they would be no-ops, and the renderer
    // opens artifacts through the desktop:artifact:open IPC instead.
    if (/^https?:\/\//i.test(url) || url.startsWith('mailto:')) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  window.once('ready-to-show', () => {
    if (!window.isDestroyed()) window.show()
  })

  window.once('closed', () => {
    if (mainWindow === window) mainWindow = null
  })

  await window.loadFile(bootPagePath())
  return window
}

function currentMainWindow(): BrowserWindow | null {
  return mainWindow && !mainWindow.isDestroyed() ? mainWindow : null
}

function ensureGatewayStarted(): Promise<GatewayState> {
  if (!gatewayStartPromise) {
    sendBootStatus('profile')
    gatewayStartPromise = startGateway().finally(() => {
      gatewayStartPromise = null
    })
  }
  return gatewayStartPromise
}

async function loadControlUiIntoCurrentWindow(gatewayUrl: string): Promise<void> {
  const window = currentMainWindow()
  if (!window) return

  sendBootStatus('control')
  if (isCurrentWindowAtControlUi(window, gatewayUrl)) {
    sendBootStatus('ready')
    return
  }

  try {
    await loadControlUi(window, gatewayUrl)
  } catch (error) {
    if (window.isDestroyed()) return
    throw error
  }
  sendBootStatus('ready')
}

async function openOrResumeDesktopApp(): Promise<void> {
  await createMainWindow()
  focusMainWindow()

  try {
    const reusableGateway = await reuseHealthyGatewayState()
    const gateway = reusableGateway ?? await ensureGatewayStarted()
    await loadControlUiIntoCurrentWindow(gateway.url)
  } catch (error) {
    if (gatewayState.status !== 'ready') {
      gatewayState.status = 'error'
      gatewayState.error = error instanceof Error ? error.message : String(error)
    }
    if (currentMainWindow()) sendBootError(error)
  }
}

// SIGKILL deadline for the owned gateway child. The Python gateway drains
// in-flight agent turns and background completions on shutdown (up to two
// graceful phases plus teardown — see gateway_shutdown_deadline()), so the
// force-kill must exceed that worst case or the drain is cut off mid-write.
// Keep in sync with the default OPENSQUILLA_GATEWAY_GRACEFUL_TIMEOUT (30s).
const GATEWAY_SHUTDOWN_KILL_AFTER_MS = 75_000
// Short SIGKILL backstop after a hard terminate (TerminateProcess / SIGTERM)
// when the graceful path was skipped or already overran its deadline.
const GATEWAY_HARD_KILL_BACKSTOP_MS = 5_000

// Ask the gateway to shut down gracefully over its owner-only HTTP endpoint,
// which runs the full GatewayServer.close() drain before exiting. The desktop
// child is loopback (no-auth owner), so no token is needed. Best-effort:
// returns false if the gateway is unreachable or rejects the request.
async function requestGatewayShutdown(url: string): Promise<boolean> {
  if (!url) return false
  try {
    const response = await fetch(`${url}/api/system/shutdown`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(2000),
    })
    return response.ok
  } catch {
    return false
  }
}

function stopGateway(): void {
  if (!gatewayProcess || !gatewayState.owned) return
  const child = gatewayProcess
  const url = gatewayState.url
  gatewayProcess = null

  const hardTerminate = () => {
    if (child.killed) return
    child.kill('SIGTERM')
    setTimeout(() => {
      if (!child.killed) child.kill('SIGKILL')
    }, GATEWAY_HARD_KILL_BACKSTOP_MS).unref()
  }

  // The Windows HTTP graceful path is async (fetch + timers) and only works
  // while the main process stays alive to drive it. On app quit (isQuitting) the
  // process is about to exit, so that fire-and-forget work would race teardown
  // and orphan the child — leaving it holding the listen port + PID lock and
  // breaking the next launch. So only take the graceful path when NOT quitting;
  // on quit, fall through to a synchronous TerminateProcess.
  if (process.platform === 'win32' && !isQuitting) {
    // Windows has no real SIGTERM — child.kill('SIGTERM') maps to an immediate
    // TerminateProcess that skips the drain. Trigger the HTTP graceful path,
    // wait for the child to exit on its own, and only force-terminate if it
    // overruns the deadline or the gateway never accepted the request.
    let exited = false
    child.once('exit', () => {
      exited = true
    })
    void requestGatewayShutdown(url).then((accepted) => {
      if (!accepted && !exited) hardTerminate()
    })
    setTimeout(() => {
      if (!exited) hardTerminate()
    }, GATEWAY_SHUTDOWN_KILL_AFTER_MS).unref()
    return
  }

  // POSIX: SIGTERM triggers the gateway's graceful drain directly (the detached
  // child drains and exits on its own after the main process is gone).
  // Windows-on-quit: SIGTERM maps to a synchronous TerminateProcess, killing the
  // child before the main process exits — no drain, but no orphan either.
  child.kill('SIGTERM')
  setTimeout(() => {
    if (!child.killed) child.kill('SIGKILL')
  }, GATEWAY_SHUTDOWN_KILL_AFTER_MS).unref()
}

// ── Auto-update (electron-updater) ──────────────────────────────────────────
// Phase 1 scope is macOS only. macOS release builds are Developer-ID signed +
// notarized and ship the zip + latest-mac.yml feed that Squirrel.Mac consumes,
// so in-place auto-update is safe. Windows builds are currently UNSIGNED, which
// would make silent NSIS updates trip SmartScreen/UAC — so Windows stays on the
// manual-download path (the in-app web notice) until a code-signing certificate
// is in place. OPENSQUILLA_DESKTOP_ENABLE_WIN_UPDATE=1 opts in for local testing
// only; OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE=1 turns the feature off entirely.
const { autoUpdater } = electronUpdater

let autoUpdaterReady = false
let manualUpdateCheck = false
let updateDownloadInProgress = false
let updateApplying = false

function autoUpdateSupported(): boolean {
  if (!app.isPackaged) return false
  if (process.env.OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE === '1') return false
  if (process.platform === 'darwin') return true
  if (process.platform === 'win32' && process.env.OPENSQUILLA_DESKTOP_ENABLE_WIN_UPDATE === '1') {
    return true
  }
  return false
}

function nativeAutoUpdateEnabled(): boolean {
  return autoUpdateSupported() && macUpdateLocationOk()
}

// macOS Squirrel cannot swap an app that runs from a read-only/translocated
// location (a mounted DMG, ~/Downloads). The app must live in /Applications.
function macUpdateLocationOk(): boolean {
  if (process.platform !== 'darwin') return true
  try {
    return app.isInApplicationsFolder()
  } catch {
    return true
  }
}

function desktopTv(key: string, version: string): string {
  return desktopT(key).replace('{version}', version)
}

function showUpdateDialog(
  options: Electron.MessageBoxOptions,
): Promise<Electron.MessageBoxReturnValue> {
  const win = currentMainWindow()
  return win ? dialog.showMessageBox(win, options) : dialog.showMessageBox(options)
}

function showUpdateError(err: unknown): void {
  const shouldReport = manualUpdateCheck || updateDownloadInProgress
  manualUpdateCheck = false
  updateDownloadInProgress = false
  if (!shouldReport) return
  void showUpdateDialog({
    type: 'error',
    buttons: ['OK'],
    title: desktopT('update.errorTitle'),
    message: desktopT('update.errorTitle'),
    detail: String(err instanceof Error ? err.message : err ?? ''),
  })
}

function initAutoUpdater(): void {
  if (autoUpdaterReady || !autoUpdateSupported()) return
  autoUpdaterReady = true

  // Consent-based: the bundled gateway + ML runtime make updates large, so we
  // never download without asking. We also keep installation on the explicit
  // restart path so applyDownloadedUpdate() can drain the owned gateway first.
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
  autoUpdater.logger = {
    info: (m: unknown) => console.log('[updater]', m),
    warn: (m: unknown) => console.warn('[updater]', m),
    error: (m: unknown) => console.error('[updater]', m),
    debug: () => {},
  }

  autoUpdater.on('update-available', (info) => {
    const version = String(info?.version ?? '')
    void showUpdateDialog({
      type: 'info',
      buttons: [desktopT('update.download'), desktopT('update.later')],
      defaultId: 0,
      cancelId: 1,
      title: desktopT('update.newVersionTitle'),
      message: desktopT('update.newVersionTitle'),
      detail: desktopTv('update.newVersionDetail', version),
    }).then(({ response }) => {
      if (response !== 0) {
        manualUpdateCheck = false
        return
      }
      updateDownloadInProgress = true
      autoUpdater.downloadUpdate().catch((err) => {
        console.error('[updater] download failed', err)
        showUpdateError(err)
      })
    })
  })

  autoUpdater.on('update-not-available', () => {
    updateDownloadInProgress = false
    if (!manualUpdateCheck) return
    manualUpdateCheck = false
    void showUpdateDialog({
      type: 'info',
      buttons: ['OK'],
      title: desktopT('update.upToDateTitle'),
      message: desktopT('update.upToDateTitle'),
      detail: desktopTv('update.upToDateDetail', app.getVersion()),
    })
  })

  autoUpdater.on('update-downloaded', (info) => {
    manualUpdateCheck = false
    updateDownloadInProgress = false
    const version = String(info?.version ?? '')
    void showUpdateDialog({
      type: 'info',
      buttons: [desktopT('update.restartNow'), desktopT('update.later')],
      defaultId: 0,
      cancelId: 1,
      title: desktopT('update.readyTitle'),
      message: desktopT('update.readyTitle'),
      detail: desktopTv('update.readyDetail', version),
    }).then(({ response }) => {
      if (response === 0) void applyDownloadedUpdate()
    })
  })

  autoUpdater.on('error', (err) => {
    console.error('[updater] error', err)
    showUpdateError(err)
  })
}

async function checkForUpdates(manual: boolean): Promise<void> {
  if (!autoUpdateSupported()) return

  // Guide the user to /Applications first, otherwise the in-place swap fails.
  if (!macUpdateLocationOk()) {
    if (manual) {
      void showUpdateDialog({
        type: 'warning',
        buttons: ['OK'],
        title: desktopT('update.errorTitle'),
        message: desktopT('update.errorTitle'),
        detail: desktopT('update.moveToApplications'),
      })
    }
    return
  }

  initAutoUpdater()
  manualUpdateCheck = manual
  try {
    await autoUpdater.checkForUpdates()
  } catch (err) {
    console.error('[updater] checkForUpdates failed', err)
    showUpdateError(err)
  }
}

// Stop the owned gateway child and WAIT for it to exit before handing control to
// the installer. The gateway holds the listen port + a PID lock and (on Windows)
// open file handles under resources/runtime that the installer must overwrite —
// orphaning it breaks the next launch. Mirrors the uninstall quiesce path.
async function applyDownloadedUpdate(): Promise<void> {
  if (updateApplying) return
  updateApplying = true
  isQuitting = true
  if (gatewayProcess && gatewayState.owned) {
    const child = gatewayProcess
    stopGateway()
    await new Promise<void>((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve()
      child.once('exit', () => resolve())
      setTimeout(resolve, GATEWAY_SHUTDOWN_KILL_AFTER_MS).unref()
    })
  }
  // isSilent=false (show the platform installer UI where applicable),
  // isForceRunAfter=true (relaunch after install).
  autoUpdater.quitAndInstall(false, true)
}

// Lets the gateway-served Control UI know whether THIS desktop runtime can
// apply updates natively right now. The web "a newer version is available"
// banner suppresses itself only when this is true, so unsupported platforms
// (e.g. unsigned Windows, or macOS running outside /Applications) still show
// the passive notice.
ipcMain.handle('desktop:update:supported', () => nativeAutoUpdateEnabled())
ipcMain.handle('desktop:os-locale', () => desktopLocale)
ipcMain.handle('gateway:status', () => ({ ...gatewayState }))
ipcMain.handle('gateway:reveal-log', async () => {
  if (!gatewayState.logPath) return false
  await shell.showItemInFolder(gatewayState.logPath)
  return true
})
ipcMain.handle('desktop:settings:get', async () => loadDesktopSettings())
ipcMain.handle('desktop:settings:save', async (_event, payload: DesktopSettingsPayload) => saveDesktopSettings(payload))
ipcMain.handle('desktop:settings:reset', async () => {
  await resetDesktopSettings()
  return { ok: true }
})
ipcMain.handle('desktop:artifact:open', async (_event, payload: ArtifactOpenRequest) => openArtifactWithDefaultApp(payload))

// ── Desktop data cleanup ───────────────────────────────────────────────────
// The data deletion logic lives in the Python core (`opensquilla uninstall`);
// the desktop only triggers it via the bundled CLI and then removes the few
// desktop-owned files that live outside the OpenSquilla home (the encrypted
// credential and gateway logs under userData/). It intentionally does not
// remove the installed .app / NSIS application; users do that through the OS.
//
// Path note: the gateway runs with OPENSQUILLA_STATE_DIR=desktopStateDir()
// (<userData>/opensquilla/state), but the uninstaller's "home" must be
// desktopHome() (<userData>/opensquilla) so it resolves config.toml + state/
// correctly. So we run the CLI with OPENSQUILLA_STATE_DIR=desktopHome().
async function runUninstallCli(
  extraArgs: string[],
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const runtime = await resolveGatewayRuntime()
  const prefix = runtime.args.slice(0, -2) // drop the trailing ['gateway','run']
  const child = spawn(runtime.command, [...prefix, 'uninstall', ...extraArgs], {
    cwd: runtime.cwd,
    env: {
      ...process.env,
      OPENSQUILLA_DESKTOP: '1',
      OPENSQUILLA_INSTALL_METHOD: 'desktop',
      OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
      OPENSQUILLA_STATE_DIR: desktopHome(),
    },
  })
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', (chunk) => {
    stdout += String(chunk)
  })
  child.stderr.on('data', (chunk) => {
    stderr += String(chunk)
  })
  const code: number = await new Promise((res) => {
    child.once('exit', (c) => res(c ?? 1))
    child.once('error', () => res(1))
  })
  return { ok: code === 0, stdout, stderr }
}

ipcMain.handle('desktop:uninstall:summary', async () => {
  const { ok, stdout } = await runUninstallCli(['--dry-run', '--json'])
  try {
    return { ok, plan: JSON.parse(stdout) }
  } catch {
    return { ok: false, plan: null, raw: stdout }
  }
})

ipcMain.handle('desktop:uninstall:run', async (_event, payload?: { purgeData?: boolean }) => {
  const purgeData = Boolean(payload?.purgeData)

  // A total wipe is irreversible: confirm at the main-process trust boundary
  // (a renderer-forged IPC call alone must not be able to delete all data).
  if (purgeData) {
    const { response } = await dialog.showMessageBox({
      type: 'warning',
      buttons: ['Cancel', 'Delete everything'],
      defaultId: 0,
      cancelId: 0,
      title: 'Delete local OpenSquilla desktop data?',
      message: 'This permanently deletes the local desktop profile on this machine.',
      detail: 'Sessions, configuration, and secrets will be removed. The installed app itself will remain; remove it through your OS after the app closes.',
    })
    if (response !== 1) return { ok: false, aborted: true, detail: 'cancelled' }
  }

  // Quiesce the owned gateway before the CLI touches files. Wait for the child to
  // actually EXIT (child.killed flips true the instant SIGTERM is sent, not when
  // the drain finishes), bounded by the kill deadline.
  isQuitting = true
  if (gatewayProcess && gatewayState.owned) {
    const child = gatewayProcess
    stopGateway()
    await new Promise<void>((res) => {
      if (child.exitCode !== null || child.signalCode !== null) return res()
      child.once('exit', () => res())
      setTimeout(res, GATEWAY_SHUTDOWN_KILL_AFTER_MS).unref()
    })
  }

  // Refuse to purge while a gateway still serves this profile (covers an
  // unmanaged/adopted gateway the desktop did not spawn). The app keeps running,
  // so clear isQuitting to restore normal gateway-crash reporting.
  if (purgeData && gatewayState.url && (await healthCheck(gatewayState.url))) {
    isQuitting = false
    return {
      ok: false,
      aborted: true,
      detail: 'A gateway is still serving this profile; stop it and retry.',
    }
  }

  const args = ['--yes', '--json']
  if (purgeData) args.push('--purge-all', '--confirm-purge-all', 'delete everything')
  const result = await runUninstallCli(args)

  // The CLI exited non-zero (e.g. quiesce refused, or a delete failed). The app
  // is still running, so restore normal crash reporting and surface the reason.
  if (!result.ok) {
    isQuitting = false
    return { ok: false, detail: (result.stderr || result.stdout || '').slice(-2000) }
  }

  // Remove desktop-owned files outside the OpenSquilla home (only on a full data
  // purge — these hold the encrypted credential and logs).
  if (purgeData) {
    await rm(credentialPath(), { force: true }).catch(() => null)
    await rm(join(app.getPath('userData'), 'logs'), { recursive: true, force: true }).catch(() => null)
  }
  return result
})
ipcMain.handle('desktop:boot:state', () => ({
  status: bootStatus,
  error: bootError,
  gateway: { ...gatewayState },
}))
ipcMain.handle('desktop:boot:retry', async () => {
  const ready = gatewayState.status === 'ready' && gatewayState.url
    ? await healthCheck(gatewayState.url)
    : false

  if (!gatewayStartPromise && !ready && gatewayProcess && gatewayState.owned) {
    stopGateway()
  }
  if (!ready) {
    gatewayState.status = 'stopped'
    gatewayState.error = undefined
    await currentMainWindow()?.loadFile(bootPagePath()).catch(() => null)
  }

  void openOrResumeDesktopApp()
  return { ok: true }
})
ipcMain.handle('desktop:boot:quit', () => {
  app.quit()
  return { ok: true }
})
ipcMain.handle('desktop:onboarding:defaults', () => ({
  providers: PROVIDER_CATALOG,
  searchProviders: SEARCH_PROVIDER_CATALOG,
  router: {
    modes: ['recommended', 'openrouter-mix', 'disabled'],
    defaultTier: 't1',
    textTiers: TEXT_ROUTER_TIERS,
    profiles: ROUTER_PROFILES,
  },
}))
ipcMain.handle('desktop:onboarding:save', async (_event, payload: OnboardingPayload) => {
  const credential = await saveDesktopCredential(payload)
  const resolve = resolveOnboarding
  resolveOnboarding = null
  rejectOnboarding = null
  onboardingWindow?.close()
  resolve?.(credential)
  return { ok: true }
})
ipcMain.handle('desktop:onboarding:cancel', () => {
  const reject = rejectOnboarding
  resolveOnboarding = null
  rejectOnboarding = null
  onboardingWindow?.close()
  reject?.(new Error('OpenSquilla setup was cancelled.'))
  return { ok: true }
})

app.on('before-quit', () => {
  isQuitting = true
  stopGateway()
})

function shutdownFromSignal(): void {
  isQuitting = true
  stopGateway()
  app.quit()
}

process.once('SIGINT', shutdownFromSignal)
process.once('SIGTERM', shutdownFromSignal)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  void openOrResumeDesktopApp()
})

configureChromiumKeychainPolicy()

const gotSingleInstanceLock = app.requestSingleInstanceLock()

if (!gotSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    void openOrResumeDesktopApp()
  })

  void app.whenReady().then(async () => {
    app.name = 'OpenSquilla'
    desktopLocale = resolveDesktopLocale()
    createApplicationMenu()
    void openOrResumeDesktopApp()
    initAutoUpdater()
    if (autoUpdateSupported()) {
      // Delay the silent startup check so it doesn't compete with gateway boot.
      setTimeout(() => {
        void checkForUpdates(false)
      }, 12_000).unref()
    }
  })
}
