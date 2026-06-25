import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSetupChannelsForm } from '@/composables/setup/useSetupChannelsForm'
import { useSetupCapabilitiesForm } from '@/composables/setup/useSetupCapabilitiesForm'
import { useSetupProviderForm } from '@/composables/setup/useSetupProviderForm'
import { useSetupRouterForm } from '@/composables/setup/useSetupRouterForm'
import { useSettingsPromotedForm, DEFAULT_LLM_TIMEOUT_SECONDS } from '@/composables/setup/useSettingsPromotedForm'
import { useSettingsSection } from '@/composables/setup/useSettingsSection'
import { SETTINGS_SECTIONS, type SettingsSectionId } from '@/composables/setup/settingsSections'
import { useRpcStore } from '@/stores/rpc'
import { useToasts } from '@/composables/useToasts'
import { copyTextWithFallback } from '@/utils/browser'
import { TEXT_TIERS, routerTierLabel } from '@/utils/chat/routerTiers'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export { SETTINGS_SECTIONS } from '@/composables/setup/settingsSections'
export type { SettingsSectionId } from '@/composables/setup/settingsSections'

const READINESS_LABELS: Record<string, string> = {
  ok: 'Ready',
  optional: 'Optional',
  missing: 'Missing',
  degraded: 'Needs action',
  unknown: 'Check',
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderSpec {
  providerId: string
  label: string
  runtimeSupported?: boolean
  routerSupported?: boolean
  fields?: FieldSpec[]
  whatYouNeed?: string[]
  envKey?: string
  requiresApiKey?: boolean
  defaultBaseUrl?: string
  defaultModel?: string
}

interface FieldSpec {
  name: string
  label: string
  type?: string
  required?: boolean
  default?: string | boolean | number
  placeholder?: string
  description?: string
  secret?: boolean
  choices?: string[]
  showWhen?: Record<string, string>
}

interface ChannelSpec {
  type: string
  label: string
  fields?: FieldSpec[]
  whatYouNeed?: string[]
}

interface ChannelStatusRow {
  name: string
  type?: string
  connected?: boolean
  status?: string
  configured?: boolean
}

interface TierConfig {
  provider?: string
  model?: string
  thinkingLevel?: string
  thinking_level?: string
  supportsImage?: boolean
  supports_image?: boolean
}

interface SectionDetail {
  status?: string
  blocking?: boolean
  actionRequired?: boolean
  required?: boolean
  label?: string
  detail?: string
}

interface OnboardingStatus {
  needsOnboarding?: boolean
  hasConfig?: boolean
  llmSource?: string
  sectionDetails?: Record<string, SectionDetail>
  envRecoveryCommands?: Array<{ section?: string; command?: string; label?: string }>
  configPath?: string
  channelCount?: number
  searchConfigured?: boolean
  searchSource?: string
  searchEnvKey?: string
  imageGenerationEnabled?: boolean
  imageGenerationConfigured?: boolean
  imageGenerationSource?: string
  imageGenerationEnvKey?: string
  imageGenerationProvider?: string
  imageGenerationPrimary?: string
  memoryEmbeddingConfigured?: boolean
  memoryEmbeddingSource?: string
  memoryEmbeddingEnvKey?: string
  memoryEmbeddingProvider?: string
}

interface OnboardingCatalog {
  providers?: ProviderSpec[]
  routerProfiles?: {
    profiles?: Array<{ providerId: string; tiers?: Record<string, TierConfig> }>
    defaultTier?: string
  }
  channels?: ChannelSpec[]
  searchProviders?: ProviderSpec[]
  imageGenerationProviders?: ProviderSpec[]
  memoryEmbeddingProviders?: ProviderSpec[]
}

interface ConfigData {
  llm?: {
    provider?: string
    model?: string
    base_url?: string
    proxy?: string
    api_key_env?: string
    api_key?: string
    [key: string]: unknown
  }
  llm_request_timeout_seconds?: number
  squilla_router?: {
    enabled?: boolean
    default_tier?: string
    visual_mode?: string
    tiers?: Record<string, TierConfig>
  }
  search_provider?: string
  search_api_key_env?: string
  search_max_results?: number
  search_proxy?: string
  search_use_env_proxy?: boolean
  search_fallback_policy?: string
  search_diagnostics?: boolean
  memory?: {
    auto_capture_enabled?: boolean
    embedding?: {
      provider?: string
      mode?: string
      remote?: {
        model?: string
        api_key?: string
        api_key_env?: string
        base_url?: string
      }
      local?: { onnx_dir?: string }
      ollama?: { model?: string; base_url?: string }
    }
  }
  image_generation?: {
    providers?: Record<string, { api_key_env?: string; base_url?: string }>
  }
  audio?: {
    enabled?: boolean
    providers?: Record<string, { api_key?: string; api_key_env?: string }>
  }
}

export interface SettingsActionItem {
  label: string
  section: SettingsSectionId
}

export function useSetupCatalog() {
// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const { pushToast } = useToasts()

const catalog = ref<OnboardingCatalog>({})
const status = ref<OnboardingStatus>({})
const config = ref<ConfigData>({})
const channelStatus = ref<{ channels: ChannelStatusRow[] }>({ channels: [] })
const loaded = ref(false)
const { section, setSection } = useSettingsSection('provider')

const providerForm = useSetupProviderForm()
const routerForm = useSetupRouterForm()
const channelsForm = useSetupChannelsForm()
const capabilitiesForm = useSetupCapabilitiesForm()
const promotedForm = useSettingsPromotedForm()

let pollTimer: ReturnType<typeof setInterval> | null = null

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(async () => {
  await loadData()
  loaded.value = true
  startChannelPolling()
})

onUnmounted(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    const [cat, st, cfg, chStatus] = await Promise.all([
      rpc.call<OnboardingCatalog>('onboarding.catalog'),
      rpc.call<OnboardingStatus>('onboarding.status'),
      rpc.call<ConfigData>('config.get'),
      rpc.call<{ channels: ChannelStatusRow[] }>('channels.status').catch(() => ({ channels: [] })),
    ])
    catalog.value = cat || {}
    status.value = st || {}
    config.value = cfg || {}
    channelStatus.value = chStatus || { channels: [] }

    // Initialize form values from config
    providerForm.initFromConfig(config.value.llm || {}, status.value, runtimeProviders.value)
    routerForm.initFromConfig(config.value.squilla_router || {}, currentRouterProfile.value?.tiers || {})
    capabilitiesForm.initSearchFromConfig(config.value, searchProviders.value)
    capabilitiesForm.initMemoryFromConfig(config.value)
    capabilitiesForm.initImageFromConfig(config.value, status.value, imageProviders.value)
    channelsForm.initFromCatalog(catalog.value.channels || [])
    promotedForm.initFromConfig(config.value)
  } catch (err) {
    pushToast('Failed to load settings: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function loadChannelStatus() {
  try {
    channelStatus.value = await rpc.call<{ channels: ChannelStatusRow[] }>('channels.status')
  } catch {
    channelStatus.value = { channels: [] }
  }
}

function startChannelPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    if (section.value !== 'channels') return
    await loadChannelStatus()
  }, 5000)
}

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const currentProvider = computed(() => (config.value.llm || {}).provider || '')
const currentProviderConfig = computed(() => config.value.llm || {})
const hasSavedProvider = computed(() => Boolean(currentProvider.value) && status.value.hasConfig !== false)

const runtimeProviders = computed(() => (catalog.value.providers || []).filter(p => p.runtimeSupported))
const catalogChannels = computed(() => catalog.value.channels || [])
const searchProviders = computed(() => (catalog.value.searchProviders || []).filter(p => p.runtimeSupported))
const imageProviders = computed(() => (catalog.value.imageGenerationProviders || []).filter(p => p.runtimeSupported))
const memoryProviders = computed(() => catalog.value.memoryEmbeddingProviders || [])
const routerProfiles = computed(() => catalog.value.routerProfiles?.profiles || [])
const currentRouterProfile = computed(() => routerProfiles.value.find(p => p.providerId === currentProvider.value))

const providerSpec = computed(() => runtimeProviders.value.find(p => p.providerId === providerForm.selectedProvider.value) || null)
const providerFields = computed(() => providerSpec.value?.fields || [])
const providerCoreFields = computed(() => providerFields.value.filter(f => !isProviderAdvancedField(f)))
const providerAdvancedFields = computed(() => providerFields.value.filter(f => isProviderAdvancedField(f)))

const providerSummary = computed(() => {
  if (!hasSavedProvider.value) return 'not configured'
  const spec = runtimeProviders.value.find(p => p.providerId === currentProvider.value)
  return spec?.label || currentProvider.value
})

const routerSupportText = computed(() => {
  if (!providerSpec.value) return 'choose provider'
  return providerSpec.value.routerSupported === true ? 'SquillaRouter ready' : 'Direct only'
})

const routerSupportTone = computed(() => {
  if (!providerSpec.value) return 'is-neutral'
  return providerSpec.value.routerSupported === true ? 'is-ready' : 'is-direct'
})

const providerNeeds = computed(() => {
  if (!providerSpec.value) return ['Choose a provider to see required fields.']
  return providerSpec.value.whatYouNeed || []
})

const providerAdvancedOpen = computed(() => {
  if (promotedForm.llmTimeoutSeconds.value !== DEFAULT_LLM_TIMEOUT_SECONDS) return true
  return providerAdvancedFields.value.some(f => {
    if (f.required) return true
    const val = providerForm.fieldValue(f, config.value.llm || {}).trim()
    const def = String(f.default || '').trim()
    if (def) return val !== def
    return val.length > 0
  })
})

const providerEnvMissing = computed(() => status.value.llmSource === 'missing_env')
const providerEnvKey = computed(() => (config.value.llm || {}).api_key_env || 'the selected API key environment variable')
const providerEnvCommand = computed(() => envRecoveryCommand('llm'))
const searchEnvCommand = computed(() => envRecoveryCommand('search'))
const memoryEnvCommand = computed(() => envRecoveryCommand('memory_embedding'))
const imageEnvCommand = computed(() => envRecoveryCommand('image_generation'))

const routerSummary = computed(() => {
  if (!hasSavedProvider.value) return 'choose a provider first'
  return routerForm.mode.value === 'disabled' ? 'disabled' : 'SquillaRouter'
})

const channelSpec = computed(() => catalogChannels.value.find(c => c.type === channelsForm.selectedChannelType.value) || null)
const channelSpecFields = computed(() => channelSpec.value?.fields || [])
const channelRuntimeRows = computed(() => (channelStatus.value.channels || []).filter(row => row.configured !== false))

const modelSummary = computed(() => {
  if (!hasSavedProvider.value) return 'not configured'
  return (config.value.llm || {}).model || 'SquillaRouter defaults'
})

const providerProxy = computed(() => {
  if (!hasSavedProvider.value) return ''
  return ((config.value.llm || {}).proxy || '').trim()
})

const configPath = computed(() => status.value.configPath || '')

const searchSpec = computed(() => searchProviders.value.find(p => p.providerId === capabilitiesForm.selectedSearchProvider.value) || searchProviders.value[0] || null)
const searchRequiresKey = computed(() => searchSpec.value?.requiresApiKey === true)
const searchEnvPlaceholder = computed(() => searchRequiresKey.value ? (searchSpec.value?.envKey || 'SEARCH_API_KEY') : 'not required for this provider')
const searchNeeds = computed(() => credentialNeedList(searchSpec.value?.whatYouNeed, capabilitiesForm.searchApiKeyEnvValue.value || searchSpec.value?.envKey))

const memorySpec = computed(() => memoryProviders.value.find(p => p.providerId === capabilitiesForm.selectedMemoryProvider.value) || memoryProviders.value[0] || null)
const memoryApiKeyEnabled = computed(() => capabilitiesForm.selectedMemoryProvider.value === 'auto' || memorySpec.value?.requiresApiKey === true)
const memoryApiKeyPlaceholder = computed(() => memoryApiKeyEnabled.value ? 'leave blank to keep current' : 'not required for this provider')
const memoryEnvPlaceholder = computed(() => memorySpec.value?.envKey || 'PROVIDER_API_KEY')
const memoryNeeds = computed(() => memoryNeedList(memorySpec.value, capabilitiesForm.selectedMemoryProvider.value, capabilitiesForm.memoryApiKeyEnvValue.value || memorySpec.value?.envKey))
const memoryStatusText = computed(() => _memoryEmbeddingStatusText(capabilitiesForm.selectedMemoryProvider.value))

const imageSpec = computed(() => imageProviders.value.find(p => p.providerId === capabilitiesForm.selectedImageProvider.value) || imageProviders.value[0] || null)
const imageNeeds = computed(() => {
  if (!capabilitiesForm.imageIsEnabled.value) return ['No key required while image generation is disabled.']
  return credentialNeedList(imageSpec.value?.whatYouNeed, capabilitiesForm.imageApiKeyEnvValue.value || imageSpec.value?.envKey)
})
const imageStatusText = computed(() => _imageGenerationStatusText())

const audioKeyReferenced = computed(() => promotedForm.audioKeyConfigured.value || Boolean(promotedForm.audioApiKeyEnv.value.trim()) || Boolean(promotedForm.audioApiKey.value.trim()))
const audioStatusText = computed(() => {
  if (!promotedForm.audioEnabled.value) return 'Voice and audio tools are hidden from agents until this capability is enabled.'
  if (audioKeyReferenced.value) return 'Voice and audio tools will be available in new turns once the gateway sees the key.'
  return 'Audio is enabled but still needs an audio provider key before agents can use it.'
})
const audioBadgeTone = computed(() => {
  if (!promotedForm.audioEnabled.value) return 'is-muted'
  return audioKeyReferenced.value ? 'is-ok' : 'is-warn'
})
const audioBadgeLabel = computed(() => {
  if (!promotedForm.audioEnabled.value) return 'Optional'
  return audioKeyReferenced.value ? 'Ready' : 'Needs action'
})
const audioKeyPlaceholder = computed(() => promotedForm.audioKeyConfigured.value ? 'leave blank to keep current' : 'paste an audio provider key')

const providerPanel = providerForm.createPanel({
  currentConfig: currentProviderConfig,
  providerSummary,
  runtimeProviders,
  routerSupportTone,
  routerSupportText,
  providerNeeds,
  providerCoreFields,
  providerAdvancedFields,
  providerAdvancedOpen,
  providerEnvMissing,
  providerEnvKey,
  providerEnvCommand,
  llmTimeoutSeconds: promotedForm.llmTimeoutSeconds,
})

const routerPanel = routerForm.createPanel({
  routerSummary,
  hasSavedProvider,
  textTiers: TEXT_TIERS,
  tierLabel,
})

const channelsPanel = channelsForm.createPanel({
  channelRuntimeRows,
  catalogChannels,
  channelSpec,
  channelSpecFields,
})

const capabilitiesPanel = capabilitiesForm.createPanel({
  searchProviders,
  memoryProviders,
  imageProviders,
  imageSpec,
  searchRequiresKey,
  searchEnvPlaceholder,
  searchAdvancedOpen: capabilitiesForm.searchAdvancedOpen,
  searchNeeds,
  searchEnvCommand,
  searchStatusText,
  memoryApiKeyEnabled,
  memoryRemoteOptionsOpen: capabilitiesForm.memoryRemoteOptionsOpen,
  memoryRemoteOptionsSummary: capabilitiesForm.memoryRemoteOptionsSummary,
  memoryModelPlaceholder: capabilitiesForm.memoryModelPlaceholder,
  memoryBasePlaceholder: capabilitiesForm.memoryBasePlaceholder,
  memoryOnnxPlaceholder: capabilitiesForm.memoryOnnxPlaceholder,
  memoryApiKeyLabel: capabilitiesForm.memoryApiKeyLabel,
  memoryApiKeyPlaceholder,
  memoryEnvPlaceholder,
  memoryNeeds,
  memoryStatusText,
  memoryEnvCommand,
  imageNeeds,
  imageStatusText,
  imageEnvCommand,
  capabilityBadgeTone,
  capabilityBadgeLabel,
  capabilitySaveButtonClass,
  memoryAutoCapture: promotedForm.memoryAutoCapture,
  audioEnabled: promotedForm.audioEnabled,
  audioApiKey: promotedForm.audioApiKey,
  audioApiKeyEnv: promotedForm.audioApiKeyEnv,
  audioStatusText,
  audioBadgeTone,
  audioBadgeLabel,
  audioKeyPlaceholder,
})

const hasSetupAction = computed(() => {
  if (status.value.needsOnboarding) return true
  const details = status.value.sectionDetails || {}
  return Object.values(details).some(detail => (
    detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'
  ))
})

// Banner items: one row per pending action, each deep-linking to its section.
const actionItems = computed<SettingsActionItem[]>(() => {
  if (!hasSetupAction.value) return []
  const items: SettingsActionItem[] = []
  const seen = new Set<string>()
  const push = (label: string, target: SettingsSectionId) => {
    if (seen.has(label)) return
    seen.add(label)
    items.push({ label, section: target })
  }
  const llm = config.value.llm || {}
  if (providerEnvMissing.value) {
    push(`${providerEnvKey.value} is not visible`, 'provider')
  } else if (!llm.provider || !llm.model) {
    push('Connect a model provider', 'provider')
  }
  const details = status.value.sectionDetails || {}
  Object.entries(details).forEach(([name, detail]) => {
    if (!detail.blocking && !detail.actionRequired) return
    if (name === 'llm' || name === 'provider') {
      push('Connect a model provider', 'provider')
      return
    }
    push(setupActionReason(name, detail), sectionForDetailName(name) || 'provider')
  })
  if (!items.length) push('Review setup sections for pending actions', 'provider')
  return items
})

const configCliArg = computed(() => {
  const path = status.value.configPath
  return path ? ` --config ${shellArg(path)}` : ''
})

const envRecoveryCommands = computed(() => {
  const cmds = Array.isArray(status.value.envRecoveryCommands) ? status.value.envRecoveryCommands : []
  return cmds
    .filter(entry => entry && entry.command)
    .map(entry => ({ label: entry.label || 'Set environment key', command: entry.command || '' }))
})

const fixCommands = computed(() => {
  if (!envRecoveryCommands.value.length) return []
  return [
    ...envRecoveryCommands.value,
    { label: 'Restart gateway after env fix', command: `opensquilla gateway restart${configCliArg.value}` },
  ]
})

const handoffCommands = computed(() => [
  { label: 'CLI onboarding', command: `opensquilla onboard --if-needed${configCliArg.value}` },
  { label: 'Check status', command: `opensquilla onboard status${configCliArg.value}` },
])

const recipeCommands = computed(() => [
  { label: 'Provider options', command: `opensquilla onboard catalog providers${configCliArg.value}` },
  { label: 'Router tiers', command: `opensquilla onboard catalog router${configCliArg.value}` },
  { label: 'Search options', command: `opensquilla onboard catalog search${configCliArg.value}` },
  { label: 'Channel options', command: `opensquilla onboard catalog channels${configCliArg.value}` },
  { label: 'Image options', command: `opensquilla onboard catalog image${configCliArg.value}` },
  { label: 'Memory options', command: `opensquilla onboard catalog memory${configCliArg.value}` },
])

const configSummary = computed(() => {
  const rows: Array<{ label: string; value: string }> = [
    { label: 'Provider', value: providerSummary.value },
    { label: 'Model', value: modelSummary.value },
  ]
  if (providerProxy.value) rows.push({ label: 'Proxy', value: providerProxy.value })
  rows.push({ label: 'Router', value: routerSummary.value })
  rows.push({ label: 'Channels', value: String(status.value.channelCount || 0) })
  return rows
})

// ---------------------------------------------------------------------------
// Section state
// ---------------------------------------------------------------------------

function isSectionId(value: string): value is SettingsSectionId {
  return SETTINGS_SECTIONS.some(s => s.id === value)
}

// target: explicit section id, 'auto' (first not-ready), or null (first section).
function selectInitialSection(target: string | null) {
  if (target && target !== 'auto' && isSectionId(target)) {
    setSection(target)
    return
  }
  setSection(target === 'auto' ? firstActionSection() : 'provider')
}

function firstActionSection(): SettingsSectionId {
  const details = status.value.sectionDetails || {}
  const sectionOrder: Array<[string, SettingsSectionId]> = [
    ['llm', 'provider'],
    ['router', 'router'],
    ['channels', 'channels'],
    ['search', 'capabilities'],
    ['image_generation', 'capabilities'],
    ['memory_embedding', 'capabilities'],
    ['audio', 'capabilities'],
  ]
  const entry = sectionOrder.find(([name]) => {
    const detail = details[name] || {}
    return stepDetailNeedsAction(detail)
  })
  if (entry) return entry[1]
  if (providerEnvMissing.value) return 'provider'
  return 'provider'
}

function sectionStatus(sectionId: string): { label: string; tone: string } {
  if (sectionId === 'connection') {
    if (rpc.isConnected) return { label: 'Connected', tone: 'is-ok' }
    if (rpc.isConnecting) return { label: 'Connecting', tone: 'is-muted' }
    return { label: 'Disconnected', tone: 'is-warn' }
  }
  if (sectionId === 'provider') {
    if (providerEnvMissing.value) return { label: 'Needs action', tone: 'is-warn' }
    return detailStepStatus((status.value.sectionDetails || {}).llm || (status.value.sectionDetails || {}).provider)
  }
  if (sectionId === 'router' && !hasSavedProvider.value) {
    return { label: 'Provider first', tone: 'is-muted' }
  }
  if (sectionId === 'router') return detailStepStatus((status.value.sectionDetails || {}).router)
  if (sectionId === 'channels') return detailStepStatus((status.value.sectionDetails || {}).channels)
  if (sectionId === 'capabilities') {
    return aggregateStepStatus(['search', 'image_generation', 'memory_embedding', 'audio'])
  }
  return { label: 'Review', tone: 'is-muted' }
}

function detailStepStatus(detail?: SectionDetail): { label: string; tone: string } {
  if (!detail) return { label: 'Review', tone: 'is-muted' }
  if (stepDetailNeedsAction(detail)) return { label: 'Needs action', tone: 'is-warn' }
  if (detail.status === 'ok') return { label: 'Ready', tone: 'is-ok' }
  return { label: READINESS_LABELS[detail.status || ''] || 'Optional', tone: 'is-muted' }
}

function aggregateStepStatus(sectionNames: string[]): { label: string; tone: string } {
  const details = status.value.sectionDetails || {}
  const entries = sectionNames.map(name => details[name]).filter(Boolean) as SectionDetail[]
  if (entries.some(detail => stepDetailNeedsAction(detail))) {
    return { label: 'Needs action', tone: 'is-warn' }
  }
  if (entries.length && entries.every(detail => detail.status === 'ok')) {
    return { label: 'Ready', tone: 'is-ok' }
  }
  return { label: 'Optional', tone: 'is-muted' }
}

function stepDetailNeedsAction(detail: SectionDetail): boolean {
  return Boolean(detail && (detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'))
}

function setupActionReason(name: string, detail: SectionDetail): string {
  const missingEnvPrefix = 'env key not visible: '
  const detailText = String(detail.detail || '')
  if (detailText.startsWith(missingEnvPrefix)) {
    const envKey = detailText.slice(missingEnvPrefix.length).trim()
    if (envKey) return `${envKey} is not visible`
  }
  return `${detail.label || name} setup needed`
}

function sectionForDetailName(name: string): SettingsSectionId | null {
  if (name === 'llm' || name === 'provider') return 'provider'
  if (name === 'router') return 'router'
  if (name === 'channels') return 'channels'
  if (name === 'search' || name === 'image_generation' || name === 'memory_embedding' || name === 'audio') return 'capabilities'
  return null
}

// ---------------------------------------------------------------------------
// Dirty state
// ---------------------------------------------------------------------------

const providerDirty = computed(() => providerForm.isDirty.value || promotedForm.timeoutDirty.value)
const routerDirty = computed(() => routerForm.isDirty.value)
const channelsDirty = computed(() => channelsForm.isDirty.value)
const capabilitiesDirty = computed(() => (
  capabilitiesForm.searchDirty.value
  || capabilitiesForm.memoryDirty.value
  || capabilitiesForm.imageDirty.value
  || promotedForm.captureDirty.value
  || promotedForm.audioDirty.value
))

function sectionDirty(sectionId: string): boolean {
  if (sectionId === 'provider') return providerDirty.value
  if (sectionId === 'router') return routerDirty.value
  if (sectionId === 'channels') return channelsDirty.value
  if (sectionId === 'capabilities') return capabilitiesDirty.value
  return false
}

const dirtySections = computed(() => SETTINGS_SECTIONS.filter(s => sectionDirty(s.id)))
const hasUnsavedChanges = computed(() => dirtySections.value.length > 0)

async function saveDirtySections() {
  if (providerDirty.value) await saveProvider()
  if (routerDirty.value) await saveRouter()
  if (channelsDirty.value) await saveChannel()
  if (capabilitiesForm.searchDirty.value) await saveSearch()
  if (capabilitiesForm.memoryDirty.value || promotedForm.captureDirty.value) await saveMemory()
  if (capabilitiesForm.imageDirty.value) await saveImage()
  if (promotedForm.audioDirty.value) await saveAudio()
}

async function discardChanges() {
  await loadData()
}

// ---------------------------------------------------------------------------
// Provider helpers
// ---------------------------------------------------------------------------

function isProviderAdvancedField(field: FieldSpec): boolean {
  if (['base_url', 'proxy'].includes(field.name)) return true
  if (field.name === 'model') {
    return providerSpec.value?.routerSupported === true && field.required !== true
  }
  return false
}

function selectProvider(value: string) {
  providerForm.selectProvider(value)
}

function onProviderChange() {
  providerForm.resetForProvider(providerSpec.value)
}

function updateProviderField(name: string, value: unknown) {
  providerForm.updateField(name, value)
}

function updateLlmTimeout(value: number) {
  promotedForm.setLlmTimeoutSeconds(value)
}

function envRecoveryCommand(section: string): string {
  const commands = Array.isArray(status.value.envRecoveryCommands) ? status.value.envRecoveryCommands : []
  const entry = commands.find(e => e && e.section === section && e.command)
  return entry ? (entry.command ?? '') : ''
}

// ---------------------------------------------------------------------------
// Channel helpers
// ---------------------------------------------------------------------------

function onChannelTypeChange() {
  channelsForm.resetForSpec(channelSpec.value)
}

function selectChannelType(value: string) {
  channelsForm.selectChannelType(value)
}

function updateChannelField(name: string, value: unknown) {
  channelsForm.updateField(name, value)
}

function setRouterMode(value: string) {
  routerForm.setRouterMode(value)
}

function setRouterDefaultTier(value: string) {
  routerForm.setRouterDefaultTier(value)
}

function setRouterVisualMode(value: string) {
  routerForm.setRouterVisualMode(value)
}

function updateTierField(
  name: string,
  key: 'provider' | 'model' | 'thinkingLevel' | 'supportsImage',
  value: string | boolean,
) {
  routerForm.updateTierField(name, key, value)
}

// ---------------------------------------------------------------------------
// Search / Memory / Image / Audio helpers
// ---------------------------------------------------------------------------

function onSearchProviderChange() {
  capabilitiesForm.onSearchProviderChange(searchSpec.value)
}

function onMemoryProviderChange() {
  capabilitiesForm.onMemoryProviderChange(memorySpec.value, memoryApiKeyEnabled.value)
}

function onImageProviderChange() {
  capabilitiesForm.onImageProviderChange(imageSpec.value)
}

function updateCapabilityField(
  group: 'search' | 'memory' | 'image' | 'audio',
  key: string,
  value: string | number | boolean,
) {
  if (group === 'audio') {
    promotedForm.updateAudioField(key, value as string | boolean)
    return
  }
  if (group === 'memory' && key === 'autoCapture') {
    promotedForm.setMemoryAutoCapture(Boolean(value))
    return
  }
  capabilitiesForm.updateField(group, key, value)
}

function credentialNeedList(items: string[] | undefined, envKey: string | undefined): string[] {
  const key = String(envKey || '').trim()
  if (!key) return items || []
  return (items || []).map(item => {
    if (/API key via [A-Z0-9_]+ or a one-time paste\./.test(item)) {
      return `API key via ${key} or a one-time paste.`
    }
    if (/Remote embedding API key or [A-Z0-9_]+ reference\./.test(item)) {
      return `Remote embedding API key or ${key} reference.`
    }
    return item
  })
}

function memoryNeedList(spec: ProviderSpec | null, providerId: string, envKey: string | undefined): string[] {
  const items = (spec?.whatYouNeed || []).filter(Boolean)
  if (providerId === 'auto' && !String(envKey || '').trim()) {
    return items.filter(item => !/remote fallback credentials/i.test(item))
  }
  return spec?.requiresApiKey ? credentialNeedList(items, envKey || spec.envKey) : items
}

// ---------------------------------------------------------------------------
// Status text helpers
// ---------------------------------------------------------------------------

function searchStatusText(): string {
  if (!config.value.search_provider) {
    return 'Web search is off until a provider is selected.'
  }
  if (status.value.searchConfigured === true) {
    return 'Web search is ready for new turns.'
  }
  if (status.value.searchSource === 'missing_env') {
    return _missingEnvStatusText('Web search', status.value.searchEnvKey, 'Web search is selected but still needs a visible provider key.')
  }
  return 'Web search is selected but still needs a visible provider key.'
}

function _imageGenerationStatusText(): string {
  if (status.value.imageGenerationEnabled === false) {
    return 'Image generation is hidden from agents until this capability is enabled.'
  }
  if (status.value.imageGenerationConfigured === true) {
    if (status.value.imageGenerationSource === 'llm_fallback') {
      return 'Image generation will be available in new turns using the same provider key.'
    }
    return 'Image generation will be available in new turns once the gateway has the visible key.'
  }
  if (status.value.imageGenerationSource === 'missing_env') {
    return _missingEnvStatusText('Image generation', status.value.imageGenerationEnvKey, 'Image generation is enabled but still needs a visible provider key before agents can use it.')
  }
  return 'Image generation is enabled but still needs a visible provider key before agents can use it.'
}

function _memoryEmbeddingStatusText(providerId = ''): string {
  const current = config.value.memory?.embedding || {}
  const savedProvider = current.provider || current.mode || status.value.memoryEmbeddingProvider || 'auto'
  const provider = providerId || savedProvider
  if (provider === 'none') {
    return 'Keyword search stays available; embeddings are disabled.'
  }
  if (provider === 'local') {
    return 'Uses local BGE embeddings; no remote key is needed.'
  }
  if (provider === 'ollama') {
    return 'Uses your Ollama server; no API key is needed.'
  }
  if (provider === 'auto') {
    return 'Local-first memory search; optional remote fallback can be configured.'
  }
  if (provider === savedProvider && status.value.memoryEmbeddingConfigured === true) {
    return 'Remote memory embeddings are configured for new turns.'
  }
  if (provider === savedProvider && status.value.memoryEmbeddingSource === 'missing_env') {
    return _missingEnvStatusText('Remote memory embeddings', status.value.memoryEmbeddingEnvKey, 'Remote memory embeddings need a visible provider key before they can run.')
  }
  return 'Remote memory embeddings need a visible provider key before they can run.'
}

function _missingEnvStatusText(capability: string, envKey: string | undefined, fallback: string): string {
  const key = String(envKey || '').trim()
  if (!key) return fallback
  return `${capability} is selected, but $${key} is not visible to the gateway.`
}

// ---------------------------------------------------------------------------
// Readiness helpers
// ---------------------------------------------------------------------------

function capabilityBadgeTone(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  if (detail.blocking || detail.actionRequired) return 'is-warn'
  if (detail.status === 'ok') return 'is-ok'
  return 'is-muted'
}

function capabilityBadgeLabel(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  if (detail.blocking || detail.actionRequired) return 'Needs action'
  return READINESS_LABELS[detail.status || ''] || 'Optional'
}

function capabilitySaveButtonClass(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return detail.blocking || detail.actionRequired
    ? 'btn btn--primary'
    : 'btn'
}

// ---------------------------------------------------------------------------
// Save actions
// ---------------------------------------------------------------------------

async function patchConfig(patches: Record<string, unknown>): Promise<boolean> {
  if (!Object.keys(patches).length) return false
  const res = await rpc.call<{ restartRequired?: boolean }>('config.patch', { patches })
  return res?.restartRequired === true
}

async function safePatchConfig(patches: Record<string, unknown>): Promise<boolean> {
  if (!Object.keys(patches).length) return false
  const res = await rpc.call<{ restartRequired?: boolean }>('config.patch.safe', { patches })
  return res?.restartRequired === true
}

async function saveProvider() {
  if (!providerForm.selectedProvider.value) {
    pushToast('Choose a provider before saving.', { tone: 'danger' })
    return
  }
  try {
    await rpc.call('onboarding.provider.configure', providerForm.payload())
    const restart = await patchConfig(promotedForm.providerPatches())
    await loadData()
    if (providerEnvMissing.value) {
      pushToast(`${providerEnvKey.value} is not visible to this gateway process.`, { tone: 'danger' })
      return
    }
    pushToast(restart ? 'Provider saved. Restart required.' : 'Provider saved.')
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveRouter() {
  if (!hasSavedProvider.value && routerForm.routingDirty.value) {
    pushToast('Choose a provider before saving router tiers.', { tone: 'danger' })
    return
  }
  try {
    if (routerForm.routingDirty.value) {
      await rpc.call('onboarding.router.configure', routerForm.payload())
    }
    const restart = await safePatchConfig(routerForm.visualModePatches())
    pushToast(restart ? 'Router saved. Restart required.' : 'Router saved.')
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveChannel() {
  const entry = channelsForm.payload()
  try {
    await rpc.call('onboarding.channel.probe', { entry })
    await rpc.call('onboarding.channel.upsert', { entry })
    pushToast('Channel saved. Restart required.')
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveSearch() {
  const params = capabilitiesForm.searchPayload()
  try {
    await rpc.call('onboarding.search.configure', params)
    pushToast('Search saved.')
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveMemory() {
  const embeddingDirty = capabilitiesForm.memoryDirty.value
  try {
    let envToastShown = false
    if (embeddingDirty) {
      const params = capabilitiesForm.memoryPayload()
      const res = await rpc.call<{ entry?: { remote?: { api_key_env?: string; api_key?: string } }; restartRequired?: boolean }>('onboarding.memory_embedding.configure', params)
      const remote = res?.entry?.remote || {}
      envToastShown = _toastEnvReferenceSave('Memory embedding', remote.api_key_env, '', remote.api_key ?? '', res?.restartRequired)
    }
    // The capture toggle rides config.patch and hot-applies; only embedding
    // changes need a gateway restart.
    await patchConfig(promotedForm.memoryPatches())
    if (!envToastShown) {
      pushToast(embeddingDirty ? 'Memory saved. Restart required for embedding changes.' : 'Memory saved.')
    }
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveImage() {
  const params = capabilitiesForm.imagePayload()
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.imageGeneration.configure', params)
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave('Image generation', entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      pushToast('Image generation saved.')
    }
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function saveAudio() {
  if (!promotedForm.audioDirty.value) {
    pushToast('No audio changes to save.')
    return
  }
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.audio.configure', promotedForm.audioPayload())
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave('Audio', entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      pushToast(res?.restartRequired ? 'Audio saved. Restart required.' : 'Audio saved.')
    }
    await loadData()
  } catch (err) {
    pushToast('Save failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

function _toastEnvReferenceSave(
  surface: string,
  envKey: string | undefined,
  keySource = '',
  hasInlineKey = '',
  restartRequired = false,
): boolean {
  const key = String(envKey || '').trim()
  if (!key || hasInlineKey) return false
  if (keySource === 'missing_env' || restartRequired) {
    pushToast(`${surface} saved $${key}. Start or restart the gateway with that variable set.`)
    return true
  }
  pushToast(`${surface} saved $${key} reference. Keep it set for gateway restarts.`)
  return true
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function tierLabel(tier: string): string {
  return routerTierLabel(tier)
}

function shellArg(value: string): string {
  const text = String(value || '')
  if (/^[A-Za-z0-9_@%+=:,./~-]+$/.test(text)) return text
  return `'${text.replace(/'/g, `'\''`)}'`
}

async function copyText(text: string, successMessage: string) {
  if (!text) return
  try {
    await copyTextWithFallback(text)
    pushToast(successMessage)
  } catch (err) {
    pushToast('Copy failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function copyCommand(command: string) {
  await copyText(command, 'Copied command')
}

async function copyConfigPath() {
  await copyText(configPath.value, 'Copied path')
}

  return {
    status,
    config,
    section,
    setSection,
    loaded,
    providerPanel,
    routerPanel,
    channelsPanel,
    capabilitiesPanel,
    loadData,
    hasSavedProvider,
    providerEnvMissing,
    providerEnvKey,
    hasSetupAction,
    actionItems,
    fixCommands,
    handoffCommands,
    recipeCommands,
    configSummary,
    configPath,
    selectInitialSection,
    sectionStatus,
    sectionDirty,
    dirtySections,
    hasUnsavedChanges,
    saveDirtySections,
    discardChanges,
    selectProvider,
    setRouterMode,
    setRouterDefaultTier,
    setRouterVisualMode,
    selectChannelType,
    updateProviderField,
    updateLlmTimeout,
    updateTierField,
    updateChannelField,
    updateCapabilityField,
    onProviderChange,
    onChannelTypeChange,
    onSearchProviderChange,
    onMemoryProviderChange,
    onImageProviderChange,
    saveProvider,
    saveRouter,
    saveChannel,
    saveSearch,
    saveMemory,
    saveImage,
    saveAudio,
    copyCommand,
    copyConfigPath,
  }
}
