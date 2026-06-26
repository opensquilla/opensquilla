import { app, BrowserWindow, Menu, ipcMain, nativeTheme, safeStorage, shell } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createWriteStream, mkdirSync } from 'node:fs'
import { access, constants, readFile, rm, stat, writeFile } from 'node:fs/promises'
import net from 'node:net'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

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
  gateway: GatewayState
}

interface RuntimeLaunch {
  command: string
  args: string[]
  cwd: string
  mode: 'bundled' | 'dev'
}

interface BootStatus {
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
let startupInProgress = false
let resolveOnboarding: ((credential: DesktopConnection) => void) | null = null
let rejectOnboarding: ((error: Error) => void) | null = null
let bootStatus: BootStatus = {
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

function sendBootStatus(label: string): void {
  bootStatus = { label, at: new Date().toISOString() }
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
  const value = String(raw || '').trim().toLowerCase()
  return PROVIDER_BY_ID.has(value) ? value : 'openrouter'
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

function encryptSecret(secret: string): { value: string; encryption: SecretEncryption } {
  if (safeStorage.isEncryptionAvailable()) {
    return {
      value: safeStorage.encryptString(secret).toString('base64'),
      encryption: 'safeStorage',
    }
  }
  return {
    value: Buffer.from(secret, 'utf8').toString('base64'),
    encryption: 'plain',
  }
}

function decryptSecret(encryptedValue: string | undefined, encryption: SecretEncryption): string {
  if (!encryptedValue) return ''
  const payload = Buffer.from(encryptedValue, 'base64')
  if (encryption === 'safeStorage') {
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
  const encryption = apiKeySecret?.encryption || searchApiKeySecret?.encryption || (safeStorage.isEncryptionAvailable() ? 'safeStorage' : 'plain')

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
  await rm(credentialPath(), { force: true })
}

function createApplicationMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
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
      label: 'View',
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
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { role: 'front' },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
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

function onboardingHtml(): string {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;">
  <title>Set up OpenSquilla</title>
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
        <h1>Desktop setup</h1>
        <p>Configure the local runtime in the same order as the guided CLI.</p>
      </section>
      <nav class="progress" aria-label="Setup steps">
        <button class="step active" type="button" data-step-label="0">
          <span class="step-index">1</span>
          <span><strong>Mode</strong><span>Setup depth</span></span>
        </button>
        <button class="step" type="button" data-step-label="1">
          <span class="step-index">2</span>
          <span><strong>Provider</strong><span>Model access</span></span>
        </button>
        <button class="step" type="button" data-step-label="2" data-advanced-step>
          <span class="step-index">3</span>
          <span><strong>Smart Router</strong><span>Routing mode</span></span>
        </button>
        <button class="step" type="button" data-step-label="3" data-advanced-step>
          <span class="step-index">4</span>
          <span><strong>Tiers</strong><span>Default models</span></span>
        </button>
        <button class="step" type="button" data-step-label="4">
          <span class="step-index">5</span>
          <span><strong>Search</strong><span>Optional web access</span></span>
        </button>
      </nav>
      <div class="rail-foot">OpenSquilla keeps this profile local to your Mac.</div>
    </aside>
    <form id="setup-form" class="deck">
      <section class="setup-card active" data-screen="0">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 01</p>
            <h2>Choose setup depth</h2>
            <p>Start with the shortest working path, or open the full router and tier controls now.</p>
          </div>
          <span class="card-badge">Start</span>
        </header>
        <div class="card-body">
          <div class="setup-mode-grid" role="radiogroup" aria-label="Setup depth">
            <button class="choice active" type="button" data-setup-mode="simple">
              <strong>Simple setup</strong>
              <small>Pick one provider, add its key, choose search, and start OpenSquilla with defaults.</small>
            </button>
            <button class="choice" type="button" data-setup-mode="advanced">
              <strong>Advanced setup</strong>
              <small>Review Smart Router mode, tier defaults, and direct model details before startup.</small>
            </button>
          </div>
          <input id="setupMode" type="hidden" value="simple" />
          <div class="note">You can change provider, router, and search settings later from the desktop Settings page.</div>
        </div>
        <footer class="actions">
          <button class="secondary" type="button" id="cancel">Quit</button>
          <button class="primary next-button" type="button">Continue</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="1">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 02</p>
            <h2>Connect a provider</h2>
            <p>This is the account the local runtime uses for model calls. OpenRouter is the default; more providers stay tucked away until you need them.</p>
          </div>
          <span class="card-badge">Required</span>
        </header>
        <div class="card-body">
        <div class="provider-picker">
          <div class="provider-grid" id="providerGrid"></div>
          <div class="provider-more">
            <button class="provider-more-toggle" type="button" id="providerMoreToggle">
              <span>More providers</span><span id="providerMoreCount"></span>
            </button>
            <div class="provider-more-list" id="providerMoreList" hidden></div>
          </div>
        </div>
        <input id="provider" type="hidden" value="openrouter" />
        <label>
          API key
          <input id="apiKey" name="apiKey" type="password" autocomplete="off" placeholder="sk-..." />
        </label>
        <details>
          <summary>Endpoint and direct model</summary>
          <div class="field-pair">
          <label>
            Base URL
            <input id="baseUrl" name="baseUrl" autocomplete="off" />
          </label>
          <label>
            Direct model
            <input id="model" name="model" autocomplete="off" />
          </label>
          </div>
        </details>
        <div class="note" id="providerHint"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">Back</button>
          <button class="primary next-button" type="button">Next</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="2">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 03</p>
            <h2>Select Smart Router mode</h2>
            <p>Choose whether OpenSquilla should route work across tier defaults or call one model directly.</p>
          </div>
          <span class="card-badge">Routing</span>
        </header>
        <div class="card-body">
          <div class="choice-row" id="routerModeGrid" role="radiogroup" aria-label="Router mode"></div>
          <input id="routerMode" type="hidden" value="recommended" />
          <div class="note" id="routerModeHint"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">Back</button>
          <button class="primary next-button" type="button">Next</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="3">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 04</p>
            <h2>Review tier models</h2>
            <p>Pick the default text tier and keep the CLI defaults, or customize the model ids before startup.</p>
          </div>
          <span class="card-badge">Models</span>
        </header>
        <div class="card-body">
          <div id="tierBody"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">Back</button>
          <button class="primary next-button" type="button">Next</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="4">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 05</p>
            <h2>Choose web search</h2>
            <p>Search is optional. Start without another key, or connect a runtime-supported search provider.</p>
          </div>
          <span class="card-badge">Optional</span>
        </header>
        <div class="card-body">
        <div class="choice-row" id="searchProviderGrid" role="radiogroup" aria-label="Search provider"></div>
        <input id="searchProvider" type="hidden" value="duckduckgo" />
        <label id="searchKeyLabel" hidden>
          Search API key
          <input id="searchApiKey" name="searchApiKey" type="password" autocomplete="off" placeholder="SEARCH_API_KEY" />
        </label>
        <div class="note" id="searchHint">DuckDuckGo is enough to start.</div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button">Back</button>
          <button class="primary" type="button" id="finish">Start OpenSquilla</button>
        </footer>
      </section>
      <div class="error" id="error"></div>
    </form>
  </main>
  <script>
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
      if (mode === 'openrouter-mix') return 'OpenRouter model mix';
      if (mode === 'disabled') return 'Direct model';
      return 'Default tier routing';
    }
    function syncProviderDefaults(resetRouter) {
      const selected = currentProvider();
      baseUrl.value = selected.baseUrl || baseUrl.value;
      model.value = selected.model || model.value;
      providerHint.textContent = selected.label + ' stores the key as ' + (selected.apiKeyEnv || 'no API key') + '. ' + selected.note;
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
        '<span class="provider-tag">provider</span><strong>' + item.label + '</strong><small>' + (item.routerSupported ? 'Tier defaults available.' : item.note) + '</small></button>'
      )).join('');
      moreToggle.querySelector('span:first-child').textContent = showMoreProviders ? 'Hide providers' : 'More providers';
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
        ? 'Use the default OpenRouter tier settings.'
        : 'Route simple, normal, and hard work through the ' + selected.label + ' tier profile.';
      routerModeGrid.className = 'router-choice';
      routerModeGrid.innerHTML =
        '<div class="router-primary">' +
        '<button class="choice' + (autoActive ? ' active' : '') + '" type="button" data-router-primary="auto"' + (autoDisabled ? ' disabled' : '') + '>' +
        '<strong>Automatic tier routing</strong><small>' + autoBody + '</small></button>' +
        '<button class="choice' + (routerMode.value === 'disabled' ? ' active' : '') + '" type="button" data-router-primary="disabled">' +
        '<strong>Use one fixed model</strong><small>Skip Smart Router and send every request to the direct model.</small></button>' +
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
        ? 'Requests will use the direct model field from the provider step.'
        : modeLabel(routerMode.value) + ' is active. The next step shows the exact t0-t3 and image model ids before saving.';
    }
    function renderTiers() {
      if (routerMode.value === 'disabled') {
        tierBody.innerHTML =
          '<label>Direct model<input id="directModelActive" autocomplete="off" value="' + escapeAttr(model.value) + '" /></label>' +
          '<div class="note">Smart Router is off. Every request uses this model directly.</div>';
        document.getElementById('directModelActive').addEventListener('input', (event) => {
          model.value = event.target.value;
        });
        return;
      }
      const defaultTier = document.getElementById('routerDefaultTier')?.value || 't1';
      const tierButtons = textTiers.map((tier) => (
        '<button class="tier-button' + (tier === defaultTier ? ' active' : '') + '" type="button" data-default-tier="' + tier + '">' +
        '<strong>' + tier.toUpperCase() + '</strong><small title="' + escapeAttr(routerTiers[tier]?.model || 'No model') + '">' + escapeHtml(shortModel(routerTiers[tier]?.model || 'No model')) + '</small></button>'
      )).join('');
      const names = Object.keys(routerTiers).filter((name) => textTiers.includes(name) || name === 'image_model');
      const tierList = names.map((name) => {
        const tier = routerTiers[name] || {};
        return '<div class="tier-item"><div class="tier-name">' + name + '</div><div class="tier-model"><strong>' + escapeHtml(tier.model || '') + '</strong><small>' + escapeHtml(tier.provider || '') + '</small></div>' +
          (name === defaultTier ? '<span class="pill">default</span>' : '<span></span>') + '</div>';
      }).join('');
      const editor = names.map((name) => {
        const tier = routerTiers[name] || {};
        return '<div class="editor-row"><div class="muted-line">' + name + '</div><div class="field-pair">' +
          '<label>Provider<input data-tier-provider="' + name + '" value="' + escapeAttr(tier.provider || '') + '" /></label>' +
          '<label>Model<input data-tier-model="' + name + '" value="' + escapeAttr(tier.model || '') + '" /></label></div></div>';
      }).join('');
      tierBody.innerHTML =
        '<input id="routerDefaultTier" type="hidden" value="' + defaultTier + '" />' +
        '<div class="tier-defaults">' + tierButtons + '</div>' +
        '<div class="tier-list">' + tierList + '</div>' +
        '<details><summary>Customize tier models</summary><div class="editor-grid">' + editor + '</div></details>';
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
        '<strong>' + escapeHtml(item.label) + '</strong><small>' + escapeHtml(item.note || (item.requiresApiKey ? 'Requires an API key.' : 'No key required.')) + '</small></button>'
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
      searchHint.textContent = selected.note || (selected.requiresApiKey ? selected.label + ' will be available to browser-capable agents.' : 'DuckDuckGo is enough to start.');
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
          eyebrow.textContent = 'Step ' + String(screenRouteIndex + 1).padStart(2, '0');
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
      if (step === 1 && selected.requiresApiKey && !document.getElementById('apiKey').value.trim()) return selected.label + ' API key is required.';
      if (step === 3 && routerMode.value === 'disabled' && !model.value.trim()) return 'Direct model is required when Smart Router is disabled.';
      if (step === 3 && routerMode.value !== 'disabled') {
        const defaultTier = document.getElementById('routerDefaultTier')?.value || 't1';
        if (!routerTiers[defaultTier] || !routerTiers[defaultTier].model) return 'Default router tier requires a model.';
      }
      if (step === 4 && selectedSearch.requiresApiKey && !document.getElementById('searchApiKey').value.trim()) return selectedSearch.label + ' search API key is required.';
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
    await writeDesktopConfig(existing)
    return existing
  }

  return new Promise((resolveCredential, rejectCredential) => {
    resolveOnboarding = resolveCredential
    rejectOnboarding = rejectCredential
    onboardingWindow = new BrowserWindow({
      width: 1040,
      height: 820,
      minWidth: 900,
      minHeight: 720,
      title: 'Set up OpenSquilla',
      icon: appIconPath(),
      resizable: true,
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

    onboardingWindow.once('ready-to-show', () => onboardingWindow?.show())
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

async function startGateway(): Promise<GatewayState> {
  const overrideUrl = process.env.OPENSQUILLA_DESKTOP_GATEWAY_URL
  const explicitPort = process.env.OPENSQUILLA_DESKTOP_GATEWAY_PORT
  if (overrideUrl) {
    sendBootStatus('Checking gateway health')
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
    sendBootStatus('Loading Control UI')
    gatewayState.url = 'http://127.0.0.1:18791'
    gatewayState.port = 18791
    gatewayState.owned = false
    gatewayState.status = 'ready'
    return gatewayState
  }

  sendBootStatus('Preparing desktop profile')
  const connection = await runOnboarding()
  const apiKey = decryptApiKey(connection)
  if (!apiKey) throw new Error('Saved desktop API key could not be read.')
  const searchApiKey = decryptSearchApiKey(connection)
  await writeDesktopConfig(connection)

  sendBootStatus('Starting local runtime')
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

  gatewayProcess = spawn(
    runtime.command,
    [...runtime.args, '--port', String(port), '--bind', '127.0.0.1', '--config', desktopConfigPath()],
    {
      cwd: runtime.cwd,
      env: {
        ...process.env,
        [connection.apiKeyEnv]: apiKey,
        ...(connection.searchApiKeyEnv && searchApiKey ? { [connection.searchApiKeyEnv]: searchApiKey } : {}),
        OPENSQUILLA_DESKTOP: '1',
        OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
        OPENSQUILLA_STATE_DIR: desktopStateDir(),
        PYTHONUNBUFFERED: '1',
      },
    }
  )

  gatewayProcess.stdout.pipe(logStream, { end: false })
  gatewayProcess.stderr.pipe(logStream, { end: false })
  gatewayProcess.once('exit', (code, signal) => {
    gatewayState.status = isQuitting ? 'stopped' : 'error'
    gatewayState.error = `gateway exited code=${code ?? 'null'} signal=${signal ?? 'null'}`
    logStream.write(`\n[desktop] ${gatewayState.error}\n`)
    if (!isQuitting && gatewayState.status === 'error') sendBootError(gatewayState.error)
  })

  sendBootStatus('Checking gateway health')
  await waitForGateway(url)
  await waitForControlUi(url)
  sendBootStatus('Loading Control UI')
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

async function createMainWindow(): Promise<BrowserWindow> {
  if (mainWindow && !mainWindow.isDestroyed()) return mainWindow

  mainWindow = new BrowserWindow({
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
  installEditingContextMenu(mainWindow)

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  await mainWindow.loadFile(bootPagePath())
  return mainWindow
}

async function bootDesktopApp(): Promise<void> {
  if (startupInProgress) return
  startupInProgress = true
  sendBootStatus('Preparing desktop profile')
  try {
    const gateway = await startGateway()
    const window = await createMainWindow()
    sendBootStatus('Loading Control UI')
    await loadControlUi(window, gateway.url)
    sendBootStatus('Ready')
  } catch (error) {
    gatewayState.status = 'error'
    gatewayState.error = error instanceof Error ? error.message : String(error)
    await createMainWindow().catch(() => null)
    sendBootError(error)
  } finally {
    startupInProgress = false
  }
}

function stopGateway(): void {
  if (!gatewayProcess || !gatewayState.owned) return
  const child = gatewayProcess
  gatewayProcess = null
  child.kill('SIGTERM')
  setTimeout(() => {
    if (!child.killed) child.kill('SIGKILL')
  }, 4000).unref()
}

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
ipcMain.handle('desktop:boot:state', () => ({
  status: bootStatus,
  error: bootError,
  gateway: { ...gatewayState },
}))
ipcMain.handle('desktop:boot:retry', async () => {
  if (startupInProgress) return { ok: false, reason: 'startup_in_progress' }
  if (gatewayProcess && gatewayState.owned) stopGateway()
  gatewayState.status = 'stopped'
  gatewayState.error = undefined
  await mainWindow?.loadFile(bootPagePath())
  void bootDesktopApp()
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
  if (BrowserWindow.getAllWindows().length === 0) {
    void bootDesktopApp()
  }
})

void app.whenReady().then(async () => {
  app.name = 'OpenSquilla'
  createApplicationMenu()
  void bootDesktopApp()
})
