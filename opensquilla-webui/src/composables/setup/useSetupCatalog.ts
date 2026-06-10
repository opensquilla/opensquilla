import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSetupChannelsForm } from '@/composables/setup/useSetupChannelsForm'
import { useSetupCapabilitiesForm } from '@/composables/setup/useSetupCapabilitiesForm'
import { useSetupProviderForm } from '@/composables/setup/useSetupProviderForm'
import { useSetupRouterForm } from '@/composables/setup/useSetupRouterForm'
import { useSetupStep } from '@/composables/setup/useSetupStep'
import { useRpcStore } from '@/stores/rpc'
import { copyTextWithFallback } from '@/utils/browser'
import { TEXT_TIERS, routerTierLabel } from '@/utils/chat/routerTiers'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = [
  { id: 'provider', label: 'Provider' },
  { id: 'router', label: 'Router Tiers' },
  { id: 'channels', label: 'Channels' },
  { id: 'extras', label: 'Capabilities' },
  { id: 'finish', label: 'Finish' },
] as const

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
  squilla_router?: {
    enabled?: boolean
    default_tier?: string
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
}

export function useSetupCatalog() {
// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const router = useRouter()

const catalog = ref<OnboardingCatalog>({})
const status = ref<OnboardingStatus>({})
const config = ref<ConfigData>({})
const channelStatus = ref<{ channels: ChannelStatusRow[] }>({ channels: [] })
const {
  step,
  hasAutoSelectedStep,
  setStep,
  markAutoSelected,
} = useSetupStep('provider')

const providerForm = useSetupProviderForm()
const routerForm = useSetupRouterForm()
const channelsForm = useSetupChannelsForm()
const capabilitiesForm = useSetupCapabilitiesForm()

let pollTimer: ReturnType<typeof setInterval> | null = null

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(async () => {
  await loadData()
  selectInitialStep()
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
  } catch (err) {
    console.warn('Failed to load setup catalog: ' + (err instanceof Error ? err.message : String(err)))
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
    if (step.value !== 'channels') return
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

const searchSpec = computed(() => searchProviders.value.find(p => p.providerId === capabilitiesForm.selectedSearchProvider.value) || searchProviders.value[0] || null)
const searchRequiresKey = computed(() => searchSpec.value?.requiresApiKey === true)
const searchEnvPlaceholder = computed(() => searchRequiresKey.value ? (searchSpec.value?.envKey || 'SEARCH_API_KEY') : 'not required for this provider')
const searchNeeds = computed(() => credentialNeedList(searchSpec.value?.whatYouNeed, capabilitiesForm.searchApiKeyEnvValue.value || searchSpec.value?.envKey))

const memorySpec = computed(() => memoryProviders.value.find(p => p.providerId === capabilitiesForm.selectedMemoryProvider.value) || memoryProviders.value[0] || null)
const memoryApiKeyEnabled = computed(() => capabilitiesForm.selectedMemoryProvider.value === 'auto' || memorySpec.value?.requiresApiKey === true)
const memoryApiKeyPlaceholder = computed(() => memoryApiKeyEnabled.value ? 'leave blank to keep current' : 'not required for this provider')
const memoryEnvPlaceholder = computed(() => memorySpec.value?.envKey || 'OPENAI_API_KEY')
const memoryNeeds = computed(() => memoryNeedList(memorySpec.value, capabilitiesForm.selectedMemoryProvider.value, capabilitiesForm.memoryApiKeyEnvValue.value || memorySpec.value?.envKey))
const memoryStatusText = computed(() => _memoryEmbeddingStatusText(capabilitiesForm.selectedMemoryProvider.value))

const imageSpec = computed(() => imageProviders.value.find(p => p.providerId === capabilitiesForm.selectedImageProvider.value) || imageProviders.value[0] || null)
const imageNeeds = computed(() => {
  if (!capabilitiesForm.imageIsEnabled.value) return ['No key required while image generation is disabled.']
  return credentialNeedList(imageSpec.value?.whatYouNeed, capabilitiesForm.imageApiKeyEnvValue.value || imageSpec.value?.envKey)
})
const imageStatusText = computed(() => _imageGenerationStatusText())

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
})

const hasSetupAction = computed(() => {
  if (status.value.needsOnboarding) return true
  const details = status.value.sectionDetails || {}
  return Object.values(details).some(detail => (
    detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'
  ))
})

const onboardingReasons = computed(() => {
  if (!hasSetupAction.value) return []
  const reasons: string[] = []
  const llm = config.value.llm || {}
  if (providerEnvMissing.value) {
    reasons.push(`${providerEnvKey.value} is not visible`)
  } else if (!llm.provider || !llm.model) {
    reasons.push('Connect a model provider')
  }
  const details = status.value.sectionDetails || {}
  Object.entries(details).forEach(([name, detail]) => {
    if (!detail.blocking && !detail.actionRequired) return
    if ((name === 'llm' || name === 'provider') && detail.status === 'missing') {
      if (!reasons.includes('Connect a model provider')) reasons.push('Connect a model provider')
      return
    }
    if ((name === 'llm' || name === 'provider') && reasons.length) return
    const reason = setupActionReason(name, detail)
    if (!reasons.includes(reason)) reasons.push(reason)
  })
  return reasons.length ? reasons : ['Review setup sections for pending actions']
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
  { label: 'Guided CLI', command: `opensquilla onboard --if-needed${configCliArg.value}` },
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

const readinessEntries = computed(() => Object.entries(status.value.sectionDetails || {}))
const requiredReadiness = computed(() => readinessEntries.value.filter(([, d]) => d.required))
const optionalReadiness = computed(() => readinessEntries.value.filter(([, d]) => !d.required))

// ---------------------------------------------------------------------------
// Step logic
// ---------------------------------------------------------------------------

function selectInitialStep() {
  if (hasAutoSelectedStep.value) return
  step.value = initialStepFromStatus()
  markAutoSelected()
}

function initialStepFromStatus(): string {
  const details = status.value.sectionDetails || {}
  const sectionSteps: [string, string][] = [
    ['llm', 'provider'],
    ['router', 'router'],
    ['channels', 'channels'],
    ['search', 'extras'],
    ['image_generation', 'extras'],
    ['memory_embedding', 'extras'],
  ]
  const entry = sectionSteps.find(([section]) => {
    const detail = details[section] || {}
    return detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'
  })
  if (entry) return entry[1]
  if (status.value.needsOnboarding === false) return 'finish'
  return 'provider'
}

function stepStatus(stepId: string): { label: string; tone: string } {
  const currentProvider = (config.value.llm || {}).provider || ''
  const hasSavedProvider = Boolean(currentProvider) && status.value.hasConfig !== false
  if (stepId === 'provider') {
    if (providerEnvMissing.value) return { label: 'Needs action', tone: 'is-warn' }
    return detailStepStatus((status.value.sectionDetails || {}).llm || (status.value.sectionDetails || {}).provider)
  }
  if (stepId === 'router' && !hasSavedProvider) {
    return { label: 'Provider first', tone: 'is-muted' }
  }
  if (stepId === 'router') return detailStepStatus((status.value.sectionDetails || {}).router)
  if (stepId === 'channels') return detailStepStatus((status.value.sectionDetails || {}).channels)
  if (stepId === 'extras') {
    return aggregateStepStatus(['search', 'image_generation', 'memory_embedding'])
  }
  if (stepId === 'finish') {
    return hasSetupAction.value
      ? { label: 'Review', tone: 'is-warn' }
      : { label: 'Ready', tone: 'is-ok' }
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

function updateTierField(
  name: string,
  key: 'provider' | 'model' | 'thinkingLevel' | 'supportsImage',
  value: string | boolean,
) {
  routerForm.updateTierField(name, key, value)
}

// ---------------------------------------------------------------------------
// Search / Memory / Image helpers
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
  group: 'search' | 'memory' | 'image',
  key: string,
  value: string | number | boolean,
) {
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
  return _readinessTone(detail, name)
}

function capabilityBadgeLabel(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return _readinessStatusLabel(detail, name)
}

function capabilitySaveButtonClass(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return detail.blocking || detail.actionRequired
    ? 'setup-btn setup-btn--primary'
    : 'setup-btn'
}

function _readinessTone(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'is-warn'
  if (detail.blocking || detail.actionRequired) return 'is-warn'
  if (detail.status === 'ok') return 'is-ok'
  return 'is-muted'
}

function _readinessStatusLabel(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'Provider first'
  if (detail.blocking || detail.actionRequired) return 'Needs action'
  return READINESS_LABELS[detail.status || ''] || 'Optional'
}

function _routerNeedsProvider(detail: SectionDetail, name: string): boolean {
  return name === 'router' && detail.status === 'ok' && detail.detail === 'uses SquillaRouter after provider setup'
}

function readinessTone(detail: SectionDetail, name: string): string {
  return _readinessTone(detail, name)
}

function readinessStatusLabel(detail: SectionDetail, name: string): string {
  return _readinessStatusLabel(detail, name)
}

function readinessActionLabel(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'Choose provider'
  if (detail.blocking || detail.actionRequired) return 'Fix'
  if (detail.status === 'ok') return 'Review'
  return 'Configure'
}

function readinessActionAriaLabel(detail: SectionDetail, name: string): string {
  const label = detail.label || name.replace(/_/g, ' ')
  if (_routerNeedsProvider(detail, name)) return `Choose provider for ${label}`
  return `${readinessActionLabel(detail, name)} ${label}`
}

function setupStepForSection(name: string, detail: SectionDetail = {}): string | null {
  if (_routerNeedsProvider(detail, name)) return 'provider'
  if (name === 'llm' || name === 'provider') return 'provider'
  if (name === 'router') return 'router'
  if (name === 'channels') return 'channels'
  if (name === 'search' || name === 'image_generation' || name === 'memory_embedding') return 'extras'
  return null
}

// ---------------------------------------------------------------------------
// Save actions
// ---------------------------------------------------------------------------

async function saveProvider() {
  if (!providerForm.selectedProvider.value) {
    console.warn('Choose a provider before saving.')
    return
  }
  try {
    await rpc.call('onboarding.provider.configure', providerForm.payload())
    await loadData()
    if (providerEnvMissing.value) {
      console.warn(`${providerEnvKey.value} is not visible to this gateway process.`)
      step.value = 'provider'
      return
    }
    console.warn('Provider saved.')
    step.value = 'router'
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveRouter() {
  if (!hasSavedProvider.value) {
    console.warn('Choose a provider before saving router tiers.')
    return
  }
  try {
    await rpc.call('onboarding.router.configure', routerForm.payload())
    console.warn('Router saved.')
    await loadData()
    step.value = 'channels'
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveChannel() {
  const entry = channelsForm.payload()
  try {
    await rpc.call('onboarding.channel.probe', { entry })
    await rpc.call('onboarding.channel.upsert', { entry })
    console.warn('Channel saved. Restart required.')
    await loadChannelStatus()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveSearch() {
  const params = capabilitiesForm.searchPayload()
  try {
    await rpc.call('onboarding.search.configure', params)
    console.warn('Search saved.')
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveMemory() {
  const params = capabilitiesForm.memoryPayload()
  try {
    const res = await rpc.call<{ entry?: { remote?: { api_key_env?: string; api_key?: string } }; restartRequired?: boolean }>('onboarding.memory_embedding.configure', params)
    const remote = res?.entry?.remote || {}
    if (!_toastEnvReferenceSave('Memory embedding', remote.api_key_env, '', remote.api_key ?? '', res?.restartRequired)) {
      console.warn('Memory embedding saved. Restart required.')
    }
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveImage() {
  const params = capabilitiesForm.imagePayload()
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.imageGeneration.configure', params)
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave('Image generation', entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      console.warn('Image generation saved.')
    }
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
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
    console.warn(`${surface} saved $${key}. Start or restart the gateway with that variable set.`)
    return true
  }
  console.warn(`${surface} saved $${key} reference. Keep it set for gateway restarts.`)
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

async function copyCommand(command: string) {
  if (!command) return
  try {
    await copyTextWithFallback(command)
    console.warn('Copied command')
  } catch (err) {
    console.warn('Copy failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

  return {
    router,
    STEPS,
    catalog,
    status,
    config,
    channelStatus,
    step,
    hasAutoSelectedStep,
    providerPanel,
    routerPanel,
    channelsPanel,
    capabilitiesPanel,
    loadData,
    loadChannelStatus,
    currentProvider,
    hasSavedProvider,
    routerProfiles,
    providerSpec,
    providerFields,
    providerSummary,
    providerEnvMissing,
    providerEnvKey,
    providerEnvCommand,
    searchEnvCommand,
    memoryEnvCommand,
    imageEnvCommand,
    routerSummary,
    modelSummary,
    providerProxy,
    hasSetupAction,
    onboardingReasons,
    configCliArg,
    envRecoveryCommands,
    fixCommands,
    handoffCommands,
    recipeCommands,
    readinessEntries,
    requiredReadiness,
    optionalReadiness,
    selectInitialStep,
    initialStepFromStatus,
    setStep,
    stepStatus,
    detailStepStatus,
    aggregateStepStatus,
    stepDetailNeedsAction,
    setupActionReason,
    isProviderAdvancedField,
    selectProvider,
    setRouterMode,
    setRouterDefaultTier,
    selectChannelType,
    updateProviderField,
    updateTierField,
    updateChannelField,
    updateCapabilityField,
    onProviderChange,
    envRecoveryCommand,
    onChannelTypeChange,
    onSearchProviderChange,
    onMemoryProviderChange,
    onImageProviderChange,
    credentialNeedList,
    memoryNeedList,
    searchStatusText,
    capabilityBadgeTone,
    capabilityBadgeLabel,
    capabilitySaveButtonClass,
    readinessTone,
    readinessStatusLabel,
    readinessActionLabel,
    readinessActionAriaLabel,
    setupStepForSection,
    saveProvider,
    saveRouter,
    saveChannel,
    saveSearch,
    saveMemory,
    saveImage,
    tierLabel,
    shellArg,
    copyCommand,
  }
}
