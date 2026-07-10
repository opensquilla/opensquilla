import { app, BrowserWindow, dialog, Menu, ipcMain, nativeTheme, safeStorage, shell } from 'electron'
import electronUpdater from 'electron-updater'
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFileSync, createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, rmdirSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { access, constants, readFile, readdir, rename, rm, stat, unlink, writeFile } from 'node:fs/promises'
import net from 'node:net'
import { homedir, tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DESKTOP_LOCALES, resolveLocaleFromTags, type DesktopLocale } from './desktop-locale.js'
import { buildCliInvocation } from './cli-invocation.js'
import { secretStorageBackendForPolicy, shouldUseChromiumMockKeychainForPolicy } from './secret-storage-policy.js'
import {
  GITHUB_UPDATE_OWNER,
  GITHUB_UPDATE_REPO,
  parseOpenSquillaReleaseTag,
  selectMacPrereleaseCandidate,
  type ReleaseSummary,
} from './update-feed-resolver.js'

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
type ModelRoutingMode = 'squilla_router' | 'direct' | 'llm_ensemble'
type TextRouterTier = 'c0' | 'c1' | 'c2' | 'c3'

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
  modelRoutingMode: ModelRoutingMode
  routerMode: RouterMode
  routerDefaultTier: TextRouterTier
  routerTiers: Record<string, RouterTier>
  searchProvider: string
  searchApiKeyEnv: string
  encryptedSearchApiKey?: string
  encryption: SecretEncryption
  disableNetworkObservability: boolean
  createdAt: string
  updatedAt: string
}

interface OnboardingPayload {
  provider?: unknown
  model?: unknown
  baseUrl?: unknown
  apiKey?: unknown
  modelRoutingMode?: unknown
  routerMode?: unknown
  routerDefaultTier?: unknown
  routerTiers?: unknown
  searchProvider?: unknown
  searchApiKey?: unknown
  disableNetworkObservability?: unknown
  locale?: unknown
}

interface DesktopSettingsPayload extends OnboardingPayload {}

interface DesktopSettingsSnapshot {
  provider: string
  model: string
  baseUrl: string
  apiKeyConfigured: boolean
  modelRoutingMode: ModelRoutingMode
  routerMode: RouterMode
  routerDefaultTier: TextRouterTier
  routerTiers: Record<string, RouterTier>
  searchProvider: string
  searchApiKeyEnv: string
  searchApiKeyConfigured: boolean
  disableNetworkObservability: boolean
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

interface MacInstallContext {
  appBundlePath: string | null
  translocated: boolean
  inApplications: boolean
  blocked: boolean
}

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(__dirname, '..')
const defaultRepoRoot = resolve(packageRoot, '..', '..')
const repoRoot = process.env.OPENSQUILLA_DESKTOP_REPO_ROOT
  ? resolve(process.env.OPENSQUILLA_DESKTOP_REPO_ROOT)
  : defaultRepoRoot
const shouldUseNativeApplicationMenu = process.platform === 'darwin'

let mainWindow: BrowserWindow | null = null
let onboardingWindow: BrowserWindow | null = null

type DesktopNativeThemeSource = 'light' | 'dark' | 'system'

function normalizeDesktopNativeThemeSource(payload: unknown): DesktopNativeThemeSource {
  const source = typeof payload === 'string'
    ? payload
    : payload && typeof payload === 'object' && 'source' in payload
      ? (payload as { source?: unknown }).source
      : undefined
  return source === 'light' || source === 'dark' || source === 'system' ? source : 'system'
}

function applyDesktopNativeTheme(source: DesktopNativeThemeSource): { source: DesktopNativeThemeSource; shouldUseDarkColors: boolean } {
  nativeTheme.themeSource = source
  const backgroundColor = nativeTheme.shouldUseDarkColors ? '#08080A' : '#F7F6F3'
  for (const window of [mainWindow, onboardingWindow]) {
    if (window && !window.isDestroyed()) window.setBackgroundColor(backgroundColor)
  }
  return { source, shouldUseDarkColors: nativeTheme.shouldUseDarkColors }
}
let gatewayProcess: ChildProcessWithoutNullStreams | null = null
let isQuitting = false
// Opt stopGateway into the Windows HTTP graceful-drain path even while isQuitting
// is set, for the update/uninstall flows that keep the main process alive and
// await the child's exit (so the fire-and-forget drain is not racing app teardown).
let allowGracefulShutdownWhileQuitting = false

// Main-process lifecycle log (distinct from the gateway child's gateway.log).
// Records launch, single-instance-lock acquisition, and quit phases so a
// "second launch does nothing" report (issue #446) is diagnosable from a user
// machine. Synchronous append: these events are rare and must survive an
// imminent app.exit().
function desktopLog(event: string, detail?: Record<string, unknown>): void {
  try {
    const logDir = join(app.getPath('userData'), 'logs')
    mkdirSync(logDir, { recursive: true })
    const line = JSON.stringify({ at: new Date().toISOString(), event, ...detail }) + '\n'
    appendFileSync(join(logDir, 'desktop.log'), line, 'utf-8')
  } catch {
    // Logging must never break the lifecycle it observes.
  }
}

let gatewayStartPromise: Promise<GatewayState> | null = null
let resolveOnboarding: ((credential: DesktopConnection) => void) | null = null
let rejectOnboarding: ((error: Error) => void) | null = null
// Legacy home detected for the CURRENT onboarding run. The onboarding migrate
// IPC handlers read the source path/kind from here (main-process truth), never
// from the renderer payload.
let onboardingMigrationCandidate: LegacyImportCandidate | null = null
let onboardingMigrationPreviewApprovedAt = 0
let secretStorageBackendCache: SecretEncryption | null = null
let macCodeSignatureDiagnosticCache: string | null = null
let bootStatus: BootStatus = {
  phaseId: 'profile',
  label: 'Preparing desktop profile',
  at: new Date().toISOString(),
}
let bootError: BootError | null = null
let forceOnboardingOnNextStartup = false
const gatewayProcessTreeChildren = new WeakSet<ChildProcessWithoutNullStreams>()

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

// ── Legacy desktop layout relocation (one-time) ────────────────────────────
// Until 0.5.x the gateway child ran with OPENSQUILLA_STATE_DIR=desktopStateDir()
// (<home>/state). The Python side treats that env var as the OpenSquilla HOME
// ROOT, so home-derived data — managed skills, the default workspace with
// MEMORY.md, session-archive, router self-learning, a user .env, and the
// paths.state_dir() consumers that nested a second state/ level — landed one
// level too deep. The gateway spawn now passes desktopHome(); this moves the
// legacy nested layout up one level, once, before the first spawn with the new
// env. Databases under state/ (sessions.db, scheduler.db, agents/) are pinned
// by the TOML state_dir and were always correct — they are never touched.
// Design: docs/features/legacy-home-migration-design.md (Phase 1).
const DESKTOP_LAYOUT_MARKER = 'desktop-layout-v2.json'
const LEGACY_HOME_ENTRIES = [
  'skills',
  'skills-taps.json',
  'skills-lock.json',
  'workspace',
  'session-archive',
  'router',
  '.env',
]

function relocateLegacyDesktopStateLayout(): void {
  const home = desktopHome()
  const state = desktopStateDir()
  const markerPath = join(home, DESKTOP_LAYOUT_MARKER)
  if (existsSync(markerPath)) return
  if (!existsSync(state)) {
    // Fresh profile: nothing nested to move; stamp so we never rescan.
    mkdirSync(home, { recursive: true })
    writeFileSync(markerPath, JSON.stringify({ migratedAt: new Date().toISOString(), moved: [] }) + '\n', 'utf-8')
    return
  }
  const moved: string[] = []
  let failed = false
  const moveUp = (sourceDir: string, name: string, label: string) => {
    const src = join(sourceDir, name)
    if (!existsSync(src)) return
    const dst = join(sourceDir === state ? home : state, name)
    try {
      if (existsSync(dst)) {
        // Never merge or overwrite: park the legacy copy beside the new one.
        const parked = join(sourceDir, `${name}.pre-relocation`)
        if (!existsSync(parked)) renameSync(src, parked)
      } else {
        renameSync(src, dst)
        moved.push(label)
      }
    } catch (error) {
      failed = true
      desktopLog('desktop_layout_relocation_entry_failed', { name: label, error: String(error) })
    }
  }
  for (const name of LEGACY_HOME_ENTRIES) moveUp(state, name, name)
  // Flatten the nested state/state tree written by direct paths.state_dir()
  // consumers (router calibration, sandbox grants, approval queue, safety log).
  const nested = join(state, 'state')
  if (existsSync(nested)) {
    for (const name of readdirSync(nested)) moveUp(nested, name, `state/${name}`)
    try {
      if (readdirSync(nested).length === 0) rmdirSync(nested)
    } catch {
      // A non-empty or locked nested dir stays in place; harmless.
    }
  }
  if (failed) {
    // No marker on failure: a locked entry (e.g. a lingering gateway) defers
    // the whole relocation to the next boot instead of stranding half of it.
    desktopLog('desktop_layout_relocation_deferred', { moved })
    return
  }
  writeFileSync(markerPath, JSON.stringify({ migratedAt: new Date().toISOString(), moved }) + '\n', 'utf-8')
  if (moved.length > 0) desktopLog('desktop_layout_relocated', { moved })
}

// ── Legacy home import detection ────────────────────────────────────────────
// Quick read-only scan for a legacy OpenSquilla home this desktop profile could
// import. The shape check mirrors the Python migrator's home validator
// (config.toml, state/, or workspace/ inside), so both sides agree on what
// counts as a home — but the import itself always runs through the bundled CLI
// (`opensquilla migrate opensquilla`) so the migration logic exists exactly
// once, in Python. Design: docs/features/legacy-home-migration-design.md
// (Phase 3).
interface LegacyImportCandidate {
  kind: 'cli-home' | 'windows-portable'
  path: string
}

function looksLikeOpenSquillaHome(path: string): boolean {
  try {
    if (!statSync(path).isDirectory()) return false
  } catch {
    return false
  }
  return (
    existsSync(join(path, 'config.toml'))
    || existsSync(join(path, 'state'))
    || existsSync(join(path, 'workspace'))
  )
}

// Compare via realpath so a symlinked/relocated desktop home is never offered
// to itself as an import source.
function resolvedPathsEqual(a: string, b: string): boolean {
  const canonical = (path: string): string => {
    try {
      return realpathSync(path)
    } catch {
      return resolve(path)
    }
  }
  return canonical(a) === canonical(b)
}

const MIGRATION_ITEM_STATUSES = new Set(['migrated', 'planned', 'skipped', 'error'])
const MIGRATION_TRANSACTION_ID_RE = /^\d{20}$/

interface MigrationReportExpectation {
  source: string
  sourceKind?: LegacyImportCandidate['kind']
  target: string
  apply: boolean
}

function migrationRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function migrationReportValidationError(
  value: unknown,
  expected: MigrationReportExpectation,
): string | null {
  const report = migrationRecord(value)
  if (!report) return 'migration report root is not an object'
  if (typeof report.source !== 'string' || !resolvedPathsEqual(report.source, expected.source)) {
    return 'migration report source does not match the approved preview'
  }
  if (
    typeof report.source_kind !== 'string'
    || !['cli-home', 'windows-portable', 'desktop-home'].includes(report.source_kind)
    || (expected.sourceKind !== undefined && report.source_kind !== expected.sourceKind)
  ) {
    return 'migration report source kind is invalid'
  }
  if (typeof report.target !== 'string' || !resolvedPathsEqual(report.target, expected.target)) {
    return 'migration report target does not match the desktop profile'
  }
  if (report.apply !== expected.apply) return 'migration report apply mode is invalid'
  if (typeof report.output_dir !== 'string') return 'migration report output directory is invalid'

  const items = report.items
  if (!Array.isArray(items)) return 'migration report items are missing'
  for (const value of items) {
    const item = migrationRecord(value)
    if (
      !item
      || typeof item.kind !== 'string'
      || typeof item.status !== 'string'
      || !MIGRATION_ITEM_STATUSES.has(item.status)
      || typeof item.reason !== 'string'
      || (item.source !== null && typeof item.source !== 'string')
      || (item.destination !== null && typeof item.destination !== 'string')
      || !migrationRecord(item.details)
    ) {
      return 'migration report contains an invalid item'
    }
  }

  for (const key of [
    'candidates',
    'config_transforms',
    'secret_relocations',
    'paused_jobs',
    'notes',
  ]) {
    if (!Array.isArray(report[key])) return `migration report ${key} is invalid`
  }
  const preflight = migrationRecord(report.preflight)
  if (
    !preflight
    || typeof preflight.source_gateway_running !== 'boolean'
    || typeof preflight.target_gateway_running !== 'boolean'
    || typeof preflight.schema_ahead !== 'boolean'
    || typeof preflight.disk_required_bytes !== 'number'
    || typeof preflight.disk_free_bytes !== 'number'
  ) {
    return 'migration report preflight data is invalid'
  }
  return null
}

function migrationReportErrors(report: Record<string, unknown>): Record<string, unknown>[] {
  return (report.items as unknown[])
    .map((item) => migrationRecord(item))
    .filter((item): item is Record<string, unknown> => item?.status === 'error')
}

function windowsPortableHomeRoots(): string[] {
  const roots: string[] = []
  if (process.env.LOCALAPPDATA) {
    roots.push(join(process.env.LOCALAPPDATA, 'OpenSquilla', 'portable'))
  }
  roots.push(join(process.env.TEMP || tmpdir(), 'OpenSquilla', 'portable'))
  return roots
}

function sourceWasImportedToTarget(source: string, target: string): boolean {
  try {
    const payload = JSON.parse(
      readFileSync(join(source, '.opensquilla-imported.json'), 'utf8'),
    ) as { target?: unknown; transaction_id?: unknown }
    if (typeof payload.target !== 'string' || !resolvedPathsEqual(payload.target, target)) {
      return false
    }
    const transactionId = typeof payload.transaction_id === 'string'
      ? payload.transaction_id
      : ''
    if (!MIGRATION_TRANSACTION_ID_RE.test(transactionId)) return false
    const receipt = JSON.parse(
      readFileSync(
        join(target, 'migration', 'opensquilla', transactionId, 'report.json'),
        'utf8',
      ),
    ) as unknown
    const validationError = migrationReportValidationError(receipt, {
      source,
      target,
      apply: true,
    })
    return validationError === null
      && migrationReportErrors(receipt as Record<string, unknown>).length === 0
  } catch {
    return false
  }
}

// The Python importer publishes a complete sibling staging tree by renaming the
// old target aside and then renaming staging into place. A crash between those
// two operations leaves this durable journal. Recover it before onboarding or
// layout relocation can create a fresh empty target over the missing profile.
function recoverInterruptedDesktopImport(): void {
  const target = desktopHome()
  const parent = dirname(target)
  const journal = join(parent, `.${basename(target)}.import-commit.json`)
  if (!existsSync(journal)) return
  const payload = JSON.parse(readFileSync(journal, 'utf8')) as Record<string, unknown>
  const recordedTarget = String(payload.target || '')
  const staging = String(payload.staging || '')
  const backup = String(payload.backup || '')
  const phase = String(payload.phase || '')
  const validPhase = ['prepared', 'target-backed-up', 'published'].includes(phase)
  const validStaging = dirname(resolve(staging)) === resolve(parent)
    && basename(staging).startsWith('.opensquilla-import-')
  const validBackup = dirname(resolve(backup)) === resolve(parent)
    && basename(backup).startsWith(`${basename(target)}.backup.`)
  if (!resolvedPathsEqual(recordedTarget, target) || !validPhase || !validStaging || !validBackup) {
    throw new Error(`Unsafe or malformed desktop import recovery journal: ${journal}`)
  }

  if (!existsSync(target) && existsSync(backup)) {
    renameSync(backup, target)
  } else if (!existsSync(target) && phase !== 'prepared') {
    throw new Error('Interrupted desktop import has no target or rollback backup.')
  }
  rmSync(staging, { recursive: true, force: true })
  unlinkSync(journal)
  desktopLog('migration_recovered', { phase, target })
}

function detectLegacyImportCandidate(): LegacyImportCandidate | null {
  // The plain CLI home wins over portable unpacks when both exist.
  const cliHome = join(homedir(), '.opensquilla')
  if (
    looksLikeOpenSquillaHome(cliHome)
    && !resolvedPathsEqual(cliHome, desktopHome())
    && !sourceWasImportedToTarget(cliHome, desktopHome())
  ) {
    return { kind: 'cli-home', path: cliHome }
  }
  if (process.platform !== 'win32') return null
  // Windows portable bundles unpack under LOCALAPPDATA/TEMP; pick the home with
  // the newest config.toml so a stale unpack does not shadow the live one.
  let best: { path: string; mtime: number } | null = null
  for (const root of windowsPortableHomeRoots()) {
    let entries: string[] = []
    try {
      entries = readdirSync(root)
    } catch {
      continue
    }
    for (const entry of entries) {
      const candidate = join(root, entry)
      if (!looksLikeOpenSquillaHome(candidate)) continue
      if (resolvedPathsEqual(candidate, desktopHome())) continue
      if (sourceWasImportedToTarget(candidate, desktopHome())) continue
      let mtime = 0
      try {
        mtime = statSync(join(candidate, 'config.toml')).mtimeMs
      } catch {
        mtime = 0
      }
      if (!best || mtime > best.mtime) best = { path: candidate, mtime }
    }
  }
  return best ? { kind: 'windows-portable', path: best.path } : null
}

function bootPagePath(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'boot.html')
    : join(packageRoot, 'src', 'boot.html')
}

function appIconPath(): string {
  // Only icon.icns (macOS) and icon.ico (Windows) ship in assets/ — there is no
  // icon.png, so the previous path resolved to a missing file everywhere. On
  // macOS BrowserWindow.icon is ignored (the bundle icon is used), so pointing at
  // the platform icon that exists is correct for the surfaces that do read it.
  const iconFile = process.platform === 'win32' ? 'icon.ico' : 'icon.icns'
  return app.isPackaged
    ? join(process.resourcesPath, 'app.asar', 'assets', iconFile)
    : join(packageRoot, 'assets', iconFile)
}

const MAC_APP_TRANSLOCATION_SEGMENT = '/AppTranslocation/'
const MAC_APP_RESOURCES_SUFFIX = '.app/Contents/Resources'

function normalizedPosixPath(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '')
}

function macAppBundlePath(resourcesPath = process.resourcesPath): string | null {
  const normalized = normalizedPosixPath(resourcesPath)
  const markerIndex = normalized.indexOf(MAC_APP_RESOURCES_SUFFIX)
  if (markerIndex < 0) return null
  return normalized.slice(0, markerIndex + '.app'.length)
}

function isMacApplicationsBundlePath(bundlePath: string | null): boolean {
  if (!bundlePath) return false
  const normalized = normalizedPosixPath(bundlePath)
  return normalized === '/Applications/OpenSquilla.app' || normalized.startsWith('/Applications/')
}

function macDesktopInstallContext(): MacInstallContext {
  if (process.platform !== 'darwin' || !app.isPackaged) {
    return {
      appBundlePath: null,
      translocated: false,
      inApplications: true,
      blocked: false,
    }
  }

  const resourcesPath = normalizedPosixPath(process.resourcesPath)
  const appBundlePath = macAppBundlePath(resourcesPath)
  const installPath = appBundlePath || resourcesPath
  const translocated = installPath.includes(MAC_APP_TRANSLOCATION_SEGMENT)
  const inApplications = isMacApplicationsBundlePath(appBundlePath)
  return {
    appBundlePath,
    translocated,
    inApplications,
    blocked: translocated,
  }
}

function macDesktopInstallBlockerMessage(context = macDesktopInstallContext()): string | null {
  if (!context.blocked) return null
  const currentLocation = context.appBundlePath ? ` Current location: ${context.appBundlePath}` : ''
  return (
    'OpenSquilla is running from a temporary macOS AppTranslocation location. ' +
    'Quit OpenSquilla, drag OpenSquilla.app from the DMG into Applications if you are installing it, ' +
    'eject the DMG, then open OpenSquilla again.' +
    currentLocation
  )
}

function assertSupportedMacInstallLocation(): void {
  const message = macDesktopInstallBlockerMessage()
  if (message) throw new Error(message)
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

const TEXT_ROUTER_TIERS: TextRouterTier[] = ['c0', 'c1', 'c2', 'c3']
// Legacy desktop builds (and any credential.json written before the c0-c3
// rename) used t0-t3. Canonicalize those on read so upgrading users don't end
// up with duplicate tier keys in their generated config.
const LEGACY_TEXT_TIER_ALIASES: Record<string, TextRouterTier> = {
  t0: 'c0',
  t1: 'c1',
  t2: 'c2',
  t3: 'c3',
}

function canonicalTierKey(name: string): string {
  return LEGACY_TEXT_TIER_ALIASES[name] ?? name
}
const ROUTER_PROFILE_IDS = new Set(['openrouter', 'dashscope', 'deepseek', 'gemini', 'volcengine', 'openai', 'zhipu', 'moonshot'])

const PROVIDER_CATALOG: ProviderCatalogEntry[] = [
  {
    id: 'tokenrhythm',
    label: 'TokenRhythm',
    model: 'deepseek-v4-pro',
    baseUrl: 'https://tokenrhythm.studio/v1',
    apiKeyEnv: 'TOKENRHYTHM_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'DeepSeek, GLM, MiniMax and Kimi model families on one key.',
  },
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
    model: 'gpt-5.5',
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
    model: 'qwen3.7-plus',
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
    model: 'gemini-3.5-flash',
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
    model: 'kimi-k2.6',
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
    model: 'ernie-4.5-turbo-128k',
    baseUrl: 'https://qianfan.baidubce.com/v2',
    apiKeyEnv: 'QIANFAN_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Direct provider model id required.',
  },
  {
    id: 'kimi_coding_openai',
    label: 'Kimi Coding OpenAI-compatible',
    model: 'kimi-for-coding',
    baseUrl: 'https://api.kimi.com/coding/v1',
    apiKeyEnv: 'KIMI_CODING_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Kimi coding-plan endpoint.',
  },
  {
    id: 'kimi_coding_anthropic',
    label: 'Kimi Coding Anthropic-compatible',
    model: 'kimi-for-coding',
    baseUrl: 'https://api.kimi.com/coding',
    apiKeyEnv: 'KIMI_CODING_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Kimi coding-plan Anthropic-shaped endpoint.',
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimaxi.com/anthropic',
    apiKeyEnv: 'MINIMAX_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax Anthropic-compatible endpoint.',
  },
  {
    id: 'minimax_cn',
    label: 'MiniMax Mainland',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimaxi.com/anthropic',
    apiKeyEnv: 'MINIMAX_CN_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax mainland Anthropic-compatible endpoint.',
  },
  {
    id: 'minimax_global',
    label: 'MiniMax Global',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimax.io/anthropic',
    apiKeyEnv: 'MINIMAX_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax global Anthropic-compatible endpoint.',
  },
  {
    id: 'minimax_openai',
    label: 'MiniMax OpenAI-compatible',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimax.io/v1',
    apiKeyEnv: 'MINIMAX_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax OpenAI-compatible endpoint.',
  },
  {
    id: 'minimax_coding_openai',
    label: 'MiniMax Coding OpenAI-compatible',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimaxi.com/v1',
    apiKeyEnv: 'MINIMAX_CODING_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax coding-plan OpenAI-compatible endpoint.',
  },
  {
    id: 'minimax_coding_anthropic',
    label: 'MiniMax Coding Anthropic-compatible',
    model: 'MiniMax-M2.7',
    baseUrl: 'https://api.minimaxi.com/anthropic',
    apiKeyEnv: 'MINIMAX_CODING_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiniMax coding-plan Anthropic-shaped endpoint.',
  },
  {
    id: 'mimo_openai',
    label: 'MiMo OpenAI-compatible',
    model: 'mimo-v2.5',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
    apiKeyEnv: 'MIMO_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiMo coding-plan endpoint.',
  },
  {
    id: 'mimo_anthropic',
    label: 'MiMo Anthropic-compatible',
    model: 'mimo-v2.5',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/anthropic',
    apiKeyEnv: 'MIMO_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'MiMo coding-plan Anthropic-shaped endpoint.',
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
    id: 'volcengine_coding_plan',
    label: 'Volcengine Coding Plan',
    model: 'doubao-seed-2.0-pro',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/coding/v3',
    apiKeyEnv: 'VOLCENGINE_API_KEY',
    requiresApiKey: true,
    routerSupported: false,
    deployment: 'cloud',
    note: 'Volcengine coding-plan endpoint.',
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
  {
    providerId: 'iqs',
    label: 'Alibaba Cloud IQS',
    envKey: 'IQS_SEARCH_API_KEY',
    requiresApiKey: true,
    note: 'Alibaba Cloud web search tuned for agents, with strong Chinese-web coverage.',
    keyPlaceholder: 'IQS_SEARCH_API_KEY',
  },
]

const SEARCH_PROVIDER_BY_ID = new Map(
  SEARCH_PROVIDER_CATALOG.map((provider) => [provider.providerId, provider]),
)

function textRouterProfile(
  provider: string,
  c0: string,
  c1: string,
  c2: string,
  c3: string,
  subject: string,
): Record<string, RouterTier> {
  return {
    c0: { provider, model: c0, description: `${subject} fast route`, thinkingLevel: 'off' },
    c1: { provider, model: c1, description: `${subject} balanced route`, thinkingLevel: 'low' },
    c2: { provider, model: c2, description: `${subject} strong route`, thinkingLevel: 'medium' },
    c3: { provider, model: c3, description: `${subject} highest route`, thinkingLevel: 'high' },
  }
}

function minimaxRouterProfile(provider: string): Record<string, RouterTier> {
  return textRouterProfile(
    provider,
    'MiniMax-M2.7',
    'MiniMax-M2.7',
    'MiniMax-M3',
    'MiniMax-M3',
    'MiniMax',
  )
}

const ROUTER_PROFILES: Record<string, Record<string, RouterTier>> = {
  openrouter: {
    c0: { provider: 'openrouter', model: 'deepseek/deepseek-v4-flash', description: 'Fast everyday work', thinkingLevel: 'high' },
    c1: { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', description: 'Balanced agent work', thinkingLevel: 'high' },
    c2: { provider: 'openrouter', model: 'z-ai/glm-5.2', description: 'Complex reasoning', thinkingLevel: 'high' },
    c3: { provider: 'openrouter', model: 'anthropic/claude-opus-4.8', description: 'Highest quality review and planning', thinkingLevel: 'high' },
    image_model: { provider: 'openrouter', model: 'moonshotai/kimi-k2.6', description: 'Vision route for image attachments', supportsImage: true, imageOnly: true, thinkingLevel: 'medium' },
  },
  openai: {
    c0: { provider: 'openai', model: 'gpt-5.4-nano', description: 'Fast simple work', thinkingLevel: 'none' },
    c1: { provider: 'openai', model: 'gpt-5.4-mini', description: 'Balanced agent work', thinkingLevel: 'low' },
    c2: { provider: 'openai', model: 'gpt-5.5', description: 'Complex text tasks', thinkingLevel: 'medium' },
    c3: { provider: 'openai', model: 'gpt-5.5', description: 'Deep review and analysis', thinkingLevel: 'high' },
  },
  dashscope: {
    c0: { provider: 'dashscope', model: 'qwen3.6-flash', description: 'Fast simple work' },
    c1: { provider: 'dashscope', model: 'qwen3.7-plus', description: 'Balanced agent work' },
    c2: { provider: 'dashscope', model: 'qwen3.7-max', description: 'Complex text tasks' },
    c3: { provider: 'dashscope', model: 'qwen3.7-max', description: 'Deep reasoning' },
  },
  deepseek: {
    c0: { provider: 'deepseek', model: 'deepseek-v4-flash', description: 'Fast simple work' },
    c1: { provider: 'deepseek', model: 'deepseek-v4-flash', description: 'Balanced agent work' },
    c2: { provider: 'deepseek', model: 'deepseek-v4-pro', description: 'Complex text tasks' },
    c3: { provider: 'deepseek', model: 'deepseek-v4-pro', description: 'Deep reasoning' },
  },
  gemini: {
    c0: { provider: 'gemini', model: 'gemini-3.1-flash-lite', description: 'Fast simple work' },
    c1: { provider: 'gemini', model: 'gemini-3.5-flash', description: 'Balanced agent work', thinkingLevel: 'low' },
    c2: { provider: 'gemini', model: 'gemini-3.1-pro-preview', description: 'Complex text tasks', thinkingLevel: 'medium' },
    c3: { provider: 'gemini', model: 'gemini-3.1-pro-preview', description: 'Deep reasoning', thinkingLevel: 'high' },
  },
  moonshot: {
    c0: { provider: 'moonshot', model: 'kimi-k2.6', description: 'Fast multimodal work', supportsImage: true, thinkingLevel: 'low' },
    c1: { provider: 'moonshot', model: 'kimi-k2.6', description: 'Balanced multimodal work', supportsImage: true, thinkingLevel: 'medium' },
    c2: { provider: 'moonshot', model: 'kimi-k2.6', description: 'Complex text and image work', supportsImage: true, thinkingLevel: 'medium' },
    c3: { provider: 'moonshot', model: 'kimi-k2.7-code', description: 'Code-heavy deep reasoning', supportsImage: true, thinkingLevel: 'high' },
  },
  kimi_coding_openai: textRouterProfile(
    'kimi_coding_openai',
    'kimi-for-coding',
    'kimi-for-coding',
    'kimi-for-coding',
    'kimi-for-coding',
    'Kimi Coding',
  ),
  kimi_coding_anthropic: textRouterProfile(
    'kimi_coding_anthropic',
    'kimi-for-coding',
    'kimi-for-coding',
    'kimi-for-coding',
    'kimi-for-coding',
    'Kimi Coding',
  ),
  volcengine: {
    c0: { provider: 'volcengine', model: 'doubao-seed-2-0-lite-260215', description: 'Fast simple work' },
    c1: { provider: 'volcengine', model: 'doubao-seed-2-0-lite-260215', description: 'Balanced agent work' },
    c2: { provider: 'volcengine', model: 'doubao-seed-2-0-pro-260215', description: 'Complex text tasks' },
    c3: { provider: 'volcengine', model: 'doubao-seed-2-0-pro-260215', description: 'Deep review and analysis' },
  },
  volcengine_coding_plan: textRouterProfile(
    'volcengine_coding_plan',
    'doubao-seed-2.0-lite',
    'doubao-seed-2.0-pro',
    'doubao-seed-2.0-code',
    'doubao-seed-2.0-code',
    'Volcengine Coding Plan',
  ),
  zhipu: {
    c0: { provider: 'zhipu', model: 'glm-5-turbo', description: 'Fast simple work' },
    c1: { provider: 'zhipu', model: 'glm-5', description: 'Balanced agent work' },
    c2: { provider: 'zhipu', model: 'glm-5.1', description: 'Complex text tasks' },
    c3: { provider: 'zhipu', model: 'glm-5.2', description: 'Deep reasoning', thinkingLevel: 'high' },
  },
  minimax: minimaxRouterProfile('minimax'),
  minimax_cn: minimaxRouterProfile('minimax_cn'),
  minimax_global: minimaxRouterProfile('minimax_global'),
  minimax_coding_openai: minimaxRouterProfile('minimax_coding_openai'),
  minimax_coding_anthropic: minimaxRouterProfile('minimax_coding_anthropic'),
  mimo_openai: textRouterProfile(
    'mimo_openai',
    'mimo-v2.5',
    'mimo-v2.5',
    'mimo-v2.5-pro',
    'mimo-v2.5-pro',
    'MiMo',
  ),
  mimo_anthropic: textRouterProfile(
    'mimo_anthropic',
    'mimo-v2.5',
    'mimo-v2.5',
    'mimo-v2.5-pro',
    'mimo-v2.5-pro',
    'MiMo',
  ),
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
  const canonical = canonicalTierKey(value)
  return TEXT_ROUTER_TIERS.includes(canonical as TextRouterTier) ? canonical as TextRouterTier : 'c1'
}

function normalizeRouterMode(raw: unknown, provider: string): RouterMode {
  const value = String(raw || '').trim().toLowerCase()
  if (value === 'disabled') return 'disabled'
  if (value === 'openrouter-mix' && provider === 'openrouter') return 'openrouter-mix'
  if (ROUTER_PROFILE_IDS.has(provider)) return 'recommended'
  return 'disabled'
}

function modelRoutingModeAllowed(mode: ModelRoutingMode, provider: string): boolean {
  if (mode === 'direct') return true
  if (mode === 'llm_ensemble') return provider === 'openrouter'
  return ROUTER_PROFILE_IDS.has(provider)
}

function modelRoutingModeForRouterMode(routerMode: RouterMode, provider: string): ModelRoutingMode {
  if (routerMode === 'disabled') return 'direct'
  if (routerMode === 'openrouter-mix' && provider === 'openrouter') return 'llm_ensemble'
  return modelRoutingModeAllowed('squilla_router', provider) ? 'squilla_router' : 'direct'
}

function normalizeModelRoutingMode(raw: unknown, provider: string, fallbackRouterMode?: RouterMode): ModelRoutingMode {
  const value = String(raw || '').trim().toLowerCase()
  const requested = ['squilla_router', 'direct', 'llm_ensemble'].includes(value)
    ? value as ModelRoutingMode
    : fallbackRouterMode
      ? modelRoutingModeForRouterMode(fallbackRouterMode, provider)
      : modelRoutingModeAllowed('squilla_router', provider)
        ? 'squilla_router'
        : 'direct'
  if (modelRoutingModeAllowed(requested, provider)) return requested
  return modelRoutingModeAllowed('squilla_router', provider) ? 'squilla_router' : 'direct'
}

function routerModeForModelRoutingMode(mode: ModelRoutingMode, provider: string): RouterMode {
  if (mode === 'direct') return 'disabled'
  if (mode === 'llm_ensemble' && provider === 'openrouter') return 'recommended'
  return normalizeRouterMode('recommended', provider)
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
  for (const [rawName, value] of Object.entries(source)) {
    if (!value || typeof value !== 'object') continue
    const name = canonicalTierKey(rawName)
    // Tier keys are emitted raw into TOML table headers ([squilla_router.tiers.NAME]),
    // so a key that is not a TOML bare key (spaces, dots, quotes, brackets, newlines)
    // would produce an unparseable config the gateway rejects on every boot. Drop
    // such keys and fall back to the profile defaults instead.
    if (!/^[A-Za-z0-9_-]+$/.test(name)) continue
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
  return tiers[defaultTier]?.model || tiers.c1?.model || tiers.c0?.model || ''
}

function searchProviderDefaults(provider: string): SearchProviderCatalogEntry {
  return SEARCH_PROVIDER_BY_ID.get(provider) || SEARCH_PROVIDER_BY_ID.get('duckduckgo')!
}

function normalizeSearchProvider(raw: unknown): string {
  const provider = String(raw || '').trim().toLowerCase()
  return SEARCH_PROVIDER_BY_ID.has(provider) ? provider : 'duckduckgo'
}

function normalizeBooleanSetting(raw: unknown, fallback: boolean): boolean {
  if (typeof raw === 'boolean') return raw
  if (typeof raw === 'number') return raw !== 0
  if (typeof raw === 'string') {
    const value = raw.trim().toLowerCase()
    if (['1', 'true', 'yes', 'on'].includes(value)) return true
    if (['0', 'false', 'no', 'off', ''].includes(value)) return false
  }
  return fallback
}

function truthyEnv(raw: string | undefined): boolean {
  return normalizeBooleanSetting(raw, false)
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

function ensembleConfigTomlLines(credential: DesktopConnection): string[] {
  if (credential.modelRoutingMode !== 'llm_ensemble') {
    return [
      '',
      '[llm_ensemble]',
      'enabled = false',
    ]
  }
  return [
    '',
    '[llm_ensemble]',
    'enabled = true',
    'selection_mode = "static_openrouter_b5"',
  ]
}

function desktopConfigShouldWritePrivacySection(credential: DesktopConnection): boolean {
  return credential.disableNetworkObservability || readDesktopConfigNetworkObservabilitySetting() !== null
}

function privacyConfigTomlLines(credential: DesktopConnection): string[] {
  if (!desktopConfigShouldWritePrivacySection(credential)) return []
  return [
    '',
    '[privacy]',
    `disable_network_observability = ${credential.disableNetworkObservability ? 'true' : 'false'}`,
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

function desktopSecretStoragePolicyBackend(): SecretEncryption {
  return secretStorageBackendForPolicy({
    envMode: process.env.OPENSQUILLA_DESKTOP_SECRET_STORAGE,
    platform: process.platform,
    appPackaged: app.isPackaged,
    codesignDiagnostic: macCodeSignatureDiagnostic(),
  })
}

function desktopSecretStorageBackend(): SecretEncryption {
  if (secretStorageBackendCache) return secretStorageBackendCache
  const selected = desktopSecretStoragePolicyBackend()
  secretStorageBackendCache = selected === 'safeStorage' && safeStorage.isEncryptionAvailable() ? 'safeStorage' : 'plain'
  return secretStorageBackendCache
}

function encryptSecret(secret: string): { value: string; encryption: SecretEncryption } {
  const policyBackend = desktopSecretStoragePolicyBackend()
  const availableBackend = desktopSecretStorageBackend()
  if (policyBackend === 'safeStorage') {
    if (availableBackend !== 'safeStorage') {
      throw new Error(
        'The OS keychain is unavailable. Unlock it and reopen OpenSquilla before saving credentials.'
      )
    }
    try {
      return {
        value: safeStorage.encryptString(secret).toString('base64'),
        encryption: 'safeStorage',
      }
    } catch (error) {
      throw new Error(
        `The OS keychain could not encrypt the credential: ${
          error instanceof Error ? error.message : String(error)
        }`
      )
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

function normalizeDesktopCredential(parsed: Partial<DesktopConnection>): DesktopConnection {
  const provider = normalizeProvider(parsed.provider)
  const defaults = providerDefaults(provider)
  const legacyRouterMode = normalizeRouterMode(parsed.routerMode, provider)
  const modelRoutingMode = normalizeModelRoutingMode(parsed.modelRoutingMode, provider, legacyRouterMode)
  const routerMode = routerModeForModelRoutingMode(modelRoutingMode, provider)
  const routerDefaultTier = normalizeTextTier(parsed.routerDefaultTier)
  const defaultTiers = defaultRouterTiers(provider, routerMode)
  const routerTiers = normalizeRouterTiers(parsed.routerTiers, defaultTiers)
  const searchProvider = normalizeSearchProvider(parsed.searchProvider)
  const searchDefaults = searchProviderDefaults(searchProvider)
  const now = new Date().toISOString()
  return {
    provider,
    model: parsed.model || routerDefaultModel(routerTiers, routerDefaultTier) || defaults.model,
    baseUrl: parsed.baseUrl || defaults.baseUrl,
    apiKeyEnv: parsed.apiKeyEnv || defaults.apiKeyEnv,
    encryptedApiKey: parsed.encryptedApiKey || '',
    modelRoutingMode,
    routerMode,
    routerDefaultTier,
    routerTiers,
    searchProvider,
    searchApiKeyEnv: parsed.searchApiKeyEnv || searchDefaults.envKey,
    encryptedSearchApiKey: parsed.encryptedSearchApiKey || '',
    encryption: parsed.encryption === 'safeStorage' ? 'safeStorage' : 'plain',
    disableNetworkObservability: normalizeBooleanSetting(parsed.disableNetworkObservability, false),
    createdAt: parsed.createdAt || now,
    updatedAt: parsed.updatedAt || now,
  }
}

// Write via a temp file + atomic rename so a crash, power loss, or full disk
// mid-write cannot leave a truncated credential (silent re-onboarding + lost
// key) or a truncated config.toml (which, since it is only reseeded when
// missing, would wedge boot on every launch).
async function atomicWriteFile(filePath: string, data: string, mode: number): Promise<void> {
  const tmpPath = `${filePath}.${randomUUID()}.tmp`
  try {
    await writeFile(tmpPath, data, { mode })
    await rename(tmpPath, filePath)
  } catch (err) {
    await rm(tmpPath, { force: true }).catch(() => null)
    throw err
  }
}

async function loadDesktopCredential(): Promise<DesktopConnection | null> {
  try {
    const raw = await readFile(credentialPath(), 'utf8')
    return normalizeDesktopCredential(JSON.parse(raw) as Partial<DesktopConnection>)
  } catch {
    return null
  }
}

async function saveDesktopCredential(payload: OnboardingPayload): Promise<DesktopConnection> {
  const existing = await loadDesktopCredential()
  const provider = normalizeProvider(payload.provider ?? existing?.provider)
  const defaults = providerDefaults(provider)
  const legacyRouterMode = normalizeRouterMode(payload.routerMode ?? existing?.routerMode, provider)
  const hasModelRoutingMode = Object.prototype.hasOwnProperty.call(payload, 'modelRoutingMode')
  const hasRouterMode = Object.prototype.hasOwnProperty.call(payload, 'routerMode')
  const rawModelRoutingMode = hasModelRoutingMode
    ? payload.modelRoutingMode
    : hasRouterMode
      ? undefined
      : existing?.modelRoutingMode
  const modelRoutingMode = normalizeModelRoutingMode(rawModelRoutingMode, provider, legacyRouterMode)
  const routerMode = routerModeForModelRoutingMode(modelRoutingMode, provider)
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
  const configDisableNetworkObservability = readDesktopConfigNetworkObservabilitySetting()
  const disableNetworkObservability = Object.prototype.hasOwnProperty.call(payload, 'disableNetworkObservability')
    ? normalizeBooleanSetting(payload.disableNetworkObservability, existing?.disableNetworkObservability ?? false)
    : configDisableNetworkObservability ?? existing?.disableNetworkObservability ?? false

  if (defaults.requiresApiKey && !encryptedApiKey) throw new Error('API key is required.')
  if (modelRoutingMode === 'llm_ensemble' && provider !== 'openrouter') throw new Error('LLM Ensemble requires OpenRouter in desktop onboarding.')
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
    modelRoutingMode,
    routerMode,
    routerDefaultTier,
    routerTiers,
    searchProvider,
    searchApiKeyEnv: searchDefaults.envKey,
    encryptedSearchApiKey,
    encryption,
    disableNetworkObservability,
    createdAt: existing?.createdAt || now,
    updatedAt: now,
  }

  mkdirSync(app.getPath('userData'), { recursive: true })
  await atomicWriteFile(credentialPath(), JSON.stringify(credential, null, 2), 0o600)
  await writeDesktopConfig(credential)
  return credential
}

// Sections the desktop config template owns and regenerates from the credential
// on every write. Everything else in config.toml is treated as foreign
// (Control-UI/RPC-owned) and preserved verbatim across regenerations.
const DESKTOP_OWNED_CONFIG_SECTIONS = ['llm', 'squilla_router', 'llm_ensemble', 'privacy', 'control_ui']
// Top-level (pre-section) keys the desktop template emits itself. Any OTHER
// top-level key present in config.toml was written by the Control UI / RPC (which
// serializes the whole GatewayConfig, so scalar fields like
// llm_request_timeout_seconds land in the TOML preamble) and must be preserved.
const DESKTOP_OWNED_CONFIG_PREAMBLE_KEYS = ['state_dir', 'search_provider', 'search_api_key_env']

function isDesktopOwnedConfigSection(header: string): boolean {
  const name = header.trim()
  return DESKTOP_OWNED_CONFIG_SECTIONS.some((owned) => name === owned || name.startsWith(`${owned}.`))
}

// Return the lines of every top-level section that the desktop template does not
// own, so they survive a config regeneration. Line-based (like the privacy-config
// reader) to avoid taking on a TOML parser dependency.
function foreignConfigSectionLines(raw: string): string[] {
  const out: string[] = []
  let keeping = false
  for (const rawLine of raw.split(/\r?\n/)) {
    const header = rawLine.trim().match(/^\[+\s*([^\]]+?)\s*\]+$/)
    if (header) keeping = !isDesktopOwnedConfigSection(header[1] ?? '')
    if (keeping) out.push(rawLine)
  }
  while (out.length && out[out.length - 1].trim() === '') out.pop()
  return out
}

// Return the top-level (pre-first-section) key lines the desktop template does
// NOT emit itself, so RPC-written global scalars (llm_request_timeout_seconds,
// log_level, workspace_dir, diagnostics_enabled, …) survive a regeneration. These
// must be re-emitted in the preamble (before any [section]) to stay top-level.
function foreignConfigPreambleLines(raw: string): string[] {
  const out: string[] = []
  for (const rawLine of raw.split(/\r?\n/)) {
    if (/^\s*\[/.test(rawLine)) break // reached the first section header
    const key = rawLine.match(/^\s*([A-Za-z0-9_-]+)\s*=/)
    if (!key) continue // blank line or comment
    if (DESKTOP_OWNED_CONFIG_PREAMBLE_KEYS.includes(key[1] ?? '')) continue
    out.push(rawLine)
  }
  return out
}

async function writeDesktopConfig(credential: DesktopConnection): Promise<void> {
  mkdirSync(desktopHome(), { recursive: true })
  mkdirSync(desktopStateDir(), { recursive: true })
  // Only the desktop-owned sections/keys are regenerated from the credential; any
  // other sections (channels, memory, sandbox, mcp, scheduler, …) AND top-level
  // scalar keys (llm_request_timeout_seconds, log_level, …) the Control UI wrote
  // via RPC are read back and preserved, so a settings save no longer wipes live
  // configuration.
  let preservedForeignSections: string[] = []
  let preservedForeignPreamble: string[] = []
  try {
    const existingRaw = readFileSync(desktopConfigPath(), 'utf8')
    preservedForeignSections = foreignConfigSectionLines(existingRaw)
    preservedForeignPreamble = foreignConfigPreambleLines(existingRaw)
  } catch {
    // No existing config to preserve (fresh install) or unreadable.
  }
  const config = [
    `state_dir = ${tomlString(desktopStateDir())}`,
    `search_provider = ${tomlString(credential.searchProvider)}`,
    ...(credential.searchApiKeyEnv ? [`search_api_key_env = ${tomlString(credential.searchApiKeyEnv)}`] : []),
    // search_max_results is intentionally omitted so the gateway's own default
    // governs instead of pinning it to a hardcoded value.
    // Preserved RPC-written top-level keys stay in the preamble (before any table).
    ...preservedForeignPreamble,
    '',
    '[llm]',
    `provider = ${tomlString(credential.provider)}`,
    `model = ${tomlString(credential.model)}`,
    ...(credential.apiKeyEnv ? [`api_key_env = ${tomlString(credential.apiKeyEnv)}`] : []),
    `base_url = ${tomlString(credential.baseUrl)}`,
    '',
    ...routerConfigTomlLines(credential),
    ...ensembleConfigTomlLines(credential),
    ...privacyConfigTomlLines(credential),
    '',
    '[control_ui]',
    'enabled = true',
    'base_path = "/control"',
    '',
    ...(preservedForeignSections.length ? [...preservedForeignSections, ''] : []),
  ].join('\n')
  await atomicWriteFile(desktopConfigPath(), config, 0o600)
}

function settingsSnapshot(connection: DesktopConnection | null): DesktopSettingsSnapshot {
  const provider = normalizeProvider(connection?.provider)
  const defaults = providerDefaults(provider)
  const legacyRouterMode = normalizeRouterMode(connection?.routerMode, provider)
  const modelRoutingMode = normalizeModelRoutingMode(connection?.modelRoutingMode, provider, legacyRouterMode)
  const routerMode = routerModeForModelRoutingMode(modelRoutingMode, provider)
  const routerDefaultTier = normalizeTextTier(connection?.routerDefaultTier)
  const routerTiers = normalizeRouterTiers(connection?.routerTiers, defaultRouterTiers(provider, routerMode))
  const searchProvider = normalizeSearchProvider(connection?.searchProvider)
  const searchDefaults = searchProviderDefaults(searchProvider)
  return {
    provider,
    model: connection?.model || routerDefaultModel(routerTiers, routerDefaultTier) || defaults.model,
    baseUrl: connection?.baseUrl || defaults.baseUrl,
    apiKeyConfigured: Boolean(connection?.encryptedApiKey),
    modelRoutingMode,
    routerMode,
    routerDefaultTier,
    routerTiers,
    searchProvider,
    searchApiKeyEnv: connection?.searchApiKeyEnv || searchDefaults.envKey,
    searchApiKeyConfigured: Boolean(connection?.encryptedSearchApiKey),
    disableNetworkObservability: connection?.disableNetworkObservability ?? false,
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
  transientPendingMigrationProviderSetup = null
  await rm(pendingMigrationProviderSetupPath(), { force: true })
  await rm(desktopMigrationResultPath(), { force: true })
}

function clearReusableGatewayState(): void {
  gatewayState.url = ''
  gatewayState.port = 0
  gatewayState.owned = false
  gatewayState.status = 'stopped'
  gatewayState.error = undefined
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

// Append an extension implied by the MIME type unless the name already ends with
// a recognized document/image extension. The previous "any .xxx suffix counts as
// an extension" heuristic misclassified version/date suffixes (report.v2,
// plan.rev3), so the authoritative MIME extension was dropped and shell.openPath
// hit a missing/incorrect OS association.
function artifactExtension(name: string, mime: unknown): string {
  const lower = name.toLowerCase()
  if (Object.values(MIME_EXTENSIONS).some((ext) => lower.endsWith(ext))) return ''
  return MIME_EXTENSIONS[artifactMimeKey(mime)] || ''
}

// Artifacts opened this session, so the prune never deletes a file that an
// external viewer (Preview, Excel, a browser) still has open — deleting it out
// from under the app loses the document and any unsaved edits made there.
const openedArtifactPaths = new Set<string>()

// Best-effort prune so opened artifacts do not accumulate unboundedly in temp.
// Skips files opened this session and only removes prior-session leftovers older
// than a day, so a document a user is actively viewing is never yanked away.
async function pruneArtifactCache(dir: string): Promise<void> {
  try {
    const now = Date.now()
    const entries = await readdir(dir)
    await Promise.all(entries.map(async (entry) => {
      const full = join(dir, entry)
      if (openedArtifactPaths.has(full)) return
      try {
        const info = await stat(full)
        if (now - info.mtimeMs > 24 * 60 * 60 * 1000) await unlink(full)
      } catch {}
    }))
  } catch {}
}

async function openArtifactWithDefaultApp(payload: ArtifactOpenRequest): Promise<{ ok: boolean; message?: string }> {
  const raw = payload?.data
  if (!raw) return { ok: false, message: 'No artifact data to open.' }
  try {
    // Reuse the received bytes directly; fs.writeFile accepts a Uint8Array, so
    // Buffer.from() here would just memcpy a second full copy of the payload
    // (hundreds of MB for media artifacts) into the main process.
    const bytes = raw instanceof Uint8Array ? raw : new Uint8Array(raw)
    const dir = join(app.getPath('temp'), 'opensquilla-artifacts')
    mkdirSync(dir, { recursive: true, mode: 0o700 })
    void pruneArtifactCache(dir)
    const name = safeArtifactFileName(payload?.name)
    // A random prefix guarantees a unique, non-colliding, non-dotfile path even
    // for two opens in the same millisecond.
    const filePath = join(dir, `${randomUUID()}-${name}${artifactExtension(name, payload?.mime)}`)
    await writeFile(filePath, bytes, { mode: 0o600 })
    openedArtifactPaths.add(filePath)
    const error = await shell.openPath(filePath)
    if (error) return { ok: false, message: error }
    return { ok: true }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  }
}

// --- Desktop native-shell i18n ---
// The embedded Web UI carries its own vue-i18n layer; this small catalog covers
// the main-process surfaces that live OUTSIDE the BrowserWindow (app-authored
// menu group labels and the onboarding window title), keyed off the OS locale.
// Role-based menu items (Cut/Copy/Paste/…) are localized by Electron itself.
const DESKTOP_LOCALE_LABELS: Record<DesktopLocale, string> = {
  en: 'English',
  'zh-Hans': '简体中文',
  ja: '日本語',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
}
let desktopLocale: DesktopLocale = 'en'

const PROVIDER_NOTE_MESSAGES: Record<DesktopLocale, Record<string, string>> = {
  en: {
    tokenrhythm: 'DeepSeek, GLM, MiniMax and Kimi model families on one key.',
    openrouter: 'Best default for mixed model routing.',
    openai: 'OpenAI-only tier profile.',
    openai_responses: 'OpenAI Responses-API shape (chat + responses).',
    anthropic: 'Direct Claude access without SquillaRouter tiers.',
    dashscope: 'Qwen tier profile for Mainland-friendly access.',
    deepseek: 'DeepSeek-only fast and pro routing.',
    gemini: 'Gemini OpenAI-compatible tier profile.',
    moonshot: 'Kimi text and image-capable routes.',
    ollama: 'Local direct model path.',
    qianfan: 'Direct provider model id required.',
    volcengine: 'Doubao tier profile.',
    zhipu: 'GLM tier profile.',
  },
  'zh-Hans': {
    tokenrhythm: '一把密钥即可使用 DeepSeek、GLM、MiniMax、Kimi 全系模型。',
    openrouter: '适合混合模型路由的初始默认选项。',
    openai: '仅使用 OpenAI 的层级配置。',
    openai_responses: 'OpenAI Responses API 格式（chat + responses）。',
    anthropic: '直接访问 Claude，不使用 SquillaRouter 层级。',
    dashscope: '面向大陆访问的 Qwen 层级配置。',
    deepseek: '仅使用 DeepSeek 的 fast/pro 路由。',
    gemini: 'Gemini 的 OpenAI 兼容层级配置。',
    moonshot: 'Kimi 文本和图像能力路由。',
    ollama: '本地直连模型路径。',
    qianfan: '需要填写直连 provider 模型 ID。',
    volcengine: '豆包层级配置。',
    zhipu: 'GLM 层级配置。',
  },
  ja: {
    tokenrhythm: 'DeepSeek・GLM・MiniMax・Kimi の各モデルを 1 つのキーで利用できます。',
    openrouter: '混合モデルルーティングに適した初期デフォルトです。',
    openai: 'OpenAI のみを使うティアプロファイルです。',
    openai_responses: 'OpenAI Responses API 形式（chat + responses）です。',
    anthropic: 'SquillaRouter ティアを使わず Claude に直接アクセスします。',
    dashscope: '中国本土から使いやすい Qwen ティアプロファイルです。',
    deepseek: 'DeepSeek の fast/pro のみでルーティングします。',
    gemini: 'Gemini の OpenAI 互換ティアプロファイルです。',
    moonshot: 'Kimi のテキストと画像対応ルートです。',
    ollama: 'ローカル直接モデルのパスです。',
    qianfan: '直接 provider のモデル ID が必要です。',
    volcengine: 'Doubao ティアプロファイルです。',
    zhipu: 'GLM ティアプロファイルです。',
  },
  fr: {
    tokenrhythm: 'Les familles DeepSeek, GLM, MiniMax et Kimi avec une seule clé.',
    openrouter: 'Bon choix initial par défaut pour le routage de modèles mixtes.',
    openai: 'Profil de niveaux limité à OpenAI.',
    openai_responses: 'Format OpenAI Responses API (chat + responses).',
    anthropic: 'Accès direct à Claude sans niveaux SquillaRouter.',
    dashscope: 'Profil de niveaux Qwen adapté à un accès depuis la Chine continentale.',
    deepseek: 'Routage fast/pro limité à DeepSeek.',
    gemini: 'Profil de niveaux Gemini compatible OpenAI.',
    moonshot: 'Routes Kimi pour le texte et les capacités image.',
    ollama: 'Chemin de modèle direct local.',
    qianfan: 'ID de modèle provider direct requis.',
    volcengine: 'Profil de niveaux Doubao.',
    zhipu: 'Profil de niveaux GLM.',
  },
  de: {
    tokenrhythm: 'DeepSeek-, GLM-, MiniMax- und Kimi-Modelle mit einem einzigen Schlüssel.',
    openrouter: 'Gute anfängliche Voreinstellung für gemischtes Modellrouting.',
    openai: 'Nur-OpenAI-Stufenprofil.',
    openai_responses: 'OpenAI Responses-API-Format (chat + responses).',
    anthropic: 'Direkter Claude-Zugriff ohne SquillaRouter-Stufen.',
    dashscope: 'Qwen-Stufenprofil für gut erreichbaren Zugriff vom chinesischen Festland.',
    deepseek: 'Nur DeepSeek fast/pro Routing.',
    gemini: 'OpenAI-kompatibles Gemini-Stufenprofil.',
    moonshot: 'Kimi-Routen für Text- und Bildfähigkeiten.',
    ollama: 'Lokaler direkter Modellpfad.',
    qianfan: 'Direkte provider-Modell-ID erforderlich.',
    volcengine: 'Doubao-Stufenprofil.',
    zhipu: 'GLM-Stufenprofil.',
  },
  es: {
    tokenrhythm: 'Las familias DeepSeek, GLM, MiniMax y Kimi con una sola clave.',
    openrouter: 'Buena opción inicial para el enrutamiento mixto de modelos.',
    openai: 'Perfil de niveles solo con OpenAI.',
    openai_responses: 'Formato OpenAI Responses API (chat + responses).',
    anthropic: 'Acceso directo a Claude sin niveles SquillaRouter.',
    dashscope: 'Perfil de niveles Qwen para acceso cómodo desde China continental.',
    deepseek: 'Enrutamiento fast/pro solo con DeepSeek.',
    gemini: 'Perfil de niveles Gemini compatible con OpenAI.',
    moonshot: 'Rutas Kimi para texto y capacidades de imagen.',
    ollama: 'Ruta de modelo directo local.',
    qianfan: 'Se requiere el ID del modelo provider directo.',
    volcengine: 'Perfil de niveles Doubao.',
    zhipu: 'Perfil de niveles GLM.',
  },
}

// Localized descriptive notes for the search providers, mirroring
// PROVIDER_NOTE_MESSAGES. Without these the onboarding search cards always
// rendered the hardcoded English catalog notes, so their localized fallbacks
// were unreachable in every non-English locale.
const SEARCH_PROVIDER_NOTE_MESSAGES: Record<DesktopLocale, Record<string, string>> = {
  en: {
    duckduckgo: 'No key required. Good default for getting started.',
    bocha: 'Web search with inline summaries and freshness support.',
    brave: 'Managed search access with freshness support.',
    tavily: 'Freshness-oriented web search for current research.',
    exa: 'Semantic and content-oriented search for research workflows.',
    iqs: 'Alibaba Cloud web search tuned for agents, with strong Chinese-web coverage.',
  },
  'zh-Hans': {
    duckduckgo: '无需密钥。适合入门的默认选项。',
    bocha: '带内联摘要和时效性支持的网络搜索。',
    brave: '带时效性支持的托管搜索访问。',
    tavily: '面向时效性的网络搜索，适合最新研究。',
    exa: '面向语义和内容的搜索，适合研究工作流。',
    iqs: '阿里云面向智能体的联网搜索，中文网页覆盖广。',
  },
  ja: {
    duckduckgo: 'キー不要。始めるのに適したデフォルトです。',
    bocha: 'インライン要約と鮮度対応を備えたウェブ検索です。',
    brave: '鮮度対応を備えたマネージド検索アクセスです。',
    tavily: '最新の調査向けの、鮮度重視のウェブ検索です。',
    exa: '調査ワークフロー向けのセマンティック／コンテンツ指向検索です。',
    iqs: 'エージェント向けに調整された Alibaba Cloud のウェブ検索。中国語ウェブのカバレッジに優れています。',
  },
  fr: {
    duckduckgo: 'Aucune clé requise. Bon choix par défaut pour démarrer.',
    bocha: 'Recherche web avec résumés en ligne et prise en charge de la fraîcheur.',
    brave: 'Accès de recherche géré avec prise en charge de la fraîcheur.',
    tavily: 'Recherche web axée sur la fraîcheur pour la recherche actuelle.',
    exa: 'Recherche sémantique et orientée contenu pour les flux de recherche.',
    iqs: 'Recherche web Alibaba Cloud conçue pour les agents, avec une forte couverture du web chinois.',
  },
  de: {
    duckduckgo: 'Kein Schlüssel erforderlich. Gute Voreinstellung für den Einstieg.',
    bocha: 'Websuche mit Inline-Zusammenfassungen und Aktualitätsunterstützung.',
    brave: 'Verwalteter Suchzugriff mit Aktualitätsunterstützung.',
    tavily: 'Aktualitätsorientierte Websuche für aktuelle Recherche.',
    exa: 'Semantische und inhaltsorientierte Suche für Recherche-Workflows.',
    iqs: 'Alibaba-Cloud-Websuche für Agenten, mit starker Abdeckung des chinesischen Webs.',
  },
  es: {
    duckduckgo: 'No se requiere clave. Buena opción predeterminada para empezar.',
    bocha: 'Búsqueda web con resúmenes en línea y soporte de actualidad.',
    brave: 'Acceso de búsqueda gestionado con soporte de actualidad.',
    tavily: 'Búsqueda web orientada a la actualidad para investigación actual.',
    exa: 'Búsqueda semántica y orientada a contenido para flujos de investigación.',
    iqs: 'Búsqueda web de Alibaba Cloud orientada a agentes, con amplia cobertura de la web china.',
  },
}

function resolveDesktopLocale(): DesktopLocale {
  const preferred = typeof app.getPreferredSystemLanguages === 'function'
    ? app.getPreferredSystemLanguages()
    : []
  return resolveLocaleFromTags([...preferred, app.getLocale()])
}

function desktopLocalePath(): string {
  return join(app.getPath('userData'), 'desktop-locale')
}

// Persist the locale the user picked during onboarding so every main-process
// surface (menu, dialogs, boot splash, next onboarding) honors it across
// launches instead of reverting to the OS locale.
function loadPersistedDesktopLocale(): DesktopLocale | null {
  try {
    const raw = readFileSync(desktopLocalePath(), 'utf8').trim()
    return DESKTOP_LOCALES.includes(raw as DesktopLocale) ? (raw as DesktopLocale) : null
  } catch {
    return null
  }
}

function persistDesktopLocale(locale: DesktopLocale): void {
  try {
    mkdirSync(app.getPath('userData'), { recursive: true })
    writeFileSync(desktopLocalePath(), locale, 'utf8')
  } catch {
    // Best-effort; a failed persist just means the next launch re-resolves the OS locale.
  }
}

function applyDesktopLocaleChoice(raw: unknown): void {
  const requested = String(raw ?? '')
  if (!DESKTOP_LOCALES.includes(requested as DesktopLocale)) return
  if (requested !== desktopLocale) {
    desktopLocale = requested as DesktopLocale
    createApplicationMenu()
  }
  persistDesktopLocale(desktopLocale)
}

const DESKTOP_MESSAGES: Record<DesktopLocale, Record<string, string>> = {
  en: {
    'menu.edit': 'Edit',
    'menu.view': 'View',
    'menu.window': 'Window',
    'menu.checkForUpdates': 'Check for Updates…',
    'menu.relaunchToUpdate': 'Relaunch to Update',
    'menu.downloadDiagnostics': 'Download Diagnostics…',
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
    'update.gatewayShutdownTimeout': 'OpenSquilla could not stop the local runtime. Try relaunching to update again.',
    'update.mockInstallTitle': 'Mock update restart',
    'update.mockInstallDetail': 'Mock mode: OpenSquilla would restart now to install {version}. No files were changed.',
    'uninstall.confirmTitle': 'Delete local OpenSquilla desktop data?',
    'uninstall.confirmMessage': 'This permanently deletes the local desktop profile on this machine.',
    'uninstall.confirmDetail': 'Sessions, configuration, and secrets will be removed. The installed app itself will remain; remove it through your OS after the app closes.',
    'uninstall.cancel': 'Cancel',
    'uninstall.deleteEverything': 'Delete everything',
    'migration.nav.title': 'Import',
    'migration.nav.sub': 'Existing data',
    'migration.step.badge': 'Import',
    'migration.step.heading': 'Import existing OpenSquilla data',
    'migration.step.subtitle': 'OpenSquilla found data from a previous installation on this machine. Preview what would be imported and bring it into the desktop app, or skip and start fresh.',
    'migration.step.sourceLabel': 'Detected data location',
    'migration.step.preview': 'Preview import',
    'migration.step.import': 'Import',
    'migration.step.skip': 'Skip',
    'migration.overwriteTitle': 'Replace conflicting desktop data?',
    'migration.overwriteMessage': 'This import will replace data in the current desktop profile.',
    'migration.overwriteDetail': 'A complete timestamped backup will be retained. Confirm the source below before continuing.',
    'migration.overwriteCancel': 'Cancel',
    'migration.overwriteConfirm': 'Import and replace',
    'launch.alreadyRunningTitle': 'OpenSquilla is already running',
    'launch.alreadyRunningMessage': 'Another OpenSquilla window is already open on this machine. Bringing it to the front.',
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
    'onboarding.language.label': 'Language',
    'onboarding.aria.setupSteps': 'Setup steps',
    'onboarding.aria.setupDepth': 'Setup depth',
    'onboarding.aria.modelRoutingMode': 'Routing mode',
    'onboarding.aria.searchProvider': 'Search provider',
    'onboarding.aria.language': 'Onboarding language',
    'onboarding.nav.mode.title': 'Mode',
    'onboarding.nav.mode.sub': 'Setup depth',
    'onboarding.nav.provider.title': 'Provider',
    'onboarding.nav.provider.sub': 'Model access',
    'onboarding.nav.routing.title': 'Routing',
    'onboarding.nav.routing.sub': 'Mode',
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
    'onboarding.step1.advancedDesc': 'Review tier defaults and direct model details before startup.',
    'onboarding.step1.note': 'You can change provider, router, and search settings later from the desktop Settings page.',
    'onboarding.step1.quit': 'Quit',
    'onboarding.step1.continue': 'Continue',
    'onboarding.step2.badge': 'Required',
    'onboarding.step2.heading': 'Connect a provider',
    'onboarding.step2.subtitle': 'Choose the provider account the local runtime uses for model calls. OpenRouter starts selected, but any supported provider can be used.',
    'onboarding.step2.apiKey': 'API key',
    'onboarding.step2.endpointSummary': 'Endpoint and direct model',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Direct model',
    'onboarding.step2.back': 'Back',
    'onboarding.step2.next': 'Next',
    'onboarding.step3.badge': 'Advanced',
    'onboarding.step3.heading': 'Choose routing mode',
    'onboarding.step3.subtitle': 'Decide whether OpenSquilla should use Smart Router tiers, call one fixed model, or use the OpenRouter ensemble.',
    'onboarding.step3.back': 'Back',
    'onboarding.step3.next': 'Next',
    'onboarding.step3.directModel': 'Direct model',
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
  },
  'zh-Hans': {
    'menu.edit': '编辑',
    'menu.view': '视图',
    'menu.window': '窗口',
    'menu.checkForUpdates': '检查更新…',
    'menu.relaunchToUpdate': '重启以更新',
    'menu.downloadDiagnostics': '下载诊断信息…',
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
    'update.gatewayShutdownTimeout': 'OpenSquilla 无法停止本地运行时。请再次尝试重启以更新。',
    'update.mockInstallTitle': '模拟重启更新',
    'update.mockInstallDetail': '模拟模式：OpenSquilla 现在会重启并安装 {version}。没有修改任何文件。',
    'uninstall.confirmTitle': '删除本地 OpenSquilla 桌面数据？',
    'uninstall.confirmMessage': '这将永久删除本机上的本地桌面配置。',
    'uninstall.confirmDetail': '会话、配置和密钥都将被移除。已安装的应用本身会保留；应用关闭后请通过操作系统将其卸载。',
    'uninstall.cancel': '取消',
    'uninstall.deleteEverything': '全部删除',
    'migration.nav.title': '导入',
    'migration.nav.sub': '现有数据',
    'migration.step.badge': '导入',
    'migration.step.heading': '导入现有的 OpenSquilla 数据',
    'migration.step.subtitle': 'OpenSquilla 在本机上发现了先前安装留下的数据。可以先预览将导入的内容并将其导入桌面应用，也可以跳过并全新开始。',
    'migration.step.sourceLabel': '检测到的数据位置',
    'migration.step.preview': '预览导入',
    'migration.step.import': '导入',
    'migration.step.skip': '跳过',
    'migration.overwriteTitle': '替换冲突的桌面数据？',
    'migration.overwriteMessage': '此次导入将替换当前桌面配置中的数据。',
    'migration.overwriteDetail': '系统会保留完整的时间戳备份。继续前请确认下方的数据来源。',
    'migration.overwriteCancel': '取消',
    'migration.overwriteConfirm': '导入并替换',
    'launch.alreadyRunningTitle': 'OpenSquilla 已在运行',
    'launch.alreadyRunningMessage': '本机已打开另一个 OpenSquilla 窗口。正在将其置于前台。',
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
    'onboarding.language.label': '语言',
    'onboarding.aria.setupSteps': '设置步骤',
    'onboarding.aria.setupDepth': '设置深度',
    'onboarding.aria.modelRoutingMode': '路由模式',
    'onboarding.aria.searchProvider': '搜索提供商',
    'onboarding.aria.language': 'onboarding 语言',
    'onboarding.nav.mode.title': '模式',
    'onboarding.nav.mode.sub': '设置深度',
    'onboarding.nav.provider.title': '提供商',
    'onboarding.nav.provider.sub': '模型访问',
    'onboarding.nav.routing.title': '路由',
    'onboarding.nav.routing.sub': '模式',
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
    'onboarding.step1.advancedDesc': '在启动前查看层级默认值和直连模型详情。',
    'onboarding.step1.note': '稍后可在桌面设置页面更改提供商、路由器和搜索设置。',
    'onboarding.step1.quit': '退出',
    'onboarding.step1.continue': '继续',
    'onboarding.step2.badge': '必填',
    'onboarding.step2.heading': '连接提供商',
    'onboarding.step2.subtitle': '选择本地运行时用于模型调用的提供商账户。OpenRouter 只是初始默认选项，可改用任何支持的提供商。',
    'onboarding.step2.apiKey': 'API 密钥',
    'onboarding.step2.endpointSummary': '端点和直连模型',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': '直连模型',
    'onboarding.step2.back': '返回',
    'onboarding.step2.next': '下一步',
    'onboarding.step3.badge': '高级',
    'onboarding.step3.heading': '选择路由模式',
    'onboarding.step3.subtitle': '选择 OpenSquilla 使用 Smart Router 层级、直连一个固定模型，还是使用 OpenRouter Ensemble。',
    'onboarding.step3.back': '返回',
    'onboarding.step3.next': '下一步',
    'onboarding.step3.directModel': '直连模型',
    'onboarding.step4.badge': '模型',
    'onboarding.step4.heading': '候选模型池',
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
  },
  ja: {
    'menu.edit': '編集',
    'menu.view': '表示',
    'menu.window': 'ウインドウ',
    'menu.checkForUpdates': 'アップデートを確認…',
    'menu.relaunchToUpdate': '再起動してアップデート',
    'menu.downloadDiagnostics': '診断情報をダウンロード…',
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
    'update.gatewayShutdownTimeout': 'ローカルランタイムを停止できませんでした。もう一度、再起動してアップデートをお試しください。',
    'uninstall.confirmTitle': 'ローカルの OpenSquilla デスクトップデータを削除しますか？',
    'uninstall.confirmMessage': 'このマシン上のローカルデスクトッププロファイルを完全に削除します。',
    'uninstall.confirmDetail': 'セッション、設定、シークレットが削除されます。インストール済みのアプリ自体は残ります。アプリを閉じた後、OS から削除してください。',
    'uninstall.cancel': 'キャンセル',
    'uninstall.deleteEverything': 'すべて削除',
    'migration.nav.title': 'インポート',
    'migration.nav.sub': '既存データ',
    'migration.step.badge': 'インポート',
    'migration.step.heading': '既存の OpenSquilla データをインポート',
    'migration.step.subtitle': 'このマシンで以前のインストールのデータが見つかりました。インポートされる内容をプレビューしてデスクトップアプリに取り込むか、スキップして新規に始められます。',
    'migration.step.sourceLabel': '検出されたデータの場所',
    'migration.step.preview': 'インポートをプレビュー',
    'migration.step.import': 'インポート',
    'migration.step.skip': 'スキップ',
    'migration.overwriteTitle': '競合するデスクトップデータを置き換えますか？',
    'migration.overwriteMessage': 'このインポートは現在のデスクトッププロファイルのデータを置き換えます。',
    'migration.overwriteDetail': 'タイムスタンプ付きの完全なバックアップが保持されます。続行する前に以下の移行元を確認してください。',
    'migration.overwriteCancel': 'キャンセル',
    'migration.overwriteConfirm': 'インポートして置換',
    'launch.alreadyRunningTitle': 'OpenSquilla はすでに実行中です',
    'launch.alreadyRunningMessage': 'このマシンでは別の OpenSquilla ウィンドウがすでに開いています。前面に表示します。',
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
    'onboarding.language.label': '言語',
    'onboarding.aria.setupSteps': 'セットアップ手順',
    'onboarding.aria.setupDepth': 'セットアップの詳細度',
    'onboarding.aria.searchProvider': '検索プロバイダー',
    'onboarding.aria.language': 'オンボーディングの言語',
    'onboarding.nav.mode.title': 'モード',
    'onboarding.nav.mode.sub': 'セットアップの詳細度',
    'onboarding.nav.provider.title': 'プロバイダー',
    'onboarding.nav.provider.sub': 'モデルアクセス',
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
    'onboarding.step1.advancedDesc': '起動前にティアのデフォルトと直接モデルの詳細を確認します。',
    'onboarding.step1.note': 'プロバイダー、ルーター、検索の設定は後でデスクトップの設定ページから変更できます。',
    'onboarding.step1.quit': '終了',
    'onboarding.step1.continue': '続行',
    'onboarding.step2.badge': '必須',
    'onboarding.step2.heading': 'プロバイダーを接続',
    'onboarding.step2.subtitle': 'ローカルランタイムがモデル呼び出しに使用するプロバイダーアカウントを選択します。OpenRouter は初期選択であり、対応する任意のプロバイダーに変更できます。',
    'onboarding.step2.apiKey': 'API キー',
    'onboarding.step2.endpointSummary': 'エンドポイントと直接モデル',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': '直接モデル',
    'onboarding.step2.back': '戻る',
    'onboarding.step2.next': '次へ',
    'onboarding.nav.routing.title': 'ルーティング',
    'onboarding.nav.routing.sub': 'モード',
    'onboarding.aria.modelRoutingMode': 'ルーティングモード',
    'onboarding.step3.badge': '詳細',
    'onboarding.step3.heading': 'ルーティングモードを選択',
    'onboarding.step3.subtitle': 'OpenSquilla が Smart Router のティアを使うか、固定モデルを 1 つ呼び出すか、OpenRouter アンサンブルを使うかを選びます。',
    'onboarding.step3.back': '戻る',
    'onboarding.step3.next': '次へ',
    'onboarding.step3.directModel': '直接モデル',
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
  },
  fr: {
    'menu.edit': 'Édition',
    'menu.view': 'Affichage',
    'menu.window': 'Fenêtre',
    'menu.checkForUpdates': 'Rechercher les mises à jour…',
    'menu.relaunchToUpdate': 'Relancer pour mettre à jour',
    'menu.downloadDiagnostics': 'Télécharger le diagnostic…',
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
    'update.gatewayShutdownTimeout': 'OpenSquilla n\'a pas pu arrêter le runtime local. Réessayez de relancer la mise à jour.',
    'uninstall.confirmTitle': 'Supprimer les données locales du bureau OpenSquilla ?',
    'uninstall.confirmMessage': 'Cela supprime définitivement le profil de bureau local sur cette machine.',
    'uninstall.confirmDetail': 'Les sessions, la configuration et les secrets seront supprimés. L’application installée elle-même sera conservée ; supprimez-la via votre système d’exploitation après la fermeture de l’application.',
    'uninstall.cancel': 'Annuler',
    'uninstall.deleteEverything': 'Tout supprimer',
    'migration.nav.title': 'Importation',
    'migration.nav.sub': 'Données existantes',
    'migration.step.badge': 'Importation',
    'migration.step.heading': 'Importer les données OpenSquilla existantes',
    'migration.step.subtitle': 'OpenSquilla a trouvé sur cette machine des données d\'une installation précédente. Prévisualisez ce qui serait importé et récupérez-les dans l\'application de bureau, ou ignorez cette étape pour repartir de zéro.',
    'migration.step.sourceLabel': 'Emplacement des données détecté',
    'migration.step.preview': 'Aperçu de l\'importation',
    'migration.step.import': 'Importer',
    'migration.step.skip': 'Ignorer',
    'migration.overwriteTitle': 'Remplacer les données de bureau en conflit ?',
    'migration.overwriteMessage': 'Cette importation remplacera des données du profil de bureau actuel.',
    'migration.overwriteDetail': 'Une sauvegarde complète horodatée sera conservée. Vérifiez la source ci-dessous avant de continuer.',
    'migration.overwriteCancel': 'Annuler',
    'migration.overwriteConfirm': 'Importer et remplacer',
    'launch.alreadyRunningTitle': 'OpenSquilla est déjà en cours d’exécution',
    'launch.alreadyRunningMessage': 'Une autre fenêtre OpenSquilla est déjà ouverte sur cette machine. Elle va être mise au premier plan.',
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
    'onboarding.language.label': 'Langue',
    'onboarding.aria.setupSteps': 'Étapes de configuration',
    'onboarding.aria.setupDepth': 'Niveau de configuration',
    'onboarding.aria.searchProvider': 'Fournisseur de recherche',
    'onboarding.aria.language': 'Langue de l’onboarding',
    'onboarding.nav.mode.title': 'Mode',
    'onboarding.nav.mode.sub': 'Niveau de configuration',
    'onboarding.nav.provider.title': 'Fournisseur',
    'onboarding.nav.provider.sub': 'Accès aux modèles',
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
    'onboarding.step1.advancedDesc': 'Examinez les niveaux par défaut et les détails du modèle direct avant le démarrage.',
    'onboarding.step1.note': 'Vous pourrez modifier les paramètres de fournisseur, de routeur et de recherche plus tard depuis la page Paramètres du bureau.',
    'onboarding.step1.quit': 'Quitter',
    'onboarding.step1.continue': 'Continuer',
    'onboarding.step2.badge': 'Requis',
    'onboarding.step2.heading': 'Connecter un fournisseur',
    'onboarding.step2.subtitle': 'Choisissez le compte fournisseur utilisé par le runtime local pour les appels de modèle. OpenRouter est sélectionné au départ, mais tout fournisseur pris en charge peut être utilisé.',
    'onboarding.step2.apiKey': 'Clé API',
    'onboarding.step2.endpointSummary': 'Point de terminaison et modèle direct',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Modèle direct',
    'onboarding.step2.back': 'Retour',
    'onboarding.step2.next': 'Suivant',
    'onboarding.nav.routing.title': 'Routage',
    'onboarding.nav.routing.sub': 'Mode',
    'onboarding.aria.modelRoutingMode': 'Mode de routage',
    'onboarding.step3.badge': 'Avancé',
    'onboarding.step3.heading': 'Choisir le mode de routage',
    'onboarding.step3.subtitle': "Décidez si OpenSquilla doit utiliser les niveaux du Smart Router, appeler un seul modèle fixe, ou utiliser l'ensemble OpenRouter.",
    'onboarding.step3.back': 'Retour',
    'onboarding.step3.next': 'Suivant',
    'onboarding.step3.directModel': 'Modèle direct',
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
  },
  de: {
    'menu.edit': 'Bearbeiten',
    'menu.view': 'Ansicht',
    'menu.window': 'Fenster',
    'menu.checkForUpdates': 'Nach Updates suchen…',
    'menu.relaunchToUpdate': 'Zum Aktualisieren neu starten',
    'menu.downloadDiagnostics': 'Diagnose herunterladen…',
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
    'update.gatewayShutdownTimeout': 'OpenSquilla konnte die lokale Laufzeitumgebung nicht stoppen. Versuchen Sie erneut, zum Aktualisieren neu zu starten.',
    'uninstall.confirmTitle': 'Lokale OpenSquilla-Desktop-Daten löschen?',
    'uninstall.confirmMessage': 'Dies löscht das lokale Desktop-Profil auf diesem Gerät dauerhaft.',
    'uninstall.confirmDetail': 'Sitzungen, Konfiguration und Secrets werden entfernt. Die installierte App selbst bleibt erhalten; entfernen Sie sie nach dem Schließen der App über Ihr Betriebssystem.',
    'uninstall.cancel': 'Abbrechen',
    'uninstall.deleteEverything': 'Alles löschen',
    'migration.nav.title': 'Import',
    'migration.nav.sub': 'Vorhandene Daten',
    'migration.step.badge': 'Import',
    'migration.step.heading': 'Vorhandene OpenSquilla-Daten importieren',
    'migration.step.subtitle': 'OpenSquilla hat auf diesem Gerät Daten einer früheren Installation gefunden. Sehen Sie sich in der Vorschau an, was importiert würde, und übernehmen Sie die Daten in die Desktop-App — oder überspringen Sie den Schritt und beginnen Sie neu.',
    'migration.step.sourceLabel': 'Erkannter Datenspeicherort',
    'migration.step.preview': 'Import-Vorschau',
    'migration.step.import': 'Importieren',
    'migration.step.skip': 'Überspringen',
    'migration.overwriteTitle': 'Konfliktierende Desktop-Daten ersetzen?',
    'migration.overwriteMessage': 'Dieser Import ersetzt Daten im aktuellen Desktop-Profil.',
    'migration.overwriteDetail': 'Eine vollständige Sicherung mit Zeitstempel bleibt erhalten. Prüfen Sie vor dem Fortfahren die Quelle unten.',
    'migration.overwriteCancel': 'Abbrechen',
    'migration.overwriteConfirm': 'Importieren und ersetzen',
    'launch.alreadyRunningTitle': 'OpenSquilla läuft bereits',
    'launch.alreadyRunningMessage': 'Auf diesem Gerät ist bereits ein anderes OpenSquilla-Fenster geöffnet. Es wird in den Vordergrund geholt.',
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
    'onboarding.language.label': 'Sprache',
    'onboarding.aria.setupSteps': 'Einrichtungsschritte',
    'onboarding.aria.setupDepth': 'Einrichtungstiefe',
    'onboarding.aria.searchProvider': 'Suchanbieter',
    'onboarding.aria.language': 'Onboarding-Sprache',
    'onboarding.nav.mode.title': 'Modus',
    'onboarding.nav.mode.sub': 'Einrichtungstiefe',
    'onboarding.nav.provider.title': 'Anbieter',
    'onboarding.nav.provider.sub': 'Modellzugriff',
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
    'onboarding.step1.advancedDesc': 'Prüfen Sie vor dem Start die Stufenstandards und die Details des direkten Modells.',
    'onboarding.step1.note': 'Sie können Anbieter-, Router- und Sucheinstellungen später auf der Desktop-Seite Einstellungen ändern.',
    'onboarding.step1.quit': 'Beenden',
    'onboarding.step1.continue': 'Weiter',
    'onboarding.step2.badge': 'Erforderlich',
    'onboarding.step2.heading': 'Anbieter verbinden',
    'onboarding.step2.subtitle': 'Wählen Sie das Anbieterkonto, das die lokale Laufzeitumgebung für Modellaufrufe verwendet. OpenRouter ist anfangs ausgewählt, aber jeder unterstützte Anbieter kann verwendet werden.',
    'onboarding.step2.apiKey': 'API-Schlüssel',
    'onboarding.step2.endpointSummary': 'Endpunkt und direktes Modell',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Direktes Modell',
    'onboarding.step2.back': 'Zurück',
    'onboarding.step2.next': 'Weiter',
    'onboarding.nav.routing.title': 'Routing',
    'onboarding.nav.routing.sub': 'Modus',
    'onboarding.aria.modelRoutingMode': 'Routing-Modus',
    'onboarding.step3.badge': 'Erweitert',
    'onboarding.step3.heading': 'Routing-Modus wählen',
    'onboarding.step3.subtitle': 'Legen Sie fest, ob OpenSquilla die Smart-Router-Stufen verwenden, ein festes Modell aufrufen oder das OpenRouter-Ensemble nutzen soll.',
    'onboarding.step3.back': 'Zurück',
    'onboarding.step3.next': 'Weiter',
    'onboarding.step3.directModel': 'Direktes Modell',
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
  },
  es: {
    'menu.edit': 'Edición',
    'menu.view': 'Ver',
    'menu.window': 'Ventana',
    'menu.checkForUpdates': 'Buscar actualizaciones…',
    'menu.relaunchToUpdate': 'Reiniciar para actualizar',
    'menu.downloadDiagnostics': 'Descargar diagnóstico…',
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
    'update.gatewayShutdownTimeout': 'OpenSquilla no pudo detener el runtime local. Intenta reiniciar para actualizar de nuevo.',
    'uninstall.confirmTitle': '¿Eliminar los datos locales de escritorio de OpenSquilla?',
    'uninstall.confirmMessage': 'Esto elimina permanentemente el perfil de escritorio local en esta máquina.',
    'uninstall.confirmDetail': 'Se eliminarán las sesiones, la configuración y los secretos. La aplicación instalada en sí permanecerá; elimínala a través de tu sistema operativo después de cerrar la aplicación.',
    'uninstall.cancel': 'Cancelar',
    'uninstall.deleteEverything': 'Eliminar todo',
    'migration.nav.title': 'Importación',
    'migration.nav.sub': 'Datos existentes',
    'migration.step.badge': 'Importación',
    'migration.step.heading': 'Importar los datos existentes de OpenSquilla',
    'migration.step.subtitle': 'OpenSquilla encontró datos de una instalación anterior en esta máquina. Previsualiza lo que se importaría y tráelo a la aplicación de escritorio, u omite este paso y empieza de cero.',
    'migration.step.sourceLabel': 'Ubicación de datos detectada',
    'migration.step.preview': 'Vista previa de la importación',
    'migration.step.import': 'Importar',
    'migration.step.skip': 'Omitir',
    'migration.overwriteTitle': '¿Reemplazar los datos de escritorio en conflicto?',
    'migration.overwriteMessage': 'Esta importación reemplazará datos del perfil de escritorio actual.',
    'migration.overwriteDetail': 'Se conservará una copia de seguridad completa con marca de tiempo. Confirma la fuente indicada abajo antes de continuar.',
    'migration.overwriteCancel': 'Cancelar',
    'migration.overwriteConfirm': 'Importar y reemplazar',
    'launch.alreadyRunningTitle': 'OpenSquilla ya se está ejecutando',
    'launch.alreadyRunningMessage': 'Ya hay otra ventana de OpenSquilla abierta en esta máquina. Se traerá al frente.',
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
    'onboarding.language.label': 'Idioma',
    'onboarding.aria.setupSteps': 'Pasos de configuración',
    'onboarding.aria.setupDepth': 'Nivel de configuración',
    'onboarding.aria.searchProvider': 'Proveedor de búsqueda',
    'onboarding.aria.language': 'Idioma de onboarding',
    'onboarding.nav.mode.title': 'Modo',
    'onboarding.nav.mode.sub': 'Nivel de configuración',
    'onboarding.nav.provider.title': 'Proveedor',
    'onboarding.nav.provider.sub': 'Acceso a modelos',
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
    'onboarding.step1.advancedDesc': 'Revisa los valores predeterminados de niveles y los detalles del modelo directo antes del inicio.',
    'onboarding.step1.note': 'Puedes cambiar los ajustes de proveedor, enrutador y búsqueda más tarde desde la página Ajustes del escritorio.',
    'onboarding.step1.quit': 'Salir',
    'onboarding.step1.continue': 'Continuar',
    'onboarding.step2.badge': 'Obligatorio',
    'onboarding.step2.heading': 'Conectar un proveedor',
    'onboarding.step2.subtitle': 'Elige la cuenta de proveedor que usa el runtime local para las llamadas a modelos. OpenRouter empieza seleccionado, pero puedes usar cualquier proveedor compatible.',
    'onboarding.step2.apiKey': 'Clave API',
    'onboarding.step2.endpointSummary': 'Endpoint y modelo directo',
    'onboarding.step2.baseUrl': 'Base URL',
    'onboarding.step2.directModel': 'Modelo directo',
    'onboarding.step2.back': 'Atrás',
    'onboarding.step2.next': 'Siguiente',
    'onboarding.nav.routing.title': 'Enrutamiento',
    'onboarding.nav.routing.sub': 'Modo',
    'onboarding.aria.modelRoutingMode': 'Modo de enrutamiento',
    'onboarding.step3.badge': 'Avanzado',
    'onboarding.step3.heading': 'Elige el modo de enrutamiento',
    'onboarding.step3.subtitle': 'Decide si OpenSquilla debe usar los niveles del Smart Router, llamar a un único modelo fijo o usar el ensemble de OpenRouter.',
    'onboarding.step3.back': 'Atrás',
    'onboarding.step3.next': 'Siguiente',
    'onboarding.step3.directModel': 'Modelo directo',
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
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: 'Use the existing layered Squilla Router defaults for this provider.',
    modeDirectTitle: 'Direct single model',
    modeDirectDesc: 'Send every request to one provider model without tier routing or ensemble.',
    modeEnsembleTitle: 'Ensemble',
    modeEnsembleDesc: 'Use the OpenRouter static B5 ensemble and skip the tier table.',
    modeSmartRouterUnavailable: 'This provider does not have desktop tier defaults yet.',
    modeEnsembleUnavailable: 'Ensemble setup currently requires OpenRouter.',
    directModelPrompt: 'Requests will use this model directly.',
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
    directModelRequiredDirect: 'Direct model is required for Direct single model mode.',
    defaultTierRequiresModel: 'Default router tier requires a model.',
    searchApiKeyRequired: '{label} search API key is required.',
    migrationPreviewRunning: 'Checking the existing data…',
    migrationApplyRunning: 'Importing data… this can take a few minutes.',
    migrationItems: 'Items — {counts}',
    migrationPausedJobs: 'Scheduler jobs to import (arrive paused): {n}',
    migrationDisk: 'Disk: {required} required, {free} free',
    migrationNotesLabel: 'Notes',
    migrationPreviewFailed: 'Preview failed: {detail}',
    migrationApplyFailed: 'Import failed: {detail}',
    migrationDone: 'Import complete. {n} scheduler job(s) arrived paused — re-enable them in the Cron view. Your original data remains untouched at {path}.',
    stepLabel: 'Step {n}',
  },
  'zh-Hans': {
    tierDefaultsAvailable: '提供层级默认值。',
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: '使用此提供商现有的 Squilla Router 层级默认值。',
    modeDirectTitle: '直连单模型',
    modeDirectDesc: '每个请求都发送到一个固定模型，不使用层级路由或 Ensemble。',
    modeEnsembleTitle: 'Ensemble',
    modeEnsembleDesc: '使用 OpenRouter static B5 Ensemble，并跳过层级表。',
    modeSmartRouterUnavailable: '此提供商尚无桌面层级默认值。',
    modeEnsembleUnavailable: '当前 onboarding 中 Ensemble 需要 OpenRouter。',
    directModelPrompt: '请求会直接使用此模型。',
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
    directModelRequiredDirect: '直连单模型模式需要直连模型。',
    defaultTierRequiresModel: '默认路由层级需要一个模型。',
    searchApiKeyRequired: '需要 {label} 搜索 API 密钥。',
    migrationPreviewRunning: '正在检查现有数据……',
    migrationApplyRunning: '正在导入数据……可能需要几分钟。',
    migrationItems: '条目 — {counts}',
    migrationPausedJobs: '将导入的计划任务（导入后为暂停状态）：{n}',
    migrationDisk: '磁盘：需要 {required}，可用 {free}',
    migrationNotesLabel: '备注',
    migrationPreviewFailed: '预览失败：{detail}',
    migrationApplyFailed: '导入失败：{detail}',
    migrationDone: '导入完成。{n} 个计划任务已以暂停状态导入——请在 Cron 视图中重新启用。原始数据仍原样保留在 {path}。',
    stepLabel: '步骤 {n}',
  },
  ja: {
    tierDefaultsAvailable: 'ティアのデフォルトを利用できます。',
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: 'このプロバイダー向けの既存の階層化された Squilla Router のデフォルトを使用します。',
    modeDirectTitle: '直接単一モデル',
    modeDirectDesc: 'すべてのリクエストを、ティアルーティングやアンサンブルなしで 1 つのプロバイダーモデルに送信します。',
    modeEnsembleTitle: 'アンサンブル',
    modeEnsembleDesc: 'OpenRouter の static B5 アンサンブルを使用し、ティア表をスキップします。',
    modeSmartRouterUnavailable: 'このプロバイダーにはまだデスクトップ用のティアデフォルトがありません。',
    modeEnsembleUnavailable: 'アンサンブルの設定には現在 OpenRouter が必要です。',
    directModelPrompt: 'リクエストはこのモデルを直接使用します。',
    directModelRequiredDirect: '直接単一モデルモードには直接モデルが必要です。',
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
    migrationPreviewRunning: '既存データを確認しています…',
    migrationApplyRunning: 'データをインポートしています… 数分かかることがあります。',
    migrationItems: '項目 — {counts}',
    migrationPausedJobs: 'インポートされるスケジュールジョブ（一時停止状態で取り込み）: {n}',
    migrationDisk: 'ディスク: 必要 {required} / 空き {free}',
    migrationNotesLabel: '補足',
    migrationPreviewFailed: 'プレビューに失敗しました: {detail}',
    migrationApplyFailed: 'インポートに失敗しました: {detail}',
    migrationDone: 'インポートが完了しました。{n} 件のスケジュールジョブは一時停止状態で取り込まれました — Cron ビューで再度有効にしてください。元のデータは {path} にそのまま残っています。',
    stepLabel: 'ステップ {n}',
  },
  fr: {
    tierDefaultsAvailable: 'Valeurs de niveau par défaut disponibles.',
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: 'Utiliser les valeurs par défaut existantes du Squilla Router en couches pour ce fournisseur.',
    modeDirectTitle: 'Modèle unique direct',
    modeDirectDesc: 'Envoyer chaque requête à un seul modèle du fournisseur, sans routage par niveaux ni ensemble.',
    modeEnsembleTitle: 'Ensemble',
    modeEnsembleDesc: "Utiliser l'ensemble statique B5 d'OpenRouter et ignorer le tableau des niveaux.",
    modeSmartRouterUnavailable: "Ce fournisseur n'a pas encore de niveaux par défaut pour le bureau.",
    modeEnsembleUnavailable: "La configuration de l'ensemble nécessite actuellement OpenRouter.",
    directModelPrompt: 'Les requêtes utiliseront directement ce modèle.',
    directModelRequiredDirect: 'Un modèle direct est requis pour le mode Modèle unique direct.',
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
    migrationPreviewRunning: 'Vérification des données existantes…',
    migrationApplyRunning: 'Importation des données… cela peut prendre quelques minutes.',
    migrationItems: 'Éléments — {counts}',
    migrationPausedJobs: 'Tâches planifiées à importer (arrivent en pause) : {n}',
    migrationDisk: 'Disque : {required} requis, {free} libres',
    migrationNotesLabel: 'Remarques',
    migrationPreviewFailed: "Échec de l'aperçu : {detail}",
    migrationApplyFailed: "Échec de l'importation : {detail}",
    migrationDone: "Importation terminée. {n} tâche(s) planifiée(s) sont arrivées en pause — réactivez-les dans la vue Cron. Vos données d'origine restent intactes dans {path}.",
    stepLabel: 'Étape {n}',
  },
  de: {
    tierDefaultsAvailable: 'Stufenstandards verfügbar.',
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: 'Die vorhandenen mehrstufigen Squilla-Router-Standards für diesen Anbieter verwenden.',
    modeDirectTitle: 'Einzelnes Direktmodell',
    modeDirectDesc: 'Jede Anfrage an ein einzelnes Anbietermodell senden, ohne Stufenrouting oder Ensemble.',
    modeEnsembleTitle: 'Ensemble',
    modeEnsembleDesc: 'Das statische B5-Ensemble von OpenRouter verwenden und die Stufentabelle überspringen.',
    modeSmartRouterUnavailable: 'Dieser Anbieter hat noch keine Desktop-Stufenstandards.',
    modeEnsembleUnavailable: 'Die Ensemble-Einrichtung erfordert derzeit OpenRouter.',
    directModelPrompt: 'Anfragen verwenden dieses Modell direkt.',
    directModelRequiredDirect: 'Für den Modus „Einzelnes Direktmodell“ ist ein direktes Modell erforderlich.',
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
    migrationPreviewRunning: 'Vorhandene Daten werden geprüft…',
    migrationApplyRunning: 'Daten werden importiert… das kann einige Minuten dauern.',
    migrationItems: 'Elemente — {counts}',
    migrationPausedJobs: 'Zu importierende Scheduler-Jobs (kommen pausiert an): {n}',
    migrationDisk: 'Speicher: {required} benötigt, {free} frei',
    migrationNotesLabel: 'Hinweise',
    migrationPreviewFailed: 'Vorschau fehlgeschlagen: {detail}',
    migrationApplyFailed: 'Import fehlgeschlagen: {detail}',
    migrationDone: 'Import abgeschlossen. {n} Scheduler-Job(s) sind pausiert angekommen — aktivieren Sie sie in der Cron-Ansicht wieder. Ihre ursprünglichen Daten bleiben unverändert unter {path}.',
    stepLabel: 'Schritt {n}',
  },
  es: {
    tierDefaultsAvailable: 'Valores de nivel predeterminados disponibles.',
    modeSmartRouterTitle: 'Smart Router',
    modeSmartRouterDesc: 'Usar los valores predeterminados por niveles existentes del Squilla Router para este proveedor.',
    modeDirectTitle: 'Modelo único directo',
    modeDirectDesc: 'Enviar cada solicitud a un único modelo del proveedor, sin enrutamiento por niveles ni ensemble.',
    modeEnsembleTitle: 'Ensemble',
    modeEnsembleDesc: 'Usar el ensemble estático B5 de OpenRouter y omitir la tabla de niveles.',
    modeSmartRouterUnavailable: 'Este proveedor aún no tiene valores de nivel predeterminados para el escritorio.',
    modeEnsembleUnavailable: 'La configuración del ensemble requiere actualmente OpenRouter.',
    directModelPrompt: 'Las solicitudes usarán este modelo directamente.',
    directModelRequiredDirect: 'Se requiere un modelo directo para el modo Modelo único directo.',
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
    migrationPreviewRunning: 'Comprobando los datos existentes…',
    migrationApplyRunning: 'Importando datos… esto puede tardar unos minutos.',
    migrationItems: 'Elementos — {counts}',
    migrationPausedJobs: 'Tareas programadas a importar (llegan en pausa): {n}',
    migrationDisk: 'Disco: {required} necesarios, {free} libres',
    migrationNotesLabel: 'Notas',
    migrationPreviewFailed: 'Error en la vista previa: {detail}',
    migrationApplyFailed: 'Error en la importación: {detail}',
    migrationDone: 'Importación completada. {n} tarea(s) programada(s) llegaron en pausa: vuelve a activarlas en la vista Cron. Tus datos originales permanecen intactos en {path}.',
    stepLabel: 'Paso {n}',
  },
}

function desktopT(key: string): string {
  return DESKTOP_MESSAGES[desktopLocale][key] ?? DESKTOP_MESSAGES.en[key] ?? key
}

function createApplicationMenu(): void {
  if (!shouldUseNativeApplicationMenu) {
    Menu.setApplicationMenu(null)
    return
  }
  const appSubmenu: Electron.MenuItemConstructorOptions[] = [{ role: 'about' }]
  if (desktopUpdateMenuEnabled()) {
    appSubmenu.push({ type: 'separator' })
    if (downloadedUpdateVersion !== null) {
      appSubmenu.push(
        {
          label: desktopT('menu.relaunchToUpdate'),
          click: () => {
            void applyDownloadedUpdate()
          },
        },
        { type: 'separator' },
      )
    }
    appSubmenu.push({
      label: desktopT('menu.checkForUpdates'),
      click: () => {
        void checkForUpdates(true)
      },
    })
  }
  appSubmenu.push(
    { type: 'separator' },
    {
      label: desktopT('menu.downloadDiagnostics'),
      click: () => {
        void downloadDiagnostics()
      },
    },
  )
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
        // Disable reload while the onboarding wizard is open: its state lives only
        // in the renderer of a one-shot data: URL, so a reload would silently wipe
        // the in-progress setup (typed key, provider, step, tier edits).
        { role: 'reload', enabled: currentOnboardingWindow() === null },
        { role: 'forceReload', enabled: currentOnboardingWindow() === null },
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

function localeOptionsHtml(): string {
  return DESKTOP_LOCALES.map((locale) => (
    `<option value="${escapeHtmlServer(locale)}"${locale === desktopLocale ? ' selected' : ''}>${escapeHtmlServer(DESKTOP_LOCALE_LABELS[locale])}</option>`
  )).join('')
}

function onboardingHtml(
  detection: LegacyImportCandidate | null = null,
  pendingProviderSetup: MigrationProviderPrefill | null = null,
): string {
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
      --accent: #F26A1B;
      --accent-dark: #D95A11;
      --accent-soft: rgba(242, 106, 27, 0.08);
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
      box-shadow: 0 9px 18px rgba(242, 106, 27, 0.2);
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
    .rail-bottom {
      display: grid;
      gap: 14px;
    }
    .language-picker {
      display: grid;
      gap: 7px;
      color: #565c54;
      font-size: 11px;
      font-weight: 700;
    }
    .language-picker select {
      min-height: 34px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 650;
      padding: 0 10px;
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
    .setup-card[data-screen="0"] .card-body {
      overflow: visible;
    }
    .provider-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .provider-picker {
      min-height: 0;
      max-height: min(310px, 42vh);
      overflow-x: hidden;
      overflow-y: auto;
      padding-right: 3px;
    }
    .provider-picker .provider-grid {
      padding-bottom: 2px;
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
      border-color: rgba(242,106,27,0.3);
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
      border: 1px solid rgba(242,106,27,0.14);
      border-radius: 999px;
      background: rgba(242,106,27,0.06);
      color: var(--accent-dark);
      font-size: 9px;
      font-weight: 750;
      letter-spacing: 0.06em;
      padding: 3px 6px;
      text-transform: uppercase;
    }
    .choice-row, .tier-defaults {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
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
      box-shadow: 0 0 0 3px rgba(242, 106, 27, 0.12);
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
	    .endpoint-panel {
	      border: 1px solid #e2e0da;
	      border-radius: 8px;
	      background: rgba(255,255,255,0.46);
	      overflow: hidden;
	      transition: border-color 180ms ease, background 180ms ease, box-shadow 180ms ease;
	    }
	    .endpoint-panel.open {
	      border-color: rgba(242,106,27,0.22);
	      background: rgba(255,255,255,0.68);
	      box-shadow: 0 10px 24px rgba(44,38,28,0.05);
	    }
	    .endpoint-summary {
	      appearance: none;
	      width: 100%;
	      min-height: 42px;
	      display: flex;
	      align-items: center;
	      gap: 9px;
	      border: 0;
	      background: transparent;
	      color: #656b64;
	      cursor: pointer;
	      font: inherit;
	      font-size: 12px;
	      font-weight: 650;
	      padding: 0 13px;
	      text-align: left;
	    }
	    .endpoint-summary::before {
	      content: "";
	      width: 7px;
	      height: 7px;
	      border-right: 2px solid #747a73;
	      border-bottom: 2px solid #747a73;
	      transform: rotate(-45deg);
	      transition: transform 180ms ease, border-color 180ms ease;
	    }
	    .endpoint-panel.open .endpoint-summary::before {
	      border-color: var(--accent-dark);
	      transform: rotate(45deg);
	    }
	    .endpoint-summary:focus-visible {
	      outline: none;
	      box-shadow: inset 0 0 0 3px rgba(242, 106, 27, 0.12);
	    }
	    .endpoint-content {
	      display: grid;
	      grid-template-rows: 0fr;
	      opacity: 0;
	      transform: translateY(-4px);
	      transition: grid-template-rows 220ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 160ms ease, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
	    }
	    .endpoint-panel.open .endpoint-content {
	      grid-template-rows: 1fr;
	      opacity: 1;
	      transform: translateY(0);
	    }
	    .endpoint-content-clip {
	      min-height: 0;
	      overflow: hidden;
	    }
	    .endpoint-fields {
	      padding: 2px 13px 13px;
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
      border: 1px solid rgba(242,106,27,0.13);
      border-radius: 8px;
      background: rgba(242,106,27,0.055);
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
      box-shadow: 0 13px 28px rgba(242, 106, 27, 0.22);
      min-width: 150px;
    }
    .primary:hover {
      transform: translateY(-1px);
    }
    .primary:disabled { opacity: 0.55; cursor: not-allowed; }
    .migration-buttons {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .migration-status {
      display: flex;
      align-items: center;
      gap: 9px;
    }
    .migration-spinner {
      width: 14px;
      height: 14px;
      flex: none;
      border: 2px solid rgba(242, 106, 27, 0.25);
      border-top-color: var(--accent);
      border-radius: 999px;
      animation: migration-spin 0.8s linear infinite;
    }
    @keyframes migration-spin {
      to { transform: rotate(360deg); }
    }
    .migration-path {
      display: block;
      margin-top: 5px;
      font-size: 12px;
      word-break: break-all;
    }
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
        <h1 data-i18n="onboarding.rail.title">${ot('onboarding.rail.title')}</h1>
        <p data-i18n="onboarding.rail.subtitle">${ot('onboarding.rail.subtitle')}</p>
      </section>
      <nav class="progress" aria-label="${ot('onboarding.aria.setupSteps')}" data-i18n-aria="onboarding.aria.setupSteps">
        ${detection ? `<button class="step active" type="button" data-step-label="5">
          <span class="step-index">1</span>
          <span><strong data-i18n="migration.nav.title">${ot('migration.nav.title')}</strong><span data-i18n="migration.nav.sub">${ot('migration.nav.sub')}</span></span>
        </button>` : ''}
        <button class="step${detection ? '' : ' active'}" type="button" data-step-label="0">
          <span class="step-index">1</span>
          <span><strong data-i18n="onboarding.nav.mode.title">${ot('onboarding.nav.mode.title')}</strong><span data-i18n="onboarding.nav.mode.sub">${ot('onboarding.nav.mode.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="1">
          <span class="step-index">2</span>
          <span><strong data-i18n="onboarding.nav.provider.title">${ot('onboarding.nav.provider.title')}</strong><span data-i18n="onboarding.nav.provider.sub">${ot('onboarding.nav.provider.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="2" data-advanced-step>
          <span class="step-index">3</span>
          <span><strong data-i18n="onboarding.nav.routing.title">${ot('onboarding.nav.routing.title')}</strong><span data-i18n="onboarding.nav.routing.sub">${ot('onboarding.nav.routing.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="3" data-advanced-step>
          <span class="step-index">4</span>
          <span><strong data-i18n="onboarding.nav.tiers.title">${ot('onboarding.nav.tiers.title')}</strong><span data-i18n="onboarding.nav.tiers.sub">${ot('onboarding.nav.tiers.sub')}</span></span>
        </button>
        <button class="step" type="button" data-step-label="4">
          <span class="step-index">4</span>
          <span><strong data-i18n="onboarding.nav.search.title">${ot('onboarding.nav.search.title')}</strong><span data-i18n="onboarding.nav.search.sub">${ot('onboarding.nav.search.sub')}</span></span>
        </button>
      </nav>
      <div class="rail-bottom">
        <label class="language-picker" for="onboardingLocale">
          <span data-i18n="onboarding.language.label">${ot('onboarding.language.label')}</span>
          <select id="onboardingLocale" aria-label="${ot('onboarding.aria.language')}" data-i18n-aria="onboarding.aria.language">
            ${localeOptionsHtml()}
          </select>
        </label>
        <div class="rail-foot" data-i18n="onboarding.rail.foot">${ot('onboarding.rail.foot')}</div>
      </div>
    </aside>
    <form id="setup-form" class="deck">
      ${detection ? `<section class="setup-card active" data-screen="5">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 01</p>
            <h2 data-i18n="migration.step.heading">${ot('migration.step.heading')}</h2>
            <p data-i18n="migration.step.subtitle">${ot('migration.step.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="migration.step.badge">${ot('migration.step.badge')}</span>
        </header>
        <div class="card-body">
          <div class="note"><span data-i18n="migration.step.sourceLabel">${ot('migration.step.sourceLabel')}</span><code class="migration-path">${escapeHtmlServer(detection.path)}</code></div>
          <div class="note migration-status" id="migrationStatus" hidden><span class="migration-spinner"></span><span id="migrationStatusLabel"></span></div>
          <div class="note" id="migrationSummary" hidden></div>
          <div class="note" id="migrationDoneNote" hidden></div>
        </div>
        <footer class="actions">
          <button class="secondary" type="button" id="migrationSkip" data-i18n="migration.step.skip">${ot('migration.step.skip')}</button>
          <div class="migration-buttons">
            <button class="secondary" type="button" id="migrationPreview" data-i18n="migration.step.preview">${ot('migration.step.preview')}</button>
            <button class="primary" type="button" id="migrationImport" data-i18n="migration.step.import" disabled>${ot('migration.step.import')}</button>
          </div>
        </footer>
      </section>` : ''}
      <section class="setup-card${detection ? '' : ' active'}" data-screen="0">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 01</p>
            <h2 data-i18n="onboarding.step1.heading">${ot('onboarding.step1.heading')}</h2>
            <p data-i18n="onboarding.step1.subtitle">${ot('onboarding.step1.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="onboarding.step1.badge">${ot('onboarding.step1.badge')}</span>
        </header>
        <div class="card-body">
          <div class="setup-mode-grid" role="radiogroup" aria-label="${ot('onboarding.aria.setupDepth')}" data-i18n-aria="onboarding.aria.setupDepth">
            <button class="choice active" type="button" data-setup-mode="simple">
              <strong data-i18n="onboarding.step1.simpleTitle">${ot('onboarding.step1.simpleTitle')}</strong>
              <small data-i18n="onboarding.step1.simpleDesc">${ot('onboarding.step1.simpleDesc')}</small>
            </button>
            <button class="choice" type="button" data-setup-mode="advanced">
              <strong data-i18n="onboarding.step1.advancedTitle">${ot('onboarding.step1.advancedTitle')}</strong>
              <small data-i18n="onboarding.step1.advancedDesc">${ot('onboarding.step1.advancedDesc')}</small>
            </button>
          </div>
          <input id="setupMode" type="hidden" value="simple" />
          <div class="note" data-i18n="onboarding.step1.note">${ot('onboarding.step1.note')}</div>
        </div>
        <footer class="actions">
          <button class="secondary" type="button" id="cancel" data-i18n="onboarding.step1.quit">${ot('onboarding.step1.quit')}</button>
          <button class="primary next-button" type="button" data-i18n="onboarding.step1.continue">${ot('onboarding.step1.continue')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="1">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 02</p>
            <h2 data-i18n="onboarding.step2.heading">${ot('onboarding.step2.heading')}</h2>
            <p data-i18n="onboarding.step2.subtitle">${ot('onboarding.step2.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="onboarding.step2.badge">${ot('onboarding.step2.badge')}</span>
        </header>
        <div class="card-body">
        <div class="provider-picker">
          <div class="provider-grid" id="providerGrid"></div>
        </div>
        <input id="provider" type="hidden" value="openrouter" />
        <input id="routerMode" type="hidden" value="recommended" />
        <label>
          <span data-i18n="onboarding.step2.apiKey">${ot('onboarding.step2.apiKey')}</span>
          <input id="apiKey" name="apiKey" type="password" autocomplete="off" placeholder="sk-..." />
        </label>
        <div class="endpoint-panel" id="endpointPanel">
          <button class="endpoint-summary" id="endpointToggle" type="button" aria-expanded="false" aria-controls="endpointContent">
            <span data-i18n="onboarding.step2.endpointSummary">${ot('onboarding.step2.endpointSummary')}</span>
          </button>
          <div class="endpoint-content" id="endpointContent" aria-hidden="true">
            <div class="endpoint-content-clip">
              <div class="field-pair endpoint-fields">
                <label>
                  <span data-i18n="onboarding.step2.baseUrl">${ot('onboarding.step2.baseUrl')}</span>
                  <input id="baseUrl" name="baseUrl" autocomplete="off" />
                </label>
                <label>
                  <span data-i18n="onboarding.step2.directModel">${ot('onboarding.step2.directModel')}</span>
                  <input id="model" name="model" autocomplete="off" />
                </label>
              </div>
            </div>
          </div>
        </div>
        <div class="note" id="providerHint"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button" data-i18n="onboarding.step2.back">${ot('onboarding.step2.back')}</button>
          <button class="primary next-button" type="button" data-i18n="onboarding.step2.next">${ot('onboarding.step2.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="2">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 03</p>
            <h2 data-i18n="onboarding.step3.heading">${ot('onboarding.step3.heading')}</h2>
            <p data-i18n="onboarding.step3.subtitle">${ot('onboarding.step3.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="onboarding.step3.badge">${ot('onboarding.step3.badge')}</span>
        </header>
        <div class="card-body">
          <div class="choice-row" id="modelRoutingModeGrid" role="radiogroup" aria-label="${ot('onboarding.aria.modelRoutingMode')}" data-i18n-aria="onboarding.aria.modelRoutingMode"></div>
          <input id="modelRoutingMode" type="hidden" value="squilla_router" />
          <div id="directModelPanel" hidden>
            <label>
              <span data-i18n="onboarding.step3.directModel">${ot('onboarding.step3.directModel')}</span>
              <input id="directModelRoute" autocomplete="off" />
            </label>
            <div class="note" id="directModelHint"></div>
          </div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button" data-i18n="onboarding.step3.back">${ot('onboarding.step3.back')}</button>
          <button class="primary next-button" type="button" data-i18n="onboarding.step3.next">${ot('onboarding.step3.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="3">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 03</p>
            <h2 data-i18n="onboarding.step4.heading">${ot('onboarding.step4.heading')}</h2>
            <p data-i18n="onboarding.step4.subtitle">${ot('onboarding.step4.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="onboarding.step4.badge">${ot('onboarding.step4.badge')}</span>
        </header>
        <div class="card-body">
          <div id="tierBody"></div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button" data-i18n="onboarding.step4.back">${ot('onboarding.step4.back')}</button>
          <button class="primary next-button" type="button" data-i18n="onboarding.step4.next">${ot('onboarding.step4.next')}</button>
        </footer>
      </section>
      <section class="setup-card" data-screen="4">
        <header class="card-head">
          <div>
            <p class="eyebrow">Step 04</p>
            <h2 data-i18n="onboarding.step5.heading">${ot('onboarding.step5.heading')}</h2>
            <p data-i18n="onboarding.step5.subtitle">${ot('onboarding.step5.subtitle')}</p>
          </div>
          <span class="card-badge" data-i18n="onboarding.step5.badge">${ot('onboarding.step5.badge')}</span>
        </header>
        <div class="card-body">
        <div class="choice-row" id="searchProviderGrid" role="radiogroup" aria-label="${ot('onboarding.aria.searchProvider')}" data-i18n-aria="onboarding.aria.searchProvider"></div>
        <input id="searchProvider" type="hidden" value="duckduckgo" />
        <label id="searchKeyLabel" hidden>
          <span data-i18n="onboarding.step5.searchKey">${ot('onboarding.step5.searchKey')}</span>
          <input id="searchApiKey" name="searchApiKey" type="password" autocomplete="off" placeholder="SEARCH_API_KEY" />
        </label>
        <div class="note" id="searchHint" data-i18n="onboarding.step5.searchHintDefault">${ot('onboarding.step5.searchHintDefault')}</div>
        </div>
        <footer class="actions">
          <button class="secondary back-button" type="button" data-i18n="onboarding.step5.back">${ot('onboarding.step5.back')}</button>
          <button class="primary" type="button" id="finish" data-i18n="onboarding.step5.finish">${ot('onboarding.step5.finish')}</button>
        </footer>
      </section>
      <div class="error" id="error"></div>
    </form>
  </main>
  <script>
    const desktopMessages = ${JSON.stringify(DESKTOP_MESSAGES)};
    const onboardingMessageCatalog = ${JSON.stringify(ONBOARDING_SCRIPT_MESSAGES)};
    const providerNoteCatalog = ${JSON.stringify(PROVIDER_NOTE_MESSAGES)};
    const searchNoteCatalog = ${JSON.stringify(SEARCH_PROVIDER_NOTE_MESSAGES)};
    let activeLocale = ${JSON.stringify(desktopLocale)};
    let t = messagesFor(activeLocale);
    function messagesFor(locale) {
      return Object.assign({}, onboardingMessageCatalog.en, onboardingMessageCatalog[locale] || {});
    }
    function desktopMessage(locale, key) {
      return (desktopMessages[locale] && desktopMessages[locale][key]) || desktopMessages.en[key] || key;
    }
    function fmt(key, vars) {
      let out = t[key] != null ? String(t[key]) : key;
      if (vars) for (const name of Object.keys(vars)) out = out.split('{' + name + '}').join(String(vars[name]));
      return out;
    }
    const providers = ${JSON.stringify(PROVIDER_CATALOG)};
    const searchProviders = ${JSON.stringify(SEARCH_PROVIDER_CATALOG)};
    const routerProfiles = ${JSON.stringify(ROUTER_PROFILES)};
    const textTiers = ${JSON.stringify(TEXT_ROUTER_TIERS)};
    const migrationCandidate = ${JSON.stringify(detection)};
    const initialProviderPrefill = ${JSON.stringify(pendingProviderSetup)};
    let step = ${detection ? 5 : 0};
    let routerTiers = clone(routerProfiles.openrouter);
    const setupMode = document.getElementById('setupMode');
    const provider = document.getElementById('provider');
    const baseUrl = document.getElementById('baseUrl');
    const model = document.getElementById('model');
    const providerHint = document.getElementById('providerHint');
    const modelRoutingMode = document.getElementById('modelRoutingMode');
    const modelRoutingModeGrid = document.getElementById('modelRoutingModeGrid');
    const directModelPanel = document.getElementById('directModelPanel');
    const directModelRoute = document.getElementById('directModelRoute');
    const directModelHint = document.getElementById('directModelHint');
    const routerMode = document.getElementById('routerMode');
    const tierBody = document.getElementById('tierBody');
    const searchHint = document.getElementById('searchHint');
    const errorBox = document.getElementById('error');
    const finish = document.getElementById('finish');
    const searchProvider = document.getElementById('searchProvider');
	    const searchProviderGrid = document.getElementById('searchProviderGrid');
	    const searchKeyLabel = document.getElementById('searchKeyLabel');
	    const onboardingLocale = document.getElementById('onboardingLocale');
	    const endpointPanel = document.getElementById('endpointPanel');
	    const endpointToggle = document.getElementById('endpointToggle');
	    const endpointContent = document.getElementById('endpointContent');
    function clone(value) {
      return JSON.parse(JSON.stringify(value || {}));
    }
    function currentProvider() {
      return providers.find((item) => item.id === provider.value) || providers[0];
    }
    function providerNote(item) {
      return (providerNoteCatalog[activeLocale] && providerNoteCatalog[activeLocale][item.id])
        || (providerNoteCatalog.en && providerNoteCatalog.en[item.id])
        || item.note
        || '';
    }
    function modelRoutingCapabilities(selected) {
      return {
        squilla_router: Boolean(selected.routerSupported),
        direct: true,
        llm_ensemble: selected.id === 'openrouter',
      };
    }
    function defaultModelRoutingModeFor(selected) {
      return selected.routerSupported ? 'squilla_router' : 'direct';
    }
    function syncRouterModeFromModelRouting() {
      routerMode.value = modelRoutingMode.value === 'direct' ? 'disabled' : 'recommended';
    }
	    function profileKeyForMode() {
	      if (modelRoutingMode.value === 'llm_ensemble') return 'openrouter';
	      return provider.value;
	    }
	    function setEndpointPanelOpen(open) {
	      endpointPanel.classList.toggle('open', open);
	      endpointToggle.setAttribute('aria-expanded', String(open));
	      endpointContent.setAttribute('aria-hidden', String(!open));
	    }
	    function syncProviderDefaults(resetRouter) {
	      const selected = currentProvider();
	      if (resetRouter) {
	        baseUrl.value = selected.baseUrl || '';
	        model.value = selected.model || '';
	      } else {
	        if (!baseUrl.value && selected.baseUrl) baseUrl.value = selected.baseUrl;
	        if (!model.value && selected.model) model.value = selected.model;
	      }
	      providerHint.textContent = providerNote(selected);
	      if (resetRouter) {
	        modelRoutingMode.value = defaultModelRoutingModeFor(selected);
	        syncRouterModeFromModelRouting();
	        routerTiers = clone(routerProfiles[profileKeyForMode()]);
	        setEndpointPanelOpen(routerMode.value === 'disabled' && !model.value.trim());
	      }
	      renderModelRoutingModeGrid();
	      renderTiers();
	    }
    function renderProviderGrid() {
      const grid = document.getElementById('providerGrid');
      grid.classList.toggle('single-provider', providers.length === 1);
      grid.innerHTML = providers.map((item) => (
        '<button class="provider' + (item.id === provider.value ? ' active' : '') + '" type="button" data-provider="' + escapeAttr(item.id) + '">' +
        '<span class="provider-tag">' + escapeHtml(t.providerField) + '</span><strong>' + escapeHtml(item.label) + '</strong><small>' + escapeHtml(item.routerSupported ? t.tierDefaultsAvailable : providerNote(item)) + '</small></button>'
      )).join('');
      function selectProvider(nextProvider) {
	        const next = nextProvider || 'openrouter';
	        // Re-clicking the already-active provider must not reset base URL, model,
	        // routing mode, and customized tiers back to catalog defaults.
	        if (next === provider.value) return;
	        provider.value = next;
	        errorBox.textContent = '';
	        syncProviderDefaults(true);
	        renderProviderGrid();
	        render();
	      }
      const bindProviderButton = (button) => {
        button.addEventListener('click', () => selectProvider(button.dataset.provider || 'openrouter'));
      };
      grid.querySelectorAll('.provider').forEach(bindProviderButton);
    }
    function renderModelRoutingModeGrid() {
      const selected = currentProvider();
      const capabilities = modelRoutingCapabilities(selected);
      if (!capabilities[modelRoutingMode.value]) {
        modelRoutingMode.value = defaultModelRoutingModeFor(selected);
      }
      syncRouterModeFromModelRouting();
      const modes = [
        { id: 'squilla_router', title: t.modeSmartRouterTitle, desc: t.modeSmartRouterDesc, disabledReason: t.modeSmartRouterUnavailable },
        { id: 'direct', title: t.modeDirectTitle, desc: t.modeDirectDesc, disabledReason: '' },
        { id: 'llm_ensemble', title: t.modeEnsembleTitle, desc: t.modeEnsembleDesc, disabledReason: t.modeEnsembleUnavailable },
      ];
      modelRoutingModeGrid.innerHTML = modes.map((mode) => {
        const enabled = Boolean(capabilities[mode.id]);
        const active = mode.id === modelRoutingMode.value;
        const desc = enabled ? mode.desc : mode.disabledReason;
        return '<button class="choice' + (active ? ' active' : '') + '" type="button" data-model-routing-mode="' + escapeAttr(mode.id) + '"' + (enabled ? '' : ' disabled') + '>' +
          '<strong>' + escapeHtml(mode.title) + '</strong><small>' + escapeHtml(desc) + '</small></button>';
      }).join('');
      modelRoutingModeGrid.querySelectorAll('[data-model-routing-mode]').forEach((button) => {
        button.addEventListener('click', () => {
          if (button.disabled) return;
          modelRoutingMode.value = button.dataset.modelRoutingMode || 'squilla_router';
          syncRouterModeFromModelRouting();
          if (modelRoutingMode.value === 'direct') setEndpointPanelOpen(true);
          errorBox.textContent = '';
          renderModelRoutingModeGrid();
          render();
        });
      });
      directModelPanel.hidden = modelRoutingMode.value !== 'direct';
      directModelRoute.value = model.value;
      directModelHint.textContent = t.directModelPrompt;
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
      const defaultTier = document.getElementById('routerDefaultTier')?.value || 'c1';
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
          document.getElementById('routerDefaultTier').value = button.dataset.defaultTier || 'c1';
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
    function applyLocale(nextLocale) {
      const locale = desktopMessages[nextLocale] ? nextLocale : 'en';
      activeLocale = locale;
      t = messagesFor(locale);
      document.documentElement.lang = locale;
      document.title = desktopMessage(locale, 'onboarding.title');
      document.querySelectorAll('[data-i18n]').forEach((element) => {
        element.textContent = desktopMessage(locale, element.dataset.i18n);
      });
      document.querySelectorAll('[data-i18n-aria]').forEach((element) => {
        element.setAttribute('aria-label', desktopMessage(locale, element.dataset.i18nAria));
      });
      renderProviderGrid();
      renderSearchProviderGrid();
      syncProviderDefaults(false);
      render();
    }
    function shortModel(value) {
      const text = String(value || '');
      const parts = text.split('/');
      return parts[parts.length - 1] || text;
    }
    function currentSearchProvider() {
      return searchProviders.find((item) => item.providerId === searchProvider.value) || searchProviders[0];
    }
    function searchProviderNote(item) {
      return (searchNoteCatalog[activeLocale] && searchNoteCatalog[activeLocale][item.providerId])
        || (searchNoteCatalog.en && searchNoteCatalog.en[item.providerId])
        || item.note
        || (item.requiresApiKey ? t.requiresApiKey : t.noKeyRequired);
    }
    function renderSearchProviderGrid() {
      searchProviderGrid.innerHTML = searchProviders.map((item) => (
        '<button class="choice' + (item.providerId === searchProvider.value ? ' active' : '') + '" type="button" data-search-provider="' + escapeAttr(item.providerId) + '">' +
        '<strong>' + escapeHtml(item.label) + '</strong><small>' + escapeHtml(searchProviderNote(item)) + '</small></button>'
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
      searchHint.textContent = searchProviderNote(selected);
    }
    function isSimpleSetup() {
      return setupMode.value === 'simple';
    }
    function routeSteps() {
      const base = isSimpleSetup()
        ? [0, 1, 4]
        : modelRoutingMode.value === 'squilla_router'
          ? [0, 1, 2, 3, 4]
          : [0, 1, 2, 4];
      // The migration step (screen 5) leads the route only when a legacy home
      // was detected; render() renumbers and hides rail entries automatically.
      return migrationCandidate ? [5, ...base] : base;
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
	        item.hidden = itemRouteIndex < 0;
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
      renderModelRoutingModeGrid();
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
	    onboardingLocale.addEventListener('change', () => {
	      errorBox.textContent = '';
	      applyLocale(onboardingLocale.value);
	    });
	    endpointToggle.addEventListener('click', () => {
	      setEndpointPanelOpen(!endpointPanel.classList.contains('open'));
	    });
	    directModelRoute.addEventListener('input', () => {
	      model.value = directModelRoute.value;
	    });
	    function validateStep() {
      const selected = currentProvider();
      const selectedSearch = currentSearchProvider();
      if (step === 1 && selected.requiresApiKey && !document.getElementById('apiKey').value.trim()) return fmt('apiKeyRequired', { label: selected.label });
      // Direct mode needs a model. In Simple setup the routing screen (step 2) is
      // not in the route, so the model is entered on the provider screen (step 1);
      // validate on whichever step is actually reachable, or the check silently
      // never runs and the save fails late with a raw main-process error.
      if (modelRoutingMode.value === 'direct' && !model.value.trim()) {
        if (isSimpleSetup() && step === 1) return t.directModelRequiredDirect;
        if (!isSimpleSetup() && step === 2) return t.directModelRequiredDirect;
      }
      if (step === 3 && modelRoutingMode.value === 'squilla_router') {
        const defaultTier = document.getElementById('routerDefaultTier')?.value || 'c1';
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
          modelRoutingMode: modelRoutingMode.value,
          routerMode: routerMode.value,
          routerDefaultTier: document.getElementById('routerDefaultTier')?.value || 'c1',
          routerTiers,
          searchProvider: searchProvider.value,
          searchApiKey: document.getElementById('searchApiKey').value,
          locale: activeLocale,
        });
      } catch (error) {
        errorBox.textContent = error && error.message ? error.message : String(error);
      }
    });
    if (migrationCandidate) {
      const migrationPreviewButton = document.getElementById('migrationPreview');
      const migrationImportButton = document.getElementById('migrationImport');
      const migrationSkipButton = document.getElementById('migrationSkip');
      const migrationStatus = document.getElementById('migrationStatus');
      const migrationStatusLabel = document.getElementById('migrationStatusLabel');
      const migrationSummary = document.getElementById('migrationSummary');
      const migrationDoneNote = document.getElementById('migrationDoneNote');
      let migrationBusy = false;
      let migrationPreviewOk = false;
      function setMigrationStatus(label) {
        if (label) {
          migrationStatusLabel.textContent = label;
          migrationStatus.hidden = false;
        } else {
          migrationStatus.hidden = true;
        }
      }
      function formatMigrationBytes(value) {
        const bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes < 0) return '?';
        if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
        if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return String(Math.round(bytes)) + ' B';
      }
      function migrationErrorDetail(result, errors) {
        if (errors && errors.length) {
          return errors.map((item) => String((item && (item.reason || item.kind)) || '')).filter(Boolean).join('; ');
        }
        if (result && result.error) return String(result.error);
        if (result && result.raw) return String(result.raw).slice(-400);
        return '';
      }
      function renderMigrationReport(report) {
        if (!report || typeof report !== 'object') {
          migrationSummary.hidden = true;
          return [];
        }
        const items = Array.isArray(report.items) ? report.items : [];
        const counts = {};
        for (const item of items) {
          const status = String((item && item.status) || 'unknown');
          counts[status] = (counts[status] || 0) + 1;
        }
        const countsText = Object.keys(counts).sort().map((status) => status + ': ' + counts[status]).join(', ') || '0';
        const pausedCount = Array.isArray(report.paused_jobs) ? report.paused_jobs.length : 0;
        const preflight = (report.preflight && typeof report.preflight === 'object') ? report.preflight : {};
        const lines = [
          fmt('migrationItems', { counts: countsText }),
          fmt('migrationPausedJobs', { n: pausedCount }),
          fmt('migrationDisk', {
            required: formatMigrationBytes(preflight.disk_required_bytes),
            free: formatMigrationBytes(preflight.disk_free_bytes),
          }),
        ];
        const notes = Array.isArray(report.notes) ? report.notes : [];
        migrationSummary.innerHTML = lines.map((line) => '<div>' + escapeHtml(line) + '</div>').join('')
          + (notes.length
            ? '<div>' + escapeHtml(t.migrationNotesLabel) + ': ' + escapeHtml(notes.map((note) => String(note)).join(' | ')) + '</div>'
            : '');
        migrationSummary.hidden = false;
        return items.filter((item) => item && item.status === 'error');
      }
      function applyMigrationPrefill(prefill) {
        if (!prefill || typeof prefill !== 'object') return;
        const nextProvider = String(prefill.provider || '').trim().toLowerCase();
        if (nextProvider && nextProvider !== provider.value) {
          provider.value = nextProvider;
          syncProviderDefaults(true);
          renderProviderGrid();
        }
        if (prefill.baseUrl) baseUrl.value = String(prefill.baseUrl);
        if (prefill.model) model.value = String(prefill.model);
        if (prefill.apiKey) document.getElementById('apiKey').value = String(prefill.apiKey);
        syncProviderDefaults(false);
        render();
      }
      applyMigrationPrefill(initialProviderPrefill);
      if (typeof window.opensquillaDesktop.onMigrationProgress === 'function') {
        window.opensquillaDesktop.onMigrationProgress((payload) => {
          const phase = payload && payload.phase;
          if (phase === 'preview') setMigrationStatus(t.migrationPreviewRunning);
          else if (phase === 'applying') setMigrationStatus(t.migrationApplyRunning);
          else setMigrationStatus('');
        });
      }
      migrationPreviewButton.addEventListener('click', async () => {
        if (migrationBusy) return;
        migrationBusy = true;
        migrationPreviewOk = false;
        errorBox.textContent = '';
        migrationDoneNote.hidden = true;
        migrationPreviewButton.disabled = true;
        migrationImportButton.disabled = true;
        setMigrationStatus(t.migrationPreviewRunning);
        try {
          const result = await window.opensquillaDesktop.previewOnboardingMigration();
          const errors = renderMigrationReport(result && result.report);
          if (result && result.ok && errors.length === 0) {
            migrationPreviewOk = true;
          } else {
            errorBox.textContent = fmt('migrationPreviewFailed', { detail: migrationErrorDetail(result, errors) });
          }
        } catch (error) {
          errorBox.textContent = fmt('migrationPreviewFailed', { detail: error && error.message ? error.message : String(error) });
        } finally {
          migrationBusy = false;
          setMigrationStatus('');
          migrationPreviewButton.disabled = false;
          migrationImportButton.disabled = !migrationPreviewOk;
        }
      });
      migrationImportButton.addEventListener('click', async () => {
        if (migrationBusy || !migrationPreviewOk) return;
        migrationBusy = true;
        errorBox.textContent = '';
        migrationPreviewButton.disabled = true;
        migrationImportButton.disabled = true;
        migrationSkipButton.disabled = true;
        setMigrationStatus(t.migrationApplyRunning);
        let imported = false;
        try {
          const result = await window.opensquillaDesktop.applyOnboardingMigration();
          const errors = renderMigrationReport(result && result.report);
          if (result && result.ok && errors.length === 0) {
            imported = true;
            const pausedCount = result.report && Array.isArray(result.report.paused_jobs)
              ? result.report.paused_jobs.length
              : 0;
            migrationDoneNote.textContent = fmt('migrationDone', { n: pausedCount, path: migrationCandidate.path });
            migrationDoneNote.hidden = false;
            applyMigrationPrefill(result.prefill);
          } else {
            errorBox.textContent = fmt('migrationApplyFailed', { detail: migrationErrorDetail(result, errors) });
          }
        } catch (error) {
          errorBox.textContent = fmt('migrationApplyFailed', { detail: error && error.message ? error.message : String(error) });
        } finally {
          migrationBusy = false;
          setMigrationStatus('');
          migrationSkipButton.disabled = false;
          if (imported) {
            // Leave the completion note readable for a beat, then continue to
            // the provider step with the imported connection prefilled. The
            // migration card stays reachable from the rail to re-read the note.
            setTimeout(() => {
              errorBox.textContent = '';
              setStep(1);
            }, 1800);
          } else {
            migrationPreviewOk = false;
            migrationPreviewButton.disabled = false;
            migrationImportButton.disabled = true;
          }
        }
      });
      migrationSkipButton.addEventListener('click', () => {
        if (migrationBusy) return;
        errorBox.textContent = '';
        setStep(nextRouteStep(step));
      });
    }
    renderProviderGrid();
    renderSearchProviderGrid();
    syncProviderDefaults(true);
    render();
  </script>
</body>
</html>`
}

async function runOnboarding(): Promise<DesktopConnection> {
  const pendingProviderSetup = await loadPendingMigrationProviderSetup()
  const existing = await loadDesktopCredential()
  // A saved credential encrypted with the OS keychain that this session cannot
  // read (keychain locked or unavailable) must not be treated as "no credential":
  // silently re-onboarding would re-save the key as plaintext. Surface an
  // actionable error so the user can unlock and retry, or Reset setup.
  if (
    desktopSecretStoragePolicyBackend() === 'safeStorage'
    && desktopSecretStorageBackend() !== 'safeStorage'
    && (
      pendingProviderSetup !== null
      || Boolean(existing?.encryptedApiKey && existing.encryption === 'safeStorage')
    )
  ) {
    throw new Error(
      'OpenSquilla needs the OS keychain to read or safely adopt this credential, '
      + 'but the keychain is currently unavailable. Unlock it and reopen '
      + 'OpenSquilla, or use "Reset setup" to start over.'
    )
  }
  if (!pendingProviderSetup && existing && isConnectionReady(existing)) {
    // Seed the gateway config from the saved credential only when it does not
    // exist yet. Once it exists the Control UI owns it via RPC, so regenerating
    // it from the credential template here would clobber provider/router/channel
    // edits made live in Settings on every boot.
    if (!(await pathExists(desktopConfigPath()))) {
      await writeDesktopConfig(existing)
    }
    return existing
  }

  // No usable credential: this is the first-run (or reset) path, the only
  // interaction point before the gateway first boots — so offer the legacy home
  // import here, before provider setup (the import must precede first boot).
  onboardingMigrationCandidate = pendingProviderSetup ? null : detectLegacyImportCandidate()
  onboardingMigrationPreviewApprovedAt = 0

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

    // The wizard is a single data: URL page; block any renderer-initiated
    // top-frame navigation (e.g. a dropped file/link) so it can't replace the
    // onboarding UI — which holds the preload IPC bridge — with a foreign document.
    const guardOnboardingNavigation = (event: Electron.Event, targetUrl: string) => {
      event.preventDefault()
      if (/^https?:\/\//i.test(targetUrl) || targetUrl.startsWith('mailto:')) {
        void shell.openExternal(targetUrl)
      }
    }
    onboardingWindow.webContents.on('will-navigate', guardOnboardingNavigation)
    onboardingWindow.webContents.on('will-redirect', guardOnboardingNavigation)
    // Rebuild the app menu so View → Reload is disabled while onboarding is open.
    createApplicationMenu()

    onboardingWindow.once('ready-to-show', () => {
      if (!onboardingWindow || onboardingWindow.isDestroyed()) return
      onboardingWindow.show()
      onboardingWindow?.focus()
    })
    onboardingWindow.on('closed', () => {
      onboardingWindow = null
      // Re-enable View → Reload now that the wizard is gone.
      createApplicationMenu()
      if (rejectOnboarding) {
        const reject = rejectOnboarding
        resolveOnboarding = null
        rejectOnboarding = null
        reject(new Error('OpenSquilla setup was closed.'))
      }
    })

    onboardingWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(onboardingHtml(onboardingMigrationCandidate, pendingProviderSetup))}`).catch((error) => {
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

const GATEWAY_PORT_FIRST = 18791
const GATEWAY_PORT_LAST = 18830
let gatewayPortCursor = GATEWAY_PORT_FIRST

function explicitGatewayPort(): number | null {
  const envPort = Number(process.env.OPENSQUILLA_DESKTOP_GATEWAY_PORT || '')
  return Number.isInteger(envPort) && envPort > 0 ? envPort : null
}

function hasExplicitGatewayPort(): boolean {
  return explicitGatewayPort() !== null
}

function nextGatewayPortAfter(port: number): number {
  return port >= GATEWAY_PORT_LAST ? GATEWAY_PORT_FIRST : port + 1
}

function isPortBindable(port: number): Promise<boolean> {
  return new Promise((resolveBindable) => {
    const server = net.createServer()
    let settled = false
    const settle = (bindable: boolean) => {
      if (settled) return
      settled = true
      server.removeAllListeners()
      if (server.listening) {
        server.close(() => resolveBindable(bindable))
      } else {
        resolveBindable(bindable)
      }
    }
    server.once('error', () => settle(false))
    server.once('listening', () => settle(true))
    server.listen({ host: '127.0.0.1', port, exclusive: true })
  })
}

async function findGatewayPort(): Promise<number> {
  const envPort = explicitGatewayPort()
  if (envPort !== null) return envPort

  const portCount = GATEWAY_PORT_LAST - GATEWAY_PORT_FIRST + 1
  const startPort = Math.min(Math.max(gatewayPortCursor, GATEWAY_PORT_FIRST), GATEWAY_PORT_LAST)
  for (let offset = 0; offset < portCount; offset += 1) {
    const port = GATEWAY_PORT_FIRST + ((startPort - GATEWAY_PORT_FIRST + offset) % portCount)
    if (await isPortBindable(port)) {
      gatewayPortCursor = nextGatewayPortAfter(port)
      return port
    }
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

const GATEWAY_OUTPUT_TAIL_MAX_CHARS = 12_000
const NEWER_CONFIG_DIAGNOSTIC_FIELDS = [
  'llm_ensemble',
  'privacy',
  'sandbox.auto_setup',
  'llm_profiles',
] as const

function appendGatewayOutputTail(tail: string, chunk: Buffer | string): string {
  const next = tail + String(chunk)
  return next.length > GATEWAY_OUTPUT_TAIL_MAX_CHARS ? next.slice(-GATEWAY_OUTPUT_TAIL_MAX_CHARS) : next
}

function gatewayExitLooksLikeNewerConfig(output: string): boolean {
  const normalized = output.toLowerCase()
  const hasValidationSignal = (
    normalized.includes('validationerror') ||
    normalized.includes('extra_forbidden') ||
    normalized.includes('extra inputs are not permitted')
  )
  return hasValidationSignal && NEWER_CONFIG_DIAGNOSTIC_FIELDS.some((field) => normalized.includes(field))
}

function gatewayExitLooksLikePortInUse(output: string): boolean {
  return /OPENSQUILLA_GATEWAY_PORT_IN_USE/i.test(output)
    || /gateway could not start:.*is already in use/i.test(output)
    || /gateway port is already in use/i.test(output)
    || /:\d+\s+is already in use/i.test(output)
}

function classifyGatewayExitMessage(message: string, outputTail: string): string {
  if (!gatewayExitLooksLikeNewerConfig(outputTail)) return message
  return (
    message +
    '\n\nOpenSquilla could not read this config because it contains settings written by a newer OpenSquilla version. ' +
    `Reopen the newer OpenSquilla version that created it, or reset the desktop config before running this version (${app.getVersion()}). ` +
    'Use Reveal log for details.'
  )
}

async function waitForGateway(url: string, earlyExitMessage?: () => string | null): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < 45_000) {
    const earlyExit = earlyExitMessage?.()
    if (earlyExit) throw new Error(earlyExit)
    if (await healthCheck(url)) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  const earlyExit = earlyExitMessage?.()
  if (earlyExit) throw new Error(earlyExit)
  throw new Error(`Gateway did not become healthy at ${url}`)
}

async function waitForControlUi(url: string, earlyExitMessage?: () => string | null): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < 45_000) {
    const earlyExit = earlyExitMessage?.()
    if (earlyExit) throw new Error(earlyExit)
    try {
      const response = await fetch(`${url}/control/`, { signal: AbortSignal.timeout(1500) })
      if (response.ok) return
    } catch {
      // The ASGI socket can become healthy just before static routes are ready.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  const earlyExit = earlyExitMessage?.()
  if (earlyExit) throw new Error(earlyExit)
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
  const reusableGateway = forceOnboardingOnNextStartup ? null : await reuseHealthyGatewayState()
  if (reusableGateway) return reusableGateway

  assertSupportedMacInstallLocation()

  if (gatewayProcess && gatewayState.owned) {
    if (hasGatewayProcessExited(gatewayProcess)) {
      gatewayProcess = null
    } else {
      // Wait for the old child to actually exit before spawning a replacement.
      // stopGateway() only initiates termination; the gateway drains for several
      // seconds and holds gateway.pid.lock until it exits, so respawning
      // immediately makes the new gateway abort on the held lock and the restart
      // fails with an unclassified error.
      const previousChild = gatewayProcess
      stopGateway()
      await waitForGatewayProcessExit(previousChild)
    }
    gatewayState.status = 'stopped'
    gatewayState.error = undefined
  }

  const overrideUrl = process.env.OPENSQUILLA_DESKTOP_GATEWAY_URL
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

  sendBootStatus('profile')
  recoverInterruptedDesktopImport()
  await recoverPendingMigrationReconciliation()
  relocateLegacyDesktopStateLayout()
  const connection = await runOnboarding()
  forceOnboardingOnNextStartup = false
  const apiKey = decryptApiKey(connection)
  // Keyless providers (e.g. Ollama) ship requiresApiKey=false and are accepted
  // by onboarding without a key, so only treat a missing key as fatal when the
  // provider actually needs one — otherwise every keyless credential wedges boot.
  if (providerDefaults(connection.provider).requiresApiKey && !apiKey) {
    throw new Error('Saved desktop API key could not be read.')
  }
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
  // Node can emit both 'error' and 'exit' for one child, and each handler closes
  // the stream — so guard writes/close to be idempotent, and swallow any late
  // write-after-end/EPIPE rather than letting it crash the main process.
  let logStreamClosed = false
  logStream.on('error', () => {})
  const writeLogLine = (text: string) => {
    if (!logStreamClosed) logStream.write(text)
  }
  const closeLogStream = () => {
    if (logStreamClosed) return
    logStreamClosed = true
    logStream.end()
  }

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
    ...(connection.apiKeyEnv && apiKey ? { [connection.apiKeyEnv]: apiKey } : {}),
    ...(connection.searchApiKeyEnv && searchApiKey ? { [connection.searchApiKeyEnv]: searchApiKey } : {}),
    OPENSQUILLA_DESKTOP: '1',
    OPENSQUILLA_INSTALL_METHOD: 'desktop',
    OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
    OPENSQUILLA_NODE_BIN_DIR: nodeBinCandidates.join(pathDelimiter()),
    // OPENSQUILLA_STATE_DIR names the OpenSquilla HOME ROOT on the Python side
    // (runtime state goes into its state/ subdir, matching the TOML-pinned
    // state_dir below). Passing the state subdir here would re-root skills,
    // workspace, session-archive, and .env one level too deep — see
    // relocateLegacyDesktopStateLayout().
    OPENSQUILLA_STATE_DIR: desktopHome(),
    ...(connection.disableNetworkObservability ? { OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY: '1' } : {}),
    PYTHONUNBUFFERED: '1',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8:replace',
  }

  const child = spawn(
    runtime.command,
    [...runtime.args, '--port', String(port), '--bind', '127.0.0.1', '--config', desktopConfigPath()],
    {
      cwd: runtime.cwd,
      env: childEnv,
      detached: runtime.mode === 'dev' && process.platform !== 'win32',
      // The bundled gateway is a console-subsystem binary; without this Windows
      // allocates a stray console window whose closure would kill the gateway.
      windowsHide: true,
    }
  )
  gatewayProcess = child
  if (runtime.mode === 'dev') gatewayProcessTreeChildren.add(child)

  let gatewayOutputTail = ''
  let childExitMessage: string | null = null
  const rememberGatewayOutput = (chunk: Buffer | string) => {
    gatewayOutputTail = appendGatewayOutputTail(gatewayOutputTail, chunk)
  }
  child.stdout.on('data', rememberGatewayOutput)
  child.stderr.on('data', rememberGatewayOutput)
  child.stdout.pipe(logStream, { end: false })
  child.stderr.pipe(logStream, { end: false })
  child.once('exit', (code, signal) => {
    const message = `gateway exited code=${code ?? 'null'} signal=${signal ?? 'null'}`
    const portConflictExit = gatewayExitLooksLikePortInUse(gatewayOutputTail)
    const exitMessage = portConflictExit ? `${message}\nGateway port is already in use.` : message
    const classifiedMessage = classifyGatewayExitMessage(exitMessage, gatewayOutputTail)
    const isCurrentGateway = gatewayProcess === child
    if (isCurrentGateway) gatewayProcess = null
    writeLogLine(`\n[desktop] ${message}\n`)
    // Release the append fd; without this every (re)start leaks one open handle
    // to gateway.log for the lifetime of the main process.
    closeLogStream()
    if (!isCurrentGateway) return
    if (isQuitting) {
      gatewayState.status = 'stopped'
      return
    }
    gatewayState.status = 'error'
    gatewayState.error = classifiedMessage
    childExitMessage = classifiedMessage
    if (portConflictExit && !hasExplicitGatewayPort()) {
      gatewayState.status = 'stopped'
      gatewayState.error = undefined
      return
    }
    sendBootError(gatewayState.error)
    // After boot the window is on the gateway-served Control UI, which never
    // listens for boot:error. Restore the boot splash so the crash message and
    // the Retry/Reset recovery affordances are visible instead of a dead origin.
    void restoreMainWindowToBootPage()
  })

  // A failed spawn (uv missing in dev, non-executable bundled binary) emits
  // 'error' and never 'exit'; without a listener Node rethrows it as an uncaught
  // main-process exception (raw Electron crash dialog) and the boot wait hangs.
  child.once('error', (err) => {
    const message = `gateway failed to start: ${err instanceof Error ? err.message : String(err)}`
    const isCurrentGateway = gatewayProcess === child
    if (isCurrentGateway) gatewayProcess = null
    closeLogStream()
    if (!isCurrentGateway) return
    childExitMessage = message
    if (isQuitting) {
      gatewayState.status = 'stopped'
      return
    }
    gatewayState.status = 'error'
    gatewayState.error = message
    sendBootError(message)
  })

  sendBootStatus('gateway-health')
  await waitForGateway(url, () => childExitMessage)
  await waitForControlUi(url, () => childExitMessage)
  // Guard against adopting a foreign gateway that won the probe→bind race: if our
  // spawned child has already exited, it lost the exclusive bind and the healthy
  // endpoint belongs to someone else (e.g. a CLI `opensquilla gateway run` on the
  // same port). Surface it as a port conflict so recovery advances to the next
  // port instead of silently attaching the window to the wrong profile.
  if (hasGatewayProcessExited(child) || gatewayProcess !== child) {
    throw new Error(childExitMessage
      || 'OPENSQUILLA_GATEWAY_PORT_IN_USE: desktop gateway did not keep the port bind.')
  }
  sendBootStatus('control')
  gatewayState.status = 'ready'
  return gatewayState
}

async function startGatewayWithPortRecovery(): Promise<GatewayState> {
  // Begin each fresh recovery sequence at the first port so a previously-used
  // port that is now free is reused. The cursor still advances within this loop
  // to skip a port whose bind lost a post-probe race, but it must not persist
  // across separate starts — otherwise every in-session restart hops to a new
  // 127.0.0.1:<port> origin and silently drops the Control UI's per-origin state.
  if (!hasExplicitGatewayPort()) gatewayPortCursor = GATEWAY_PORT_FIRST
  const maxAttempts = hasExplicitGatewayPort() ? 1 : GATEWAY_PORT_LAST - GATEWAY_PORT_FIRST + 1
  let lastError: unknown = null
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await startGateway()
    } catch (err) {
      lastError = err
      const message = err instanceof Error ? err.message : String(err)
      if (hasExplicitGatewayPort() || !gatewayExitLooksLikePortInUse(message)) throw err
      desktopLog('gateway_port_retry', { attempt: attempt + 1 })
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError || 'Gateway port retry exhausted.'))
}

async function loadControlUi(window: BrowserWindow, gatewayUrl: string): Promise<void> {
  const url = `${gatewayUrl}/control/chat`
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

// The main window is only ever meant to sit on the gateway-served Control UI
// origin (its /control paths). Anything else — a dropped file:// document, an
// off-origin redirect — is a foreign navigation and must be blocked. The boot
// splash is loaded programmatically (loadFile), which does not go through the
// navigation guard, so it needs no allow-entry here.
function isAllowedMainWindowNavigation(targetUrl: string): boolean {
  if (!gatewayState.url) return false
  try {
    const target = new URL(targetUrl)
    const gateway = new URL(gatewayState.url)
    return (
      target.origin === gateway.origin
      && (target.pathname === '/control' || target.pathname.startsWith('/control/'))
    )
  } catch {
    return false
  }
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

  // Top-frame navigation guard. Programmatic loadFile/loadURL from the main
  // process do NOT emit these, so this only blocks renderer-initiated top-frame
  // navigations: a dropped file/link (Chromium's default drop action) or an
  // in-content redirect that would replace the Control UI with a foreign document
  // while keeping the full opensquillaDesktop IPC bridge. SPA route changes use
  // history.pushState and are unaffected.
  const guardMainWindowNavigation = (event: Electron.Event, targetUrl: string) => {
    if (isAllowedMainWindowNavigation(targetUrl)) return
    event.preventDefault()
    if (/^https?:\/\//i.test(targetUrl) || targetUrl.startsWith('mailto:')) {
      void shell.openExternal(targetUrl)
    }
  }
  window.webContents.on('will-navigate', guardMainWindowNavigation)
  window.webContents.on('will-redirect', guardMainWindowNavigation)

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
    gatewayStartPromise = startGatewayWithPortRecovery().finally(() => {
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

// Bring the main window back to the boot splash when a gateway failure happens
// while the window is showing the gateway-served Control UI. The splash owns the
// boot:error listener plus the Retry/Reset recovery buttons, so this is what
// turns an otherwise-dead Control UI origin back into a recoverable state.
async function restoreMainWindowToBootPage(): Promise<void> {
  const window = currentMainWindow()
  if (!window) return
  // Already on the boot splash (initial boot); its own onBootError handler will
  // render the error. Only navigate back when the window left for the Control UI.
  if (window.webContents.getURL().startsWith('file:')) return
  try {
    await window.loadFile(bootPagePath())
  } catch {
    // Best-effort: the diagnostic log and gatewayState still record the failure.
  }
}

async function openOrResumeDesktopApp(): Promise<void> {
  if (isQuitting) return
  await createMainWindow()
  focusMainWindow()

  try {
    const reusableGateway = forceOnboardingOnNextStartup ? null : await reuseHealthyGatewayState()
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
const UPDATE_GATEWAY_EXIT_TIMEOUT_MS = GATEWAY_SHUTDOWN_KILL_AFTER_MS + GATEWAY_HARD_KILL_BACKSTOP_MS

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

// Fetch a diagnostics bundle from the child gateway (loopback owner, no token
// needed — same auth posture as requestGatewayShutdown) and save it where the
// user chooses. Falls back to opening the logs folder when no gateway is up.
async function downloadDiagnostics(): Promise<void> {
  desktopLog('diagnostics_download_requested')
  const url = gatewayState.url
  if (!url) {
    await shell.openPath(join(app.getPath('userData'), 'logs')).catch(() => null)
    return
  }
  try {
    const response = await fetch(`${url}/api/v1/diagnostics/bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(60000),
    })
    if (!response.ok) {
      desktopLog('diagnostics_download_failed', { status: response.status })
      await shell.openPath(join(app.getPath('userData'), 'logs')).catch(() => null)
      return
    }
    // Read the body before showing the modal save dialog: the 60s abort signal
    // keeps counting while the dialog is open, and a slow deliberation would
    // otherwise abort the already-successful response.
    const bytes = Buffer.from(await response.arrayBuffer())
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    const win = currentMainWindow()
    const defaultPath = join(
      app.getPath('downloads'),
      `opensquilla-bundle-${stamp}.zip`,
    )
    const saveOptions: Electron.SaveDialogOptions = {
      defaultPath,
      filters: [{ name: 'Zip archive', extensions: ['zip'] }],
    }
    const result = win
      ? await dialog.showSaveDialog(win, saveOptions)
      : await dialog.showSaveDialog(saveOptions)
    if (result.canceled || !result.filePath) return
    await writeFile(result.filePath, bytes)
    desktopLog('diagnostics_download_saved', { bytes: bytes.length })
    await shell.showItemInFolder(result.filePath)
  } catch (err) {
    desktopLog('diagnostics_download_failed', { error: String(err) })
    await shell.openPath(join(app.getPath('userData'), 'logs')).catch(() => null)
  }
}

async function clearKnownOwnedGatewayPidFile(): Promise<void> {
  // Leave gateway.pid.lock in place. The persistent lock path is the authority
  // shared by all contenders; deleting it can create split-brain locks.
  await rm(join(desktopStateDir(), 'gateway.pid'), { force: true }).catch(() => null)
}

function hardTerminateGatewayProcess(
  child: ChildProcessWithoutNullStreams,
  backstopMs = GATEWAY_HARD_KILL_BACKSTOP_MS,
): void {
  if (hasGatewayProcessExited(child)) return
  terminateGatewayProcess(child, 'SIGTERM')
  if (process.platform === 'win32') void clearKnownOwnedGatewayPidFile()
  setTimeout(() => {
    if (!hasGatewayProcessExited(child)) {
      terminateGatewayProcess(child, 'SIGKILL')
      if (process.platform === 'win32') void clearKnownOwnedGatewayPidFile()
    }
  }, backstopMs).unref()
}

function terminateGatewayProcess(
  child: ChildProcessWithoutNullStreams,
  signal: NodeJS.Signals,
): void {
  const pid = child.pid
  if (pid && gatewayProcessTreeChildren.has(child)) {
    if (process.platform === 'win32') {
      const result = spawnSync('taskkill', ['/pid', String(pid), '/t', '/f'], {
        stdio: 'ignore',
        windowsHide: true,
      })
      if (result.status === 0) return
    } else {
      try {
        process.kill(-pid, signal)
        return
      } catch {
        // Fall back to signaling the direct child below.
      }
    }
  }
  child.kill(signal)
}

function stopGateway(): void {
  if (!gatewayProcess || !gatewayState.owned) return
  const child = gatewayProcess
  const url = gatewayState.url
  gatewayProcess = null

  const hardTerminate = () => {
    hardTerminateGatewayProcess(child)
  }

  // The Windows HTTP graceful path is async (fetch + timers) and only works
  // while the main process stays alive to drive it. On app quit (isQuitting) the
  // process is about to exit, so that fire-and-forget work would race teardown
  // and orphan the child — leaving it holding the listen port + PID lock and
  // breaking the next launch. So only take the graceful path when NOT quitting;
  // on quit, fall through to a synchronous TerminateProcess.
  if (process.platform === 'win32' && (!isQuitting || allowGracefulShutdownWhileQuitting)) {
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
  hardTerminateGatewayProcess(child, GATEWAY_SHUTDOWN_KILL_AFTER_MS)
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
let downloadedUpdateVersion: string | null = null
let updateGatewayShutdownProcess: ChildProcessWithoutNullStreams | null = null
let mockDownloadedUpdate = false
let mockUpdatePromptActive = false
let mockUpdateDialogResponses: number[] | null = null

const MOCK_UPDATE_VERSION_ENV = 'OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION'
const MOCK_UPDATE_DIALOG_RESPONSES_ENV = 'OPENSQUILLA_DESKTOP_MOCK_UPDATE_DIALOG_RESPONSES'

type DesktopUpdateStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'downloaded'
  | 'not-available'
  | 'error'
  | 'applying'

interface DesktopUpdateState {
  status: DesktopUpdateStatus
  currentVersion: string
  latestVersion: string | null
  progress: number | null
  checkedAt: string | null
  error: string | null
  snoozedUntil: string | null
  canNativeInstall: boolean
  releaseUrl: string | null
}

interface DesktopUpdatePersistedState {
  snoozedVersion?: string
  snoozedUntil?: string
}

const UPDATE_SNOOZE_MS = 24 * 60 * 60 * 1000

let desktopUpdateStatus: DesktopUpdateStatus = 'idle'
let desktopUpdateLatestVersion: string | null = null
let desktopUpdateProgress: number | null = null
let desktopUpdateCheckedAt: string | null = null
let desktopUpdateError: string | null = null
let desktopUpdateSnoozedVersion: string | null = null
let desktopUpdateSnoozedUntil: string | null = null
let desktopUpdatePersistenceLoaded = false

const NETWORK_OBSERVABILITY_DISABLE_ENV_KEYS = [
  'OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY',
  'OPENSQUILLA_TELEMETRY_DISABLED',
  'OPENSQUILLA_UPDATE_CHECK_DISABLED',
] as const

// mtime-keyed caches so the update-state publish path (which runs on every
// download-progress tick) does not re-read + JSON.parse the credential and
// re-scan config.toml on every call. Invalidated automatically when the file
// changes — atomicWriteFile's rename bumps mtime, and deletion falls through the
// existsSync guard.
let persistedNetObsCache: { mtime: number; value: boolean } | null = null
let configNetObsCache: { mtime: number; value: boolean | null } | null = null

function desktopPersistedNetworkObservabilityDisabled(): boolean {
  try {
    const path = credentialPath()
    if (!existsSync(path)) return false
    const mtime = statSync(path).mtimeMs
    if (persistedNetObsCache && persistedNetObsCache.mtime === mtime) return persistedNetObsCache.value
    const raw = readFileSync(path, 'utf8')
    const value = normalizeDesktopCredential(JSON.parse(raw) as Partial<DesktopConnection>).disableNetworkObservability
    persistedNetObsCache = { mtime, value }
    return value
  } catch {
    return true
  }
}

function parseDesktopNetworkObservabilityPrivacyConfig(raw: string): boolean | null {
  let inPrivacySection = false
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const section = line.match(/^\[([^\]]+)\]$/)
    if (section) {
      inPrivacySection = section[1]?.trim() === 'privacy'
      continue
    }
    if (!inPrivacySection) continue
    const setting = line.match(/^disable_network_observability\s*=\s*(.*)$/i)
    if (!setting) continue
    const value = String(setting[1] ?? '').split('#', 1)[0].trim().toLowerCase()
    if (value === 'true') return true
    if (value === 'false') return false
    return true
  }
  return null
}

function readDesktopConfigNetworkObservabilitySetting(): boolean | null {
  try {
    const path = desktopConfigPath()
    if (!existsSync(path)) return null
    const mtime = statSync(path).mtimeMs
    if (configNetObsCache && configNetObsCache.mtime === mtime) return configNetObsCache.value
    const raw = readFileSync(path, 'utf8')
    const value = parseDesktopNetworkObservabilityPrivacyConfig(raw)
    configNetObsCache = { mtime, value }
    return value
  } catch {
    return true
  }
}

function desktopConfigNetworkObservabilityDisabled(): boolean {
  return readDesktopConfigNetworkObservabilitySetting() ?? false
}

function desktopNetworkObservabilityDisabled(): boolean {
  if (NETWORK_OBSERVABILITY_DISABLE_ENV_KEYS.some((key) => truthyEnv(process.env[key]))) return true
  return desktopPersistedNetworkObservabilityDisabled() || desktopConfigNetworkObservabilityDisabled()
}

function mockUpdateVersion(): string | null {
  if (app.isPackaged) return null
  const version = (process.env[MOCK_UPDATE_VERSION_ENV] || '').trim()
  return version || null
}

function desktopUpdateMenuEnabled(): boolean {
  return autoUpdateSupported() || mockUpdateVersion() !== null
}

function autoUpdateSupported(): boolean {
  if (!app.isPackaged) return false
  if (desktopNetworkObservabilityDisabled()) return false
  if (process.env.OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE === '1') return false
  if (process.platform === 'darwin') return true
  if (process.platform === 'win32' && process.env.OPENSQUILLA_DESKTOP_ENABLE_WIN_UPDATE === '1') {
    return true
  }
  return false
}

function nativeAutoUpdateEnabled(): boolean {
  return mockUpdateVersion() !== null || (autoUpdateSupported() && macUpdateLocationOk())
}

function desktopUpdateStatePath(): string {
  return join(desktopStateDir(), 'desktop-update.json')
}

function loadDesktopUpdatePersistence(): void {
  if (desktopUpdatePersistenceLoaded) return
  desktopUpdatePersistenceLoaded = true
  try {
    const path = desktopUpdateStatePath()
    if (!existsSync(path)) return
    const parsed = JSON.parse(readFileSync(path, 'utf8')) as DesktopUpdatePersistedState
    const snoozedVersion = String(parsed.snoozedVersion || '').trim()
    const snoozedUntil = String(parsed.snoozedUntil || '').trim()
    if (!snoozedVersion || !snoozedUntil) return
    if (Number.isNaN(Date.parse(snoozedUntil)) || Date.parse(snoozedUntil) <= Date.now()) return
    desktopUpdateSnoozedVersion = snoozedVersion
    desktopUpdateSnoozedUntil = snoozedUntil
  } catch {
    desktopUpdateSnoozedVersion = null
    desktopUpdateSnoozedUntil = null
  }
}

async function persistDesktopUpdateSnooze(): Promise<void> {
  try {
    mkdirSync(desktopStateDir(), { recursive: true })
    await writeFile(
      desktopUpdateStatePath(),
      JSON.stringify(
        {
          snoozedVersion: desktopUpdateSnoozedVersion || undefined,
          snoozedUntil: desktopUpdateSnoozedUntil || undefined,
        },
        null,
        2,
      ),
      { mode: 0o600 },
    )
  } catch (err) {
    console.warn('[updater] failed to persist update snooze', err)
  }
}

function activeDesktopUpdateSnoozeFor(version: string | null): string | null {
  loadDesktopUpdatePersistence()
  if (!version || !desktopUpdateSnoozedVersion || !desktopUpdateSnoozedUntil) return null
  if (desktopUpdateSnoozedVersion !== version) return null
  if (Date.parse(desktopUpdateSnoozedUntil) <= Date.now()) {
    desktopUpdateSnoozedVersion = null
    desktopUpdateSnoozedUntil = null
    void persistDesktopUpdateSnooze()
    return null
  }
  return desktopUpdateSnoozedUntil
}

function clearDesktopUpdateSnoozeIfVersionChanged(version: string | null): void {
  loadDesktopUpdatePersistence()
  if (!version || !desktopUpdateSnoozedVersion || desktopUpdateSnoozedVersion === version) return
  desktopUpdateSnoozedVersion = null
  desktopUpdateSnoozedUntil = null
  void persistDesktopUpdateSnooze()
}

function desktopUpdateSnapshot(): DesktopUpdateState {
  const latestVersion = desktopUpdateLatestVersion || downloadedUpdateVersion
  return {
    status: desktopUpdateStatus,
    currentVersion: app.getVersion(),
    latestVersion,
    progress: desktopUpdateProgress,
    checkedAt: desktopUpdateCheckedAt,
    error: desktopUpdateError,
    snoozedUntil: activeDesktopUpdateSnoozeFor(latestVersion),
    canNativeInstall: nativeAutoUpdateEnabled(),
    releaseUrl: null,
  }
}

function publishDesktopUpdateState(): DesktopUpdateState {
  const state = desktopUpdateSnapshot()
  for (const window of BrowserWindow.getAllWindows()) {
    if (!window.isDestroyed()) window.webContents.send('desktop:update:state-changed', state)
  }
  return state
}

function setDesktopUpdateState(patch: Partial<DesktopUpdateState>): DesktopUpdateState {
  if (patch.status !== undefined) desktopUpdateStatus = patch.status
  if ('latestVersion' in patch) desktopUpdateLatestVersion = patch.latestVersion ?? null
  if ('progress' in patch) desktopUpdateProgress = patch.progress ?? null
  if ('checkedAt' in patch) desktopUpdateCheckedAt = patch.checkedAt ?? null
  if ('error' in patch) desktopUpdateError = patch.error ?? null
  clearDesktopUpdateSnoozeIfVersionChanged(desktopUpdateLatestVersion || downloadedUpdateVersion)
  return publishDesktopUpdateState()
}

async function dismissDesktopUpdate(): Promise<DesktopUpdateState> {
  const latestVersion = desktopUpdateLatestVersion || downloadedUpdateVersion
  if (latestVersion) {
    desktopUpdateSnoozedVersion = latestVersion
    desktopUpdateSnoozedUntil = new Date(Date.now() + UPDATE_SNOOZE_MS).toISOString()
    await persistDesktopUpdateSnooze()
  }
  return publishDesktopUpdateState()
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

function nextMockUpdateDialogResponse(): number | null {
  if (mockUpdateVersion() === null) return null
  if (mockUpdateDialogResponses === null) {
    const raw = (process.env[MOCK_UPDATE_DIALOG_RESPONSES_ENV] || '').trim()
    mockUpdateDialogResponses = raw
      ? raw.split(',').map((part) => Number(part.trim()))
      : []
  }
  const response = mockUpdateDialogResponses.shift()
  if (!Number.isInteger(response)) return null
  return Number(response)
}

function showUpdateDialog(
  options: Electron.MessageBoxOptions,
): Promise<Electron.MessageBoxReturnValue> {
  const mockResponse = nextMockUpdateDialogResponse()
  if (mockResponse !== null) {
    console.log(`[mock-updater] ${String(options.title || options.message || 'dialog')} response=${mockResponse}`)
    return Promise.resolve({ response: mockResponse, checkboxChecked: false })
  }
  const win = currentMainWindow()
  return win ? dialog.showMessageBox(win, options) : dialog.showMessageBox(options)
}

function showUpdateError(err: unknown): void {
  const shouldNotify = manualUpdateCheck || updateDownloadInProgress
  manualUpdateCheck = false
  updateDownloadInProgress = false
  if (!shouldNotify) {
    // electron-updater delivers each failure twice (it emits 'error' AND rejects
    // the promise our try/catch awaits). The first delivery publishes the visible
    // error and clears the notify flags; without this guard the second, now-silent
    // delivery would clobber that error back to idle and wipe the known
    // latestVersion. Leave an already-published error in place.
    if (desktopUpdateStatus === 'error') return
    setDesktopUpdateState({
      status: downloadedUpdateVersion ? 'downloaded' : 'idle',
      latestVersion: downloadedUpdateVersion,
      progress: downloadedUpdateVersion ? 100 : null,
      checkedAt: new Date().toISOString(),
      error: null,
    })
    return
  }
  setDesktopUpdateState({
    status: 'error',
    progress: null,
    checkedAt: new Date().toISOString(),
    error: String(err instanceof Error ? err.message : err ?? ''),
  })
}

async function runMockUpdateFlow(version: string): Promise<void> {
  if (mockUpdatePromptActive) return
  mockUpdatePromptActive = true
  try {
    if (downloadedUpdateVersion === version) {
      setDesktopUpdateState({
        status: 'downloaded',
        latestVersion: version,
        progress: 100,
        checkedAt: new Date().toISOString(),
        error: null,
      })
    } else {
      setDesktopUpdateState({
        status: 'available',
        latestVersion: version,
        progress: null,
        checkedAt: new Date().toISOString(),
        error: null,
      })
    }
  } finally {
    mockUpdatePromptActive = false
    updateDownloadInProgress = false
    manualUpdateCheck = false
  }
}

async function downloadDesktopUpdate(): Promise<DesktopUpdateState> {
  if (updateDownloadInProgress || updateApplying || desktopUpdateStatus === 'downloaded') {
    return desktopUpdateSnapshot()
  }

  const mockVersion = mockUpdateVersion()
  if (mockVersion !== null) {
    const version = desktopUpdateLatestVersion || mockVersion
    updateDownloadInProgress = true
    setDesktopUpdateState({
      status: 'downloading',
      latestVersion: version,
      progress: 0,
      error: null,
    })
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 100)
    })
    updateDownloadInProgress = false
    downloadedUpdateVersion = version
    mockDownloadedUpdate = true
    createApplicationMenu()
    return setDesktopUpdateState({
      status: 'downloaded',
      latestVersion: version,
      progress: 100,
      error: null,
    })
  }

  if (!autoUpdateSupported()) return desktopUpdateSnapshot()
  if (!macUpdateLocationOk()) {
    return setDesktopUpdateState({
      status: 'error',
      progress: null,
      error: desktopT('update.moveToApplications'),
    })
  }

  initAutoUpdater()
  if (!desktopUpdateLatestVersion) await checkForUpdates(true)
  if (!desktopUpdateLatestVersion) return desktopUpdateSnapshot()

  updateDownloadInProgress = true
  setDesktopUpdateState({
    status: 'downloading',
    progress: 0,
    error: null,
  })
  try {
    await autoUpdater.downloadUpdate()
  } catch (err) {
    console.error('[updater] download failed', err)
    showUpdateError(err)
  }
  return desktopUpdateSnapshot()
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
    manualUpdateCheck = false
    updateDownloadInProgress = false
    setDesktopUpdateState({
      status: 'available',
      latestVersion: version || null,
      progress: null,
      checkedAt: new Date().toISOString(),
      error: null,
    })
  })

  autoUpdater.on('update-not-available', () => {
    manualUpdateCheck = false
    updateDownloadInProgress = false
    setDesktopUpdateState({
      status: 'not-available',
      latestVersion: app.getVersion(),
      progress: null,
      checkedAt: new Date().toISOString(),
      error: null,
    })
  })

  autoUpdater.on('download-progress', (progress) => {
    const percent = Number(progress?.percent)
    setDesktopUpdateState({
      status: 'downloading',
      progress: Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null,
      error: null,
    })
  })

  autoUpdater.on('update-downloaded', (info) => {
    manualUpdateCheck = false
    updateDownloadInProgress = false
    const version = String(info?.version ?? '')
    downloadedUpdateVersion = version
    mockDownloadedUpdate = false
    createApplicationMenu()
    setDesktopUpdateState({
      status: 'downloaded',
      latestVersion: version || null,
      progress: 100,
      checkedAt: new Date().toISOString(),
      error: null,
    })
  })

  autoUpdater.on('error', (err) => {
    console.error('[updater] error', err)
    showUpdateError(err)
  })
}

// ── macOS prerelease update discovery ───────────────────────────────────────
// The tag-parsing + candidate-selection logic lives in ./update-feed-resolver so
// it can be unit-tested without Electron; the pieces below are the Electron-bound
// glue (current version, GitHub fetch, feed wiring).

// The running app version if it is a prerelease we can resolve upgrades for.
function currentPrereleaseReleaseTarget(): { base: string; rc: number } | null {
  const parsed = parseOpenSquillaReleaseTag(app.getVersion())
  return parsed && parsed.rc !== null ? { base: parsed.base, rc: parsed.rc } : null
}

async function fetchGithubReleaseSummaries(): Promise<ReleaseSummary[]> {
  const url = `https://api.github.com/repos/${GITHUB_UPDATE_OWNER}/${GITHUB_UPDATE_REPO}/releases?per_page=50`
  const response = await fetch(url, {
    headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'OpenSquilla-Desktop' },
    signal: AbortSignal.timeout(8000),
  })
  if (!response.ok) throw new Error(`GitHub releases request failed: ${response.status}`)
  const data = await response.json()
  return Array.isArray(data) ? (data as ReleaseSummary[]) : []
}

// Returns 'default' to leave the built-in GitHub provider in place (stable
// builds, non-macOS, dev), 'configured' after pointing a generic feed at the
// resolved candidate, or 'up-to-date' when no newer same-base release exists.
async function configureDesktopUpdateFeed(): Promise<'default' | 'configured' | 'up-to-date'> {
  // Default (stable builds, GitHub provider path): never silently downgrade.
  autoUpdater.allowDowngrade = false
  if (process.platform !== 'darwin' || !app.isPackaged) return 'default'
  const current = currentPrereleaseReleaseTarget()
  if (!current) return 'default'
  const candidate = selectMacPrereleaseCandidate(current, await fetchGithubReleaseSummaries())
  if (!candidate) return 'up-to-date'
  // Generic provider + channel 'latest' fetches latest-mac.yml from this exact
  // release; the yml's version is then gated by electron-updater's isUpdateAvailable.
  autoUpdater.setFeedURL({ provider: 'generic', url: candidate.feedUrl, channel: 'latest' })
  // The resolver already decided this candidate is the correct forward move by
  // NUMERIC rc order. electron-updater's gate uses semver.gt, which sorts rc
  // identifiers as strings — so 0.5.0-rc10 ranks BELOW 0.5.0-rc9/rc2 and the
  // update would be wrongly rejected. Allow the "downgrade": we only ever point
  // the feed at a genuinely newer release, never an older one.
  autoUpdater.allowDowngrade = true
  desktopLog('update_feed_resolved', { tag: candidate.tag, version: candidate.version })
  return 'configured'
}

async function checkForUpdates(manual: boolean): Promise<void> {
  if (updateDownloadInProgress || updateApplying) return

  const mockVersion = mockUpdateVersion()
  if (mockVersion !== null) {
    manualUpdateCheck = manual
    setDesktopUpdateState({
      status: 'checking',
      latestVersion: desktopUpdateLatestVersion || mockVersion,
      progress: null,
      checkedAt: new Date().toISOString(),
      error: null,
    })
    await runMockUpdateFlow(mockVersion)
    return
  }

  if (!autoUpdateSupported()) {
    if (manual) {
      setDesktopUpdateState({
        status: 'error',
        progress: null,
        checkedAt: new Date().toISOString(),
        error: desktopT('update.errorTitle'),
      })
    }
    return
  }

  // Guide the user to /Applications first, otherwise the in-place swap fails.
  if (!macUpdateLocationOk()) {
    setDesktopUpdateState({
      status: 'error',
      progress: null,
      checkedAt: new Date().toISOString(),
      error: desktopT('update.moveToApplications'),
    })
    return
  }

  initAutoUpdater()
  manualUpdateCheck = manual
  setDesktopUpdateState({
    status: 'checking',
    progress: null,
    checkedAt: new Date().toISOString(),
    error: null,
  })
  try {
    const feed = await configureDesktopUpdateFeed()
    if (feed === 'up-to-date') {
      // A packaged macOS prerelease with no newer same-base release. Report
      // up-to-date directly — the default GitHub provider would find nothing
      // (the rc tags are PEP440, not npm semver) and raise a spurious error.
      manualUpdateCheck = false
      setDesktopUpdateState({
        status: 'not-available',
        latestVersion: app.getVersion(),
        progress: null,
        checkedAt: new Date().toISOString(),
        error: null,
      })
      return
    }
    await autoUpdater.checkForUpdates()
  } catch (err) {
    console.error('[updater] checkForUpdates failed', err)
    showUpdateError(err)
  }
}

function gatewayProcessForUpdateInstall(): ChildProcessWithoutNullStreams | null {
  const child = gatewayProcess && gatewayState.owned ? gatewayProcess : updateGatewayShutdownProcess
  if (!child) return null
  if (!hasGatewayProcessExited(child)) return child
  if (updateGatewayShutdownProcess === child) updateGatewayShutdownProcess = null
  return null
}

async function waitForGatewayProcessExit(
  child: ChildProcessWithoutNullStreams,
  timeoutMs = UPDATE_GATEWAY_EXIT_TIMEOUT_MS,
): Promise<boolean> {
  if (hasGatewayProcessExited(child)) return true
  return new Promise<boolean>((resolve) => {
    let settled = false
    const finish = (exited: boolean) => {
      if (settled) return
      settled = true
      resolve(exited)
    }
    child.once('exit', () => finish(true))
    setTimeout(() => {
      finish(hasGatewayProcessExited(child))
    }, timeoutMs).unref()
  })
}

function restoreDownloadedUpdateRetryState(pendingVersion: string | null): void {
  downloadedUpdateVersion = pendingVersion
  updateApplying = false
  isQuitting = false
  createApplicationMenu()
  setDesktopUpdateState({
    status: pendingVersion ? 'downloaded' : 'error',
    latestVersion: pendingVersion,
    progress: pendingVersion ? 100 : null,
  })
}

// Stop the owned gateway child and WAIT for it to exit before handing control to
// the installer. The gateway holds the listen port + a PID lock and (on Windows)
// open file handles under resources/runtime that the installer must overwrite —
// orphaning it breaks the next launch. Mirrors the uninstall quiesce path.
async function applyDownloadedUpdate(): Promise<void> {
  if (updateApplying) return
  if (!mockDownloadedUpdate && !downloadedUpdateVersion) return

  if (mockDownloadedUpdate) {
    const version = downloadedUpdateVersion || mockUpdateVersion() || app.getVersion()
    updateApplying = true
    setDesktopUpdateState({
      status: 'applying',
      latestVersion: version,
      progress: 100,
      error: null,
    })
    try {
      await showUpdateDialog({
        type: 'info',
        buttons: ['OK'],
        title: desktopT('update.mockInstallTitle'),
        message: desktopT('update.mockInstallTitle'),
        detail: desktopTv('update.mockInstallDetail', version),
      })
    } finally {
      downloadedUpdateVersion = version
      updateApplying = false
      createApplicationMenu()
      setDesktopUpdateState({
        status: 'downloaded',
        latestVersion: version,
        progress: 100,
        error: null,
      })
    }
    return
  }
  const pendingVersion = downloadedUpdateVersion
  updateApplying = true
  downloadedUpdateVersion = null
  createApplicationMenu()
  setDesktopUpdateState({
    status: 'applying',
    latestVersion: pendingVersion,
    progress: 100,
    error: null,
  })
  isQuitting = true
  const child = gatewayProcessForUpdateInstall()
  if (child) {
    if (gatewayProcess === child && gatewayState.owned) {
      updateGatewayShutdownProcess = child
      // We stay alive and await the exit below, so let the gateway take its
      // Windows HTTP graceful drain instead of an immediate TerminateProcess.
      allowGracefulShutdownWhileQuitting = true
      try {
        stopGateway()
      } finally {
        allowGracefulShutdownWhileQuitting = false
      }
    }
    const exited = await waitForGatewayProcessExit(child)
    if (!exited) {
      restoreDownloadedUpdateRetryState(pendingVersion)
      void showUpdateDialog({
        type: 'error',
        buttons: ['OK'],
        title: desktopT('update.errorTitle'),
        message: desktopT('update.errorTitle'),
        detail: desktopT('update.gatewayShutdownTimeout'),
      })
      return
    }
    if (updateGatewayShutdownProcess === child) updateGatewayShutdownProcess = null
  }
  // isSilent=false (show the platform installer UI where applicable),
  // isForceRunAfter=true (relaunch after install).
  try {
    autoUpdater.quitAndInstall(false, true)
  } catch (err) {
    restoreDownloadedUpdateRetryState(pendingVersion)
    void showUpdateDialog({
      type: 'error',
      buttons: ['OK'],
      title: desktopT('update.errorTitle'),
      message: desktopT('update.errorTitle'),
      detail: String(err instanceof Error ? err.message : err ?? ''),
    })
    // The owned gateway was stopped for the (now-failed) handoff and its exit was
    // swallowed as intentional (isQuitting was true). restoreDownloadedUpdateRetryState
    // cleared isQuitting, so bring the runtime back up instead of leaving the
    // window stranded on the dead gateway's Control UI.
    void openOrResumeDesktopApp()
  }
}

// Lets the gateway-served Control UI know whether THIS desktop runtime can
// apply updates natively right now. The web "a newer version is available"
// banner suppresses itself only when this is true, so unsupported platforms
// (e.g. unsigned Windows, or macOS running outside /Applications) still show
// the passive notice.
ipcMain.handle('desktop:update:supported', () => nativeAutoUpdateEnabled())
ipcMain.handle('desktop:update:state', () => desktopUpdateSnapshot())
ipcMain.handle('desktop:update:check', async () => {
  await checkForUpdates(true)
  return desktopUpdateSnapshot()
})
ipcMain.handle('desktop:update:download', async () => downloadDesktopUpdate())
ipcMain.handle('desktop:update:relaunch', async () => {
  await applyDownloadedUpdate()
  return desktopUpdateSnapshot()
})
ipcMain.handle('desktop:update:dismiss', async () => dismissDesktopUpdate())
ipcMain.handle('desktop:os-locale', () => desktopLocale)
ipcMain.handle('desktop:theme:set', (_event, payload: unknown) => (
  applyDesktopNativeTheme(normalizeDesktopNativeThemeSource(payload))
))
ipcMain.handle('gateway:status', () => ({ ...gatewayState }))
ipcMain.handle('gateway:cli-invocation', async () => {
  const runtime = await resolveGatewayRuntime()
  return buildCliInvocation({
    platform: process.platform,
    mode: runtime.mode,
    binaryPath: runtime.mode === 'bundled' ? runtime.command : undefined,
    repoRoot: runtime.mode === 'dev' ? repoRoot : undefined,
    stateDir: desktopHome(),
    configPath: desktopConfigPath(),
  })
})
ipcMain.handle('gateway:reveal-log', async () => {
  if (gatewayState.logPath) {
    await shell.showItemInFolder(gatewayState.logPath)
    return true
  }
  // Startup can fail before the gateway log path is assigned (e.g. onboarding or
  // port selection error), so Reveal log would otherwise be a dead button on the
  // error panel. Fall back to the always-present desktop lifecycle log.
  const desktopLogPath = join(app.getPath('userData'), 'logs', 'desktop.log')
  if (existsSync(desktopLogPath)) {
    await shell.showItemInFolder(desktopLogPath)
    return true
  }
  await shell.openPath(join(app.getPath('userData'), 'logs')).catch(() => null)
  return false
})
ipcMain.handle('desktop:settings:get', async () => loadDesktopSettings())
ipcMain.handle('desktop:settings:save', async (_event, payload: DesktopSettingsPayload) => saveDesktopSettings(payload))
ipcMain.handle('desktop:settings:reset', async () => {
  await resetDesktopSettings()
  forceOnboardingOnNextStartup = true
  const child = gatewayProcess && gatewayState.owned ? gatewayProcess : null
  if (child) {
    stopGateway()
    await waitForGatewayProcessExit(child)
  }
  clearReusableGatewayState()
  // This IPC is also reachable from the live Control UI (Settings → Runtime),
  // which stays on the now-dead gateway after the reset. Return the window to the
  // boot splash and re-run startup so onboarding re-runs, instead of stranding
  // the user on a dead page. (The boot.html caller also calls retryStartup; the
  // in-flight start is joined, not double-started.)
  bootError = null
  await currentMainWindow()?.loadFile(bootPagePath()).catch(() => null)
  void openOrResumeDesktopApp()
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
// Path note: OPENSQUILLA_STATE_DIR names the OpenSquilla home root. Both the
// gateway spawn and this uninstall CLI pass desktopHome()
// (<userData>/opensquilla), so config.toml + state/ resolve identically
// everywhere.
async function runUninstallCli(
  extraArgs: string[],
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const runtime = await resolveGatewayRuntime()
  const prefix = runtime.args.slice(0, -2) // drop the trailing ['gateway','run']
  const child = spawn(runtime.command, [...prefix, 'uninstall', ...extraArgs], {
    cwd: runtime.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      OPENSQUILLA_DESKTOP: '1',
      OPENSQUILLA_INSTALL_METHOD: 'desktop',
      OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
      OPENSQUILLA_STATE_DIR: desktopHome(),
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8:replace',
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
      buttons: [desktopT('uninstall.cancel'), desktopT('uninstall.deleteEverything')],
      defaultId: 0,
      cancelId: 0,
      title: desktopT('uninstall.confirmTitle'),
      message: desktopT('uninstall.confirmMessage'),
      detail: desktopT('uninstall.confirmDetail'),
    })
    if (response !== 1) return { ok: false, aborted: true, detail: 'cancelled' }
  }

  // Quiesce the owned gateway before the CLI touches files. Wait for the child to
  // actually EXIT (child.killed flips true the instant SIGTERM is sent, not when
  // the drain finishes), bounded by the kill deadline.
  isQuitting = true
  if (gatewayProcess && gatewayState.owned) {
    const child = gatewayProcess
    // We stay alive and await the exit, so let the gateway take its Windows HTTP
    // graceful drain instead of an immediate TerminateProcess.
    allowGracefulShutdownWhileQuitting = true
    try {
      stopGateway()
    } finally {
      allowGracefulShutdownWhileQuitting = false
    }
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
    transientPendingMigrationProviderSetup = null
    await rm(pendingMigrationProviderSetupPath(), { force: true }).catch(() => null)
    await rm(desktopMigrationResultPath(), { force: true }).catch(() => null)
    await rm(join(app.getPath('userData'), 'logs'), { recursive: true, force: true }).catch(() => null)
  }
  // The app keeps running after a successful data cleanup (the user closes it
  // later), so clear the quit latch — otherwise it stays true and silently
  // suppresses reporting of any later gateway crash.
  isQuitting = false
  return result
})

// ── Legacy home migration (Phase 3 entry points) ─────────────────────────────
// The import logic lives once in Python (`opensquilla migrate opensquilla`,
// dry-run by default); the desktop only detects candidates, orchestrates the
// gateway lifecycle, and spawns the bundled CLI — mirroring the uninstall flow
// above. Design: docs/features/legacy-home-migration-design.md (Phase 3).
async function runMigrateCli(
  extraArgs: string[],
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const runtime = await resolveGatewayRuntime()
  const prefix = runtime.args.slice(0, -2) // drop the trailing ['gateway','run']
  const child = spawn(runtime.command, [...prefix, 'migrate', 'opensquilla', ...extraArgs], {
    cwd: runtime.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      OPENSQUILLA_DESKTOP: '1',
      OPENSQUILLA_INSTALL_METHOD: 'desktop',
      OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath(),
      // OPENSQUILLA_STATE_DIR names the OpenSquilla HOME ROOT: the migrator's
      // import TARGET. It must match the gateway spawn (desktopHome()), or the
      // import would land in a home the gateway never reads.
      OPENSQUILLA_STATE_DIR: desktopHome(),
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8:replace',
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

// Run the migrate CLI in JSON mode and parse its report. A blocked run exits
// non-zero but still prints a valid report (items with status "error"), so ok
// and report are independent signals.
async function migrateSummaryJson(
  extraArgs: string[],
): Promise<{ ok: boolean; report: Record<string, unknown> | null; raw: string }> {
  const { ok, stdout, stderr } = await runMigrateCli([...extraArgs, '--json'])
  try {
    return { ok, report: JSON.parse(stdout) as Record<string, unknown>, raw: stdout }
  } catch {
    return { ok: false, report: null, raw: stdout || stderr }
  }
}

type DesktopMigrationPhase = 'preview' | 'applying' | 'done' | 'error'

// Coarse migration progress for renderers (same publish pattern as
// publishDesktopUpdateState): the onboarding card and the settings panel show a
// spinner/label off these while the CLI runs.
function publishDesktopMigrationProgress(phase: DesktopMigrationPhase, detail?: string): void {
  const payload = detail === undefined ? { phase } : { phase, detail }
  for (const window of BrowserWindow.getAllWindows()) {
    try {
      if (!window.isDestroyed()) window.webContents.send('desktop:migration:progress', payload)
    } catch {
      // A renderer can disappear while the import replaces its gateway origin.
      // Progress is advisory; lifecycle cleanup and restart must still run.
    }
  }
}

interface MigrationProviderPrefill {
  provider: string
  model: string
  baseUrl: string
  apiKeyEnv: string
  apiKey: string
}

interface PendingMigrationProviderSetup extends MigrationProviderPrefill {
  version: 1
  phase: 'applying' | 'needs-setup'
  source: string
  sourceKind: LegacyImportCandidate['kind']
  target: string
  knownReceiptIds: string[]
}

let transientPendingMigrationProviderSetup: PendingMigrationProviderSetup | null = null

function pendingMigrationProviderSetupPath(): string {
  return join(app.getPath('userData'), 'migration-provider-setup.json')
}

function migrationReceiptRoot(): string {
  return join(desktopHome(), 'migration', 'opensquilla')
}

async function listMigrationReceiptIds(): Promise<string[]> {
  try {
    const entries = await readdir(migrationReceiptRoot(), { withFileTypes: true })
    return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []
    throw error
  }
}

async function readPendingMigrationProviderSetup(): Promise<PendingMigrationProviderSetup | null> {
  if (transientPendingMigrationProviderSetup) return transientPendingMigrationProviderSetup
  let raw = ''
  try {
    raw = await readFile(pendingMigrationProviderSetupPath(), 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw new Error(`Could not read the pending desktop import record: ${String(error)}`)
  }
  let payload: Record<string, unknown>
  try {
    const parsed = JSON.parse(raw) as unknown
    const record = migrationRecord(parsed)
    if (!record) throw new Error('record root is not an object')
    payload = record
  } catch (error) {
    throw new Error(`The pending desktop import record is malformed: ${String(error)}`)
  }

  // Accept the short-lived pre-release marker shape as a needs-setup record so
  // users who hit this recovery path while testing are not stranded.
  const legacyShape = payload.phase === undefined
  const phase = legacyShape ? 'needs-setup' : payload.phase
  const source = legacyShape ? '' : String(payload.source || '')
  const sourceKind = legacyShape ? 'cli-home' : String(payload.sourceKind || '')
  const target = legacyShape ? desktopHome() : String(payload.target || '')
  if (
    !legacyShape
    && (
      payload.version !== 1
      || !Array.isArray(payload.knownReceiptIds)
      || payload.knownReceiptIds.some((value) => typeof value !== 'string')
    )
  ) {
    throw new Error('The pending desktop import record has invalid transaction metadata.')
  }
  const knownReceiptIds = legacyShape
    ? []
    : payload.knownReceiptIds as string[]
  if (
    (phase !== 'applying' && phase !== 'needs-setup')
    || !resolvedPathsEqual(target, desktopHome())
    || (!legacyShape && !source)
    || !['cli-home', 'windows-portable'].includes(sourceKind)
  ) {
    throw new Error('The pending desktop import record does not match this desktop profile.')
  }
  transientPendingMigrationProviderSetup = {
    version: 1,
    phase,
    source,
    sourceKind: sourceKind as LegacyImportCandidate['kind'],
    target,
    knownReceiptIds,
    provider: String(payload.provider || ''),
    model: String(payload.model || ''),
    baseUrl: String(payload.baseUrl || ''),
    apiKeyEnv: String(payload.apiKeyEnv || ''),
    // Secrets are always re-read from the imported target, never the marker.
    apiKey: '',
  }
  return transientPendingMigrationProviderSetup
}

async function persistPendingMigrationProviderSetup(
  pending: PendingMigrationProviderSetup,
): Promise<void> {
  const durable = { ...pending, apiKey: '' }
  mkdirSync(app.getPath('userData'), { recursive: true })
  await atomicWriteFile(
    pendingMigrationProviderSetupPath(),
    JSON.stringify(durable, null, 2),
    0o600,
  )
  transientPendingMigrationProviderSetup = durable
}

async function beginMigrationReconciliationIntent(
  candidate: LegacyImportCandidate,
): Promise<PendingMigrationProviderSetup> {
  const intent: PendingMigrationProviderSetup = {
    version: 1,
    phase: 'applying',
    source: candidate.path,
    sourceKind: candidate.kind,
    target: desktopHome(),
    knownReceiptIds: await listMigrationReceiptIds(),
    provider: '',
    model: '',
    baseUrl: '',
    apiKeyEnv: '',
    apiKey: '',
  }
  await persistPendingMigrationProviderSetup(intent)
  return intent
}

async function findAppliedReceiptForIntent(
  intent: PendingMigrationProviderSetup,
): Promise<{ transactionId: string; report: Record<string, unknown> } | null> {
  const known = new Set(intent.knownReceiptIds)
  const candidates = (await listMigrationReceiptIds())
    .filter((transactionId) => !known.has(transactionId))
    .sort()
    .reverse()
  for (const transactionId of candidates) {
    if (!MIGRATION_TRANSACTION_ID_RE.test(transactionId)) continue
    try {
      const report = JSON.parse(
        await readFile(join(migrationReceiptRoot(), transactionId, 'report.json'), 'utf8'),
      ) as unknown
      if (
        migrationReportValidationError(report, {
          source: intent.source,
          sourceKind: intent.sourceKind,
          target: intent.target,
          apply: true,
        }) === null
        && migrationReportErrors(report as Record<string, unknown>).length === 0
      ) {
        return { transactionId, report: report as Record<string, unknown> }
      }
    } catch {
      // Ignore incomplete/unrelated report directories and keep looking.
    }
  }
  return null
}

async function writePendingMigrationProviderSetup(
  prefill: MigrationProviderPrefill | null,
  intent: PendingMigrationProviderSetup,
): Promise<void> {
  const pending: PendingMigrationProviderSetup = {
    ...intent,
    phase: 'needs-setup',
    provider: prefill?.provider || '',
    model: prefill?.model || '',
    baseUrl: prefill?.baseUrl || '',
    apiKeyEnv: prefill?.apiKeyEnv || '',
    // A provider key never belongs in this durable prompt marker. The imported
    // target .env remains the source until the user confirms it into safeStorage.
    apiKey: '',
  }
  await persistPendingMigrationProviderSetup(pending)
}

async function clearPendingMigrationProviderSetup(): Promise<void> {
  transientPendingMigrationProviderSetup = null
  await rm(pendingMigrationProviderSetupPath(), { force: true })
}

async function scrubImportedProviderEnvEntry(envKey: string): Promise<void> {
  if (!envKey) return
  const envPath = join(desktopHome(), '.env')
  let raw = ''
  try {
    raw = await readFile(envPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return
    throw error
  }
  const lines = raw.split(/\r?\n/)
  const kept = lines.filter((line) => {
    const entry = line.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=/)
    return !entry || entry[1] !== envKey
  })
  if (kept.length === lines.length) return
  while (kept.length > 0 && kept[kept.length - 1] === '') kept.pop()
  await atomicWriteFile(envPath, kept.length > 0 ? `${kept.join('\n')}\n` : '', 0o600)
}

async function loadPendingMigrationProviderSetup(): Promise<MigrationProviderPrefill | null> {
  const pending = await readPendingMigrationProviderSetup()
  if (!pending) return null
  if (pending.phase === 'applying') {
    throw new Error('An interrupted desktop import still needs reconciliation.')
  }
  const live = readMigratedProviderPrefill()
  return {
    provider: live?.provider || pending.provider,
    model: live?.model || pending.model,
    baseUrl: live?.baseUrl || pending.baseUrl,
    apiKeyEnv: live?.apiKeyEnv || pending.apiKeyEnv,
    apiKey: live?.apiKey || '',
  }
}

async function reconcileImportedDesktopCredential(
  intent: PendingMigrationProviderSetup,
): Promise<{ requiresSetup: boolean }> {
  const prefill = readMigratedProviderPrefill()
  if (prefill?.provider) {
    const defaults = providerDefaults(prefill.provider)
    if (!defaults.requiresApiKey || prefill.apiKey) {
      try {
        await saveDesktopCredential(prefill)
        await scrubImportedProviderEnvEntry(prefill.apiKeyEnv)
        await clearPendingMigrationProviderSetup()
        return { requiresSetup: false }
      } catch (error) {
        desktopLog('migration_credential_adoption_failed', {
          error: error instanceof Error ? error.message : String(error),
        })
      }
    }
  }
  await writePendingMigrationProviderSetup(prefill, intent)
  return { requiresSetup: true }
}

async function recoverPendingMigrationReconciliation(): Promise<void> {
  const pending = await readPendingMigrationProviderSetup()
  if (!pending || pending.phase !== 'applying') return
  const receipt = await findAppliedReceiptForIntent(pending)
  if (!receipt) {
    // The commit journal has already been recovered before this runs. With no
    // new target-side applied receipt, the attempted import never published.
    await clearPendingMigrationProviderSetup()
    return
  }
  await reconcileImportedDesktopCredential(pending)
}

// After a successful apply the migrator has rewritten the target config.toml
// and .env. Read the [llm] section back (line-based, like the privacy-config
// reader — the file is generated, simple TOML) so the onboarding provider step
// starts prefilled from the imported connection. The api key travels only over
// the onboarding IPC response — the same trust boundary as saveOnboarding — and
// is never logged and never part of any report.
function readMigratedProviderPrefill(): MigrationProviderPrefill | null {
  let raw = ''
  try {
    raw = readFileSync(desktopConfigPath(), 'utf8')
  } catch {
    return null
  }
  let inLlmSection = false
  const values: Record<string, string> = {}
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const section = line.match(/^\[([^\]]+)\]$/)
    if (section) {
      inLlmSection = section[1]?.trim() === 'llm'
      continue
    }
    if (!inLlmSection) continue
    const setting = line.match(/^([A-Za-z0-9_]+)\s*=\s*("(?:[^"\\]|\\.)*")\s*$/)
    if (!setting) continue
    try {
      values[setting[1] ?? ''] = JSON.parse(setting[2] ?? '""') as string
    } catch {
      continue
    }
  }
  const provider = (values.provider || '').trim()
  if (!provider) return null
  const apiKeyEnv = (values.api_key_env || '').trim()
  let apiKey = ''
  if (apiKeyEnv) {
    try {
      const envRaw = readFileSync(join(desktopHome(), '.env'), 'utf8')
      for (const envLine of envRaw.split(/\r?\n/)) {
        const entry = envLine.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)$/)
        if (!entry || entry[1] !== apiKeyEnv) continue
        apiKey = String(entry[2] ?? '').trim().replace(/^(["'])(.*)\1$/, '$2')
      }
    } catch {
      // No migrated .env; the user types the key as usual.
    }
  }
  return {
    provider,
    model: (values.model || '').trim(),
    baseUrl: (values.base_url || '').trim(),
    apiKeyEnv,
    apiKey,
  }
}

interface TrustedDesktopMigrationPreview {
  id: string
  candidate: LegacyImportCandidate
  report: Record<string, unknown>
  createdAt: number
}

interface DesktopMigrationResult {
  id: string
  at: string
  ok: boolean
  migrationApplied: boolean
  restartOk: boolean
  requiresProviderSetup: boolean
  detail?: string
}

const DESKTOP_MIGRATION_PREVIEW_TTL_MS = 10 * 60 * 1000
let trustedDesktopMigrationPreview: TrustedDesktopMigrationPreview | null = null

function migrationPreviewAllowsApply(
  report: Record<string, unknown>,
  overwrite: boolean,
): boolean {
  const errors = migrationReportErrors(report)
  if (errors.length === 0) return !overwrite
  return overwrite
    && errors.length === 1
    && errors[0]?.kind === 'preflight/target'
}

function desktopMigrationResultPath(): string {
  return join(app.getPath('userData'), 'migration-last-result.json')
}

async function persistDesktopMigrationResult(result: DesktopMigrationResult): Promise<void> {
  try {
    mkdirSync(app.getPath('userData'), { recursive: true })
    await atomicWriteFile(
      desktopMigrationResultPath(),
      JSON.stringify(result, null, 2),
      0o600,
    )
  } catch (error) {
    desktopLog('migration_result_persist_failed', {
      error: error instanceof Error ? error.message : String(error),
    })
  }
}

async function takeDesktopMigrationResult(): Promise<DesktopMigrationResult | null> {
  let raw = ''
  try {
    raw = await readFile(desktopMigrationResultPath(), 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
  const parsed = migrationRecord(JSON.parse(raw))
  if (!parsed) throw new Error('Saved desktop migration result is malformed.')
  const result: DesktopMigrationResult = {
    id: String(parsed.id || ''),
    at: String(parsed.at || ''),
    ok: parsed.ok === true,
    migrationApplied: parsed.migrationApplied === true,
    restartOk: parsed.restartOk === true,
    requiresProviderSetup: parsed.requiresProviderSetup === true,
    ...(typeof parsed.detail === 'string' && parsed.detail ? { detail: parsed.detail } : {}),
  }
  if (!result.id || !result.at) throw new Error('Saved desktop migration result is malformed.')
  await rm(desktopMigrationResultPath(), { force: true })
  return result
}

ipcMain.handle('desktop:migration:summary', async () => {
  trustedDesktopMigrationPreview = null
  const candidate = detectLegacyImportCandidate()
  if (!candidate) return { ok: true, candidate: null, report: null }
  // Dry-run is read-only, so the running gateway is deliberately left alone.
  publishDesktopMigrationProgress('preview')
  const { ok, report, raw } = await migrateSummaryJson([
    '--source', candidate.path, '--kind', candidate.kind,
  ])
  const validationError = migrationReportValidationError(report, {
    source: candidate.path,
    sourceKind: candidate.kind,
    target: desktopHome(),
    apply: false,
  })
  if (validationError || !report) {
    const detail = validationError || raw || 'Invalid migration report'
    publishDesktopMigrationProgress('error', detail)
    return { ok: false, candidate, report: null, raw: detail }
  }
  const preview: TrustedDesktopMigrationPreview = {
    id: randomUUID(),
    candidate,
    report,
    createdAt: Date.now(),
  }
  trustedDesktopMigrationPreview = preview
  publishDesktopMigrationProgress(ok ? 'done' : 'error')
  return { ok, candidate, report, previewId: preview.id }
})

ipcMain.handle('desktop:migration:run', async (
  _event,
  payload?: { overwrite?: boolean; previewId?: string },
) => {
  const preview = trustedDesktopMigrationPreview
  if (
    !preview
    || payload?.previewId !== preview.id
    || Date.now() - preview.createdAt > DESKTOP_MIGRATION_PREVIEW_TTL_MS
  ) {
    trustedDesktopMigrationPreview = null
    return {
      ok: false,
      report: null,
      detail: 'The migration preview is missing or expired. Preview the import again.',
    }
  }
  const candidate = preview.candidate
  const overwrite = Boolean(payload?.overwrite)
  if (!migrationPreviewAllowsApply(preview.report, overwrite)) {
    trustedDesktopMigrationPreview = null
    return {
      ok: false,
      report: preview.report,
      detail: 'The approved preview does not permit this import mode. Preview again.',
    }
  }
  if (
    !looksLikeOpenSquillaHome(candidate.path)
    || sourceWasImportedToTarget(candidate.path, desktopHome())
  ) {
    trustedDesktopMigrationPreview = null
    return {
      ok: false,
      report: preview.report,
      detail: 'The approved migration source changed after preview. Preview again.',
    }
  }
  if (overwrite) {
    const options: Electron.MessageBoxOptions = {
      type: 'warning',
      buttons: [desktopT('migration.overwriteCancel'), desktopT('migration.overwriteConfirm')],
      defaultId: 0,
      cancelId: 0,
      title: desktopT('migration.overwriteTitle'),
      message: desktopT('migration.overwriteMessage'),
      detail: `${desktopT('migration.overwriteDetail')}\n\n${candidate.path}`,
    }
    const window = currentMainWindow()
    const confirmation = window
      ? await dialog.showMessageBox(window, options)
      : await dialog.showMessageBox(options)
    if (confirmation.response !== 1) {
      return { ok: false, aborted: true, report: preview.report, detail: 'cancelled' }
    }
  }
  trustedDesktopMigrationPreview = null

  // A live gateway not owned by this process must remain attached and untouched.
  // Do this before setting the quit latch so a refusal cannot suppress its later
  // crash reporting or fall through into the owned-gateway restart path.
  if ((!gatewayProcess || !gatewayState.owned) && gatewayState.url) {
    if (await healthCheck(gatewayState.url)) {
      const refused: DesktopMigrationResult = {
        id: randomUUID(),
        at: new Date().toISOString(),
        ok: false,
        migrationApplied: false,
        restartOk: true,
        requiresProviderSetup: false,
        detail: 'A gateway is still serving this profile; stop it and retry.',
      }
      await persistDesktopMigrationResult(refused)
      return { ...refused, report: null }
    }
  }

  publishDesktopMigrationProgress('applying')
  let report: Record<string, unknown> | null = null
  let migrationVerified = false
  let migrationApplied = false
  let restartOk = false
  let requiresProviderSetup = false
  let detail = ''
  let intent: PendingMigrationProviderSetup | null = null
  let restartAllowed = true
  let shouldRestart = true
  isQuitting = true
  try {
    // Quiesce the owned gateway before the CLI writes (the uninstall-run
    // pattern): wait for the child to actually EXIT, bounded by the kill deadline.
    if (gatewayProcess && gatewayState.owned) {
      const child = gatewayProcess
      // We stay alive and await the exit, so let the gateway take its Windows
      // HTTP graceful drain instead of an immediate TerminateProcess.
      allowGracefulShutdownWhileQuitting = true
      try {
        stopGateway()
      } finally {
        allowGracefulShutdownWhileQuitting = false
      }
      const exited = await waitForGatewayProcessExit(child)
      if (!exited) {
        // Keep the still-live child visible to the rest of the lifecycle code and
        // refuse both the import and a replacement spawn against the same profile.
        gatewayProcess = child
        gatewayState.owned = true
        gatewayState.status = 'error'
        gatewayState.error = 'The desktop gateway did not exit before the import deadline.'
        restartAllowed = false
        throw new Error(gatewayState.error)
      }
    }

    // Refuse while an unmanaged gateway still serves this profile — the import
    // must not race live sessions.db/scheduler.db writers.
    if (gatewayState.url && (await healthCheck(gatewayState.url))) {
      gatewayState.owned = false
      gatewayState.status = 'ready'
      shouldRestart = false
      throw new Error('A gateway is still serving this profile; stop it and retry.')
    }

    // The intent is outside the target tree, so it survives target replacement.
    // Startup can use it plus a new target-side receipt to finish credential
    // adoption even if Electron dies after the Python commit but before this IPC
    // handler receives stdout.
    intent = await beginMigrationReconciliationIntent(candidate)
    const result = await runMigrateCli([
      '--source', candidate.path, '--kind', candidate.kind, '--apply',
      ...(overwrite ? ['--overwrite'] : []),
      '--json',
    ])
    try {
      report = migrationRecord(JSON.parse(result.stdout))
    } catch {
      report = null
    }
    const validationError = migrationReportValidationError(report, {
      source: candidate.path,
      sourceKind: candidate.kind,
      target: desktopHome(),
      apply: true,
    })
    migrationVerified = result.ok
      && report !== null
      && validationError === null
      && migrationReportErrors(report).length === 0
    detail = migrationVerified
      ? ''
      : (validationError || result.stderr || result.stdout || 'Invalid migration report').slice(-2000)
  } catch (error) {
    detail = error instanceof Error ? error.message : String(error)
  } finally {
    if (intent) {
      try {
        const receipt = await findAppliedReceiptForIntent(intent)
        if (receipt) {
          migrationApplied = true
          if (!migrationVerified) report = receipt.report
          // Publication of a validated, previously-unseen target receipt is the
          // durable commit authority. The CLI child can lose stdout or exit
          // nonzero after that atomic rename without making the import a failure.
          migrationVerified = true
          const reconciliation = await reconcileImportedDesktopCredential(intent)
          requiresProviderSetup = reconciliation.requiresSetup
        } else {
          if (migrationVerified) {
            detail = 'The migration command succeeded without a valid target-side receipt.'
            migrationVerified = false
          }
          await clearPendingMigrationProviderSetup()
        }
      } catch (error) {
        migrationVerified = false
        const reconciliationError = error instanceof Error ? error.message : String(error)
        detail = detail ? `${detail}; ${reconciliationError}` : reconciliationError
      }
    }
    publishDesktopMigrationProgress(migrationVerified ? 'done' : 'error', detail || undefined)
    // Restart via the boot splash on every path. The imported profile is not
    // considered ready until the replacement gateway is healthy (and, when a
    // key could not be adopted, the durable provider-confirmation flow finishes).
    isQuitting = false
    if (restartAllowed && shouldRestart) {
      clearReusableGatewayState()
      bootError = null
      await currentMainWindow()?.loadFile(bootPagePath()).catch(() => null)
      await openOrResumeDesktopApp()
      restartOk = gatewayState.status === 'ready'
        && Boolean(gatewayState.url)
        && await healthCheck(gatewayState.url)
    } else if (!shouldRestart) {
      restartOk = Boolean(gatewayState.url) && await healthCheck(gatewayState.url)
    }
  }

  if (migrationApplied && !restartOk && !detail) {
    detail = 'Import applied, but the desktop gateway did not become healthy.'
  }
  const finalResult: DesktopMigrationResult = {
    id: randomUUID(),
    at: new Date().toISOString(),
    ok: migrationVerified && restartOk,
    migrationApplied,
    restartOk,
    requiresProviderSetup,
    ...(detail ? { detail } : {}),
  }
  await persistDesktopMigrationResult(finalResult)
  return { ...finalResult, report }
})

ipcMain.handle('desktop:migration:last-result', takeDesktopMigrationResult)

ipcMain.handle('desktop:boot:state', () => ({
  status: bootStatus,
  error: bootError,
  gateway: { ...gatewayState },
}))
ipcMain.handle('desktop:boot:retry', async () => {
  // Backs both the boot-error "Retry" button and the Control UI "Restart
  // runtime" action. If a start attempt is already in flight, join it and clear
  // the stale bootError so the reloaded splash shows live progress instead of
  // instantly re-rendering the previous error panel.
  if (gatewayStartPromise) {
    bootError = null
    void openOrResumeDesktopApp()
    return { ok: true }
  }

  // Otherwise force a real runtime restart. "Restart runtime" must relaunch the
  // child even when the current gateway is healthy, so always tear an owned
  // gateway down and wait for it to release its port + PID lock before
  // openOrResumeDesktopApp respawns it — never reuse the existing one here.
  if (gatewayProcess && gatewayState.owned) {
    const previousChild = gatewayProcess
    stopGateway()
    await waitForGatewayProcessExit(previousChild)
  }
  clearReusableGatewayState()
  bootError = null
  await currentMainWindow()?.loadFile(bootPagePath()).catch(() => null)

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
    modelRoutingModes: ['squilla_router', 'direct', 'llm_ensemble'],
    modes: ['recommended', 'openrouter-mix', 'disabled'],
    defaultTier: 'c1',
    textTiers: TEXT_ROUTER_TIERS,
    profiles: ROUTER_PROFILES,
  },
}))
ipcMain.handle('desktop:onboarding:save', async (_event, payload: OnboardingPayload) => {
  // Only honor this while an onboarding flow is actually awaiting a result. The
  // same preload bridge is attached to the Control UI window, so without this
  // guard any script on the gateway-served page could rewrite the credential and
  // regenerate config.toml outside onboarding.
  if (!resolveOnboarding) return { ok: false, error: 'No onboarding in progress.' }
  const pendingMigration = await readPendingMigrationProviderSetup()
  const credential = await saveDesktopCredential(payload)
  if (pendingMigration?.phase === 'needs-setup') {
    await scrubImportedProviderEnvEntry(pendingMigration.apiKeyEnv)
  }
  await clearPendingMigrationProviderSetup()
  applyDesktopLocaleChoice(payload.locale)
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
  // The onboarding "Quit" button routes here; it is a deliberate exit, so quit
  // the app instead of surfacing the cancellation as a boot failure panel.
  app.quit()
  return { ok: true }
})
ipcMain.handle('desktop:onboarding:migrate:preview', async () => {
  // Same guard as desktop:onboarding:save: the preload bridge is also attached
  // to the Control UI window, so these only respond while onboarding awaits.
  // The source path/kind come from the main process's own detection, never
  // from the renderer.
  if (!resolveOnboarding) return { ok: false, error: 'No onboarding in progress.' }
  const candidate = onboardingMigrationCandidate
  if (!candidate) return { ok: false, error: 'No legacy OpenSquilla home was detected.' }
  onboardingMigrationPreviewApprovedAt = 0
  publishDesktopMigrationProgress('preview')
  const { ok, report, raw } = await migrateSummaryJson([
    '--source', candidate.path, '--kind', candidate.kind,
  ])
  const validationError = migrationReportValidationError(report, {
    source: candidate.path,
    sourceKind: candidate.kind,
    target: desktopHome(),
    apply: false,
  })
  const approved = ok
    && report !== null
    && validationError === null
    && migrationReportErrors(report).length === 0
  if (approved) onboardingMigrationPreviewApprovedAt = Date.now()
  publishDesktopMigrationProgress(approved ? 'done' : 'error', validationError || undefined)
  return validationError
    ? { ok: false, report: null, raw: validationError }
    : { ok, report, raw }
})
ipcMain.handle('desktop:onboarding:migrate:apply', async () => {
  if (!resolveOnboarding) return { ok: false, error: 'No onboarding in progress.' }
  const candidate = onboardingMigrationCandidate
  if (!candidate) return { ok: false, error: 'No legacy OpenSquilla home was detected.' }
  if (
    !onboardingMigrationPreviewApprovedAt
    || Date.now() - onboardingMigrationPreviewApprovedAt > DESKTOP_MIGRATION_PREVIEW_TTL_MS
  ) {
    onboardingMigrationPreviewApprovedAt = 0
    return { ok: false, error: 'Preview the import again before applying it.' }
  }
  onboardingMigrationPreviewApprovedAt = 0
  // Onboarding runs before the first gateway spawn, so there is nothing to
  // quiesce here — the import lands before boot creates sessions.db and before
  // scheduler jobs (imported paused) are scanned.
  publishDesktopMigrationProgress('applying')
  let intent: PendingMigrationProviderSetup | null = null
  try {
    intent = await beginMigrationReconciliationIntent(candidate)
    const result = await migrateSummaryJson([
      '--source', candidate.path, '--kind', candidate.kind, '--apply',
    ])
    const validationError = migrationReportValidationError(result.report, {
      source: candidate.path,
      sourceKind: candidate.kind,
      target: desktopHome(),
      apply: true,
    })
    const receipt = await findAppliedReceiptForIntent(intent)
    if (!receipt) {
      await clearPendingMigrationProviderSetup()
      const detail = validationError || result.raw || 'Import did not publish a valid receipt.'
      publishDesktopMigrationProgress('error', detail)
      return { ok: false, report: result.report, raw: detail, prefill: null }
    }

    const prefill = readMigratedProviderPrefill()
    await writePendingMigrationProviderSetup(prefill, intent)
    const outputVerified = result.ok
      && result.report !== null
      && validationError === null
      && migrationReportErrors(result.report).length === 0
    // The target-side receipt is the crash-safe publication authority. If the
    // child lost stdout after commit, continue onboarding from that validated
    // receipt rather than offering a destructive retry against imported data.
    publishDesktopMigrationProgress('done')
    return {
      ok: true,
      report: outputVerified ? result.report : receipt.report,
      raw: outputVerified ? result.raw : (validationError || result.raw),
      prefill,
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    if (intent) {
      const receipt = await findAppliedReceiptForIntent(intent).catch(() => null)
      if (receipt) {
        const prefill = readMigratedProviderPrefill()
        await writePendingMigrationProviderSetup(prefill, intent)
        publishDesktopMigrationProgress('done')
        return { ok: true, report: receipt.report, raw: detail, prefill }
      }
      await clearPendingMigrationProviderSetup().catch(() => null)
    }
    publishDesktopMigrationProgress('error', detail)
    return { ok: false, report: null, raw: detail, prefill: null }
  }
})

// Set once the Windows graceful-drain-on-quit sequence has run so the re-issued
// quit (after app.exit is deferred) is not intercepted a second time.
let windowsQuitDrainDone = false

app.on('before-quit', (event) => {
  desktopLog('before_quit', { platform: process.platform, drained: windowsQuitDrainDone })
  isQuitting = true
  // On Windows there is no real SIGTERM, so the normal close path would
  // TerminateProcess the gateway with no drain (unlike the update/uninstall
  // paths which already wait for a graceful exit). Give the daily close path the
  // same graceful drain: defer the quit once, ask the gateway to shut down over
  // HTTP, wait for the child to exit (bounded), then exit for real. Fall back to
  // a hard terminate on timeout via stopGateway's own backstop.
  if (
    process.platform === 'win32' &&
    !windowsQuitDrainDone &&
    gatewayProcess &&
    gatewayState.owned &&
    !hasGatewayProcessExited(gatewayProcess)
  ) {
    event.preventDefault()
    const child = gatewayProcess
    void (async () => {
      try {
        const accepted = await requestGatewayShutdown(gatewayState.url || '')
        desktopLog('quit_gateway_shutdown_requested', { accepted })
        let hardTerminated = false
        let exited = false
        if (!accepted) {
          hardTerminated = true
          hardTerminateGatewayProcess(child)
          exited = await waitForGatewayProcessExit(child, GATEWAY_HARD_KILL_BACKSTOP_MS)
          await clearKnownOwnedGatewayPidFile()
        } else {
          exited = await waitForGatewayProcessExit(child)
          if (!exited) {
            hardTerminated = true
            hardTerminateGatewayProcess(child)
            exited = await waitForGatewayProcessExit(child, GATEWAY_HARD_KILL_BACKSTOP_MS)
            await clearKnownOwnedGatewayPidFile()
          }
        }
        desktopLog('quit_gateway_exit', { exited, hardTerminated })
      } finally {
        windowsQuitDrainDone = true
        app.exit(0)
      }
    })()
    return
  }
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

// Bounded retry for the single-instance lock. A relaunch immediately after
// closing the previous instance can race that instance's teardown (Electron
// exit + gateway TerminateProcess), during which the lock is briefly still
// held. Without a retry the new process silently quits and no window appears
// (issue #446). Retry synchronously for a short window, then — if still
// unavailable — surface an explicit error instead of exiting silently.
function acquireSingleInstanceLockWithRetry(): boolean {
  const deadline = Date.now() + 5_000
  // Atomics.wait blocks this thread without an event loop (app.whenReady has not
  // fired) and, unlike a Date.now() spin, does not peg a CPU core. Larger sleep
  // slices also cut the retry count — each failed requestSingleInstanceLock
  // notifies the running instance (firing its second-instance handler).
  const sleepSignal = new Int32Array(new SharedArrayBuffer(4))
  let attempt = 0
  for (;;) {
    attempt += 1
    if (app.requestSingleInstanceLock()) {
      desktopLog('single_instance_lock_acquired', { attempt })
      return true
    }
    const remaining = deadline - Date.now()
    if (remaining <= 0) {
      desktopLog('single_instance_lock_unavailable', { attempt })
      return false
    }
    Atomics.wait(sleepSignal, 0, 0, Math.min(400, remaining))
  }
}

desktopLog('launch', { platform: process.platform, argv: process.argv.length })
const gotSingleInstanceLock = acquireSingleInstanceLockWithRetry()

if (!gotSingleInstanceLock) {
  // Another instance genuinely holds the lock past the retry window. Signal it
  // to surface its window (the second-instance handler calls
  // openOrResumeDesktopApp), show an explicit dialog so the launch is never a
  // silent no-op, then quit.
  desktopLog('launch_aborted_lock_held')
  try {
    // This runs before app.whenReady, so app.getLocale() is unreliable; fall back
    // to the persisted onboarding locale (a plain file read) for this dialog.
    desktopLocale = loadPersistedDesktopLocale() ?? desktopLocale
    dialog.showErrorBox(
      desktopT('launch.alreadyRunningTitle'),
      desktopT('launch.alreadyRunningMessage'),
    )
  } catch {
    // Dialog is best-effort; the diagnostic log is the durable record.
  }
  app.quit()
} else {
  app.on('second-instance', () => {
    desktopLog('second_instance')
    void openOrResumeDesktopApp()
  })

  void app.whenReady().then(async () => {
    app.name = 'OpenSquilla'
    desktopLocale = loadPersistedDesktopLocale() ?? resolveDesktopLocale()
    createApplicationMenu()
    void openOrResumeDesktopApp()
    initAutoUpdater()
    if (mockUpdateVersion() !== null) {
      setTimeout(() => {
        void checkForUpdates(false)
      }, 1_000).unref()
    } else if (autoUpdateSupported()) {
      // Delay the silent startup check so it doesn't compete with gateway boot.
      setTimeout(() => {
        void checkForUpdates(false)
      }, 12_000).unref()
    }
  })
}
