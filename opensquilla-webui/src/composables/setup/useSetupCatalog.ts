import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import i18n from '@/i18n'
import { useSetupChannelsForm } from '@/composables/setup/useSetupChannelsForm'
import { useSetupCapabilitiesForm } from '@/composables/setup/useSetupCapabilitiesForm'
import { useSetupBehaviorForm } from '@/composables/setup/useSetupBehaviorForm'
import {
  hasEffectiveProvider,
  normalizeDiscoveredModels,
  useSetupProviderForm,
  type DiscoveredModelsByProvider,
} from '@/composables/setup/useSetupProviderForm'
import { useSetupRouterForm, type SetupTierRow } from '@/composables/setup/useSetupRouterForm'
import {
  STATIC_B5_PROFILES,
  staticB5ModeForProvider,
  useSetupEnsembleForm,
  type EnsembleCandidateConfig,
  type EnsembleCandidateRole,
  type EnsembleCandidateView,
  type EnsembleCredentialStatus,
} from '@/composables/setup/useSetupEnsembleForm'
import { useSetupModelStrategyForm } from '@/composables/setup/useSetupModelStrategyForm'
import { invalidateReadiness } from '@/composables/setup/useReadinessSummary'
import { useSettingsPromotedForm, DEFAULT_LLM_TIMEOUT_SECONDS } from '@/composables/setup/useSettingsPromotedForm'
import { useSettingsSection } from '@/composables/setup/useSettingsSection'
import { SETTINGS_SECTIONS, type SettingsSectionId } from '@/composables/setup/settingsSections'
import { useRpcStore } from '@/stores/rpc'
import { useToasts } from '@/composables/useToasts'
import { useConfirm } from '@/composables/useConfirm'
import { saveFailedMessage } from '@/lib/rpcErrors'
import { copyTextWithFallback } from '@/utils/browser'
import { TEXT_TIERS, IMAGE_TIER, normalizeRouterTier, routerTierLabelKey } from '@/utils/chat/routerTiers'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export { SETTINGS_SECTIONS } from '@/composables/setup/settingsSections'
export type { SettingsSectionId } from '@/composables/setup/settingsSections'

const READINESS_KEYS: Record<string, string> = {
  ok: 'setup.readiness.ready',
  optional: 'setup.readiness.optional',
  missing: 'setup.readiness.missing',
  degraded: 'setup.readiness.needsAction',
  unknown: 'setup.readiness.check',
}

function readinessLabel(status: string): string {
  const key = READINESS_KEYS[status]
  return key ? i18n.global.t(key) : ''
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderPresetSpec {
  presetId: string
  label: string
  description?: string
  synthesized?: boolean
  defaultModel?: string
  tiers?: Record<string, TierConfig>
}

interface ProviderSpec {
  providerId: string
  label: string
  runtimeSupported?: boolean
  routerSupported?: boolean
  fields?: FieldSpec[]
  whatYouNeed?: string[]
  envKey?: string
  acceptsApiKey?: boolean
  requiresApiKey?: boolean
  defaultBaseUrl?: string
  defaultModel?: string
  deployment?: string
  presets?: ProviderPresetSpec[]
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
  enabled?: boolean
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
  // Server-computed router mode (router section card only):
  // recommended | openrouter-mix | custom | disabled.
  routerMode?: string
}

interface OnboardingStatus {
  needsOnboarding?: boolean
  hasConfig?: boolean
  llmConfigured?: boolean
  llmSource?: string
  sectionDetails?: Record<string, SectionDetail>
  // Read-only legacy-home detection (absent on older gateways).
  legacyData?: { path?: string; kind?: string; command?: string } | null
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
  llmCredentialStatus?: {
    provider?: string
    available?: boolean
    source?: string
    envKey?: string
    masked?: string
    revealAllowed?: boolean
  }
  ensembleCredentialStatus?: EnsembleCredentialStatus[]
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
  // Per-provider/per-model overrides (deep-merge subtree; model ids carry
  // dots/colons so dot-path patches cannot address it).
  models?: Record<string, Record<string, { context_window?: number }>>
  squilla_router?: {
    enabled?: boolean
    default_tier?: string
    visual_mode?: string
    tiers?: Record<string, TierConfig>
  }
  llm_ensemble?: {
    enabled?: boolean
    selection_mode?: string
    model_options?: string[]
    candidates?: EnsembleCandidateConfig[]
    min_successful_proposers?: number
    all_failed_policy?: string
  }
  naming?: {
    enabled?: boolean
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
  privacy?: {
    disable_network_observability?: boolean
    network_observability_disabled_effective?: boolean
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
const { confirm } = useConfirm()
const t = i18n.global.t

const catalog = ref<OnboardingCatalog>({})
const status = ref<OnboardingStatus>({})
const config = ref<ConfigData>({})
const channelStatus = ref<{ channels: ChannelStatusRow[] }>({ channels: [] })
const loaded = ref(false)
const { section, setSection } = useSettingsSection('provider')
const disableNetworkObservability = ref(false)

const providerForm = useSetupProviderForm()
const behaviorForm = useSetupBehaviorForm()
const routerForm = useSetupRouterForm()
const ensembleForm = useSetupEnsembleForm()
const channelsForm = useSetupChannelsForm()
const capabilitiesForm = useSetupCapabilitiesForm()
const promotedForm = useSettingsPromotedForm()

let pollTimer: ReturnType<typeof setInterval> | null = null
const tierModelCatalogs = ref<DiscoveredModelsByProvider>({})
const tierModelDiscoveries = new Map<string, Promise<void>>()
const tierModelDiscoveryCompleted = new Set<string>()
let tierModelDiscoveryEpoch = 0

function normalizeProviderId(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function resetTierModelDiscovery() {
  tierModelDiscoveryEpoch += 1
  tierModelCatalogs.value = {}
  tierModelDiscoveries.clear()
  tierModelDiscoveryCompleted.clear()
}

function discoverTierProviderModels(providerId: string): Promise<void> {
  const provider = normalizeProviderId(providerId)
  if (!provider) return Promise.resolve()

  const selectedProvider = normalizeProviderId(providerForm.selectedProvider.value)
  if (provider === selectedProvider) {
    // Keep using the provider form's discovery path for the selected provider:
    // it is the only path allowed to include unsaved credentials/endpoints.
    if (providerForm.connection.value.models.length > 0) return Promise.resolve()
    return providerForm.discoverModels()
  }

  const existing = tierModelDiscoveries.get(provider)
  if (existing) return existing
  if (tierModelDiscoveryCompleted.has(provider)) return Promise.resolve()

  const epoch = tierModelDiscoveryEpoch
  tierModelDiscoveryCompleted.add(provider)
  const request = (async () => {
    try {
      // Deliberately provider-only. Never forward the selected provider's
      // unsaved apiKey/baseUrl/proxy into another provider's request.
      const res = await rpc.call<{
        ok?: boolean
        source?: string
        models?: unknown
      }>('onboarding.models.discover', { providerId: provider })
      if (epoch !== tierModelDiscoveryEpoch) return
      const source = res?.ok && res.source === 'live' ? 'live' : 'none'
      tierModelCatalogs.value = {
        ...tierModelCatalogs.value,
        [provider]: source === 'live'
          ? {
              models: normalizeDiscoveredModels(res.models),
              source,
            }
          : { models: [], source: 'none' },
      }
    } catch {
      if (epoch !== tierModelDiscoveryEpoch) return
      tierModelCatalogs.value = {
        ...tierModelCatalogs.value,
        [provider]: { models: [], source: 'none' },
      }
    }
  })()
  const tracked = request.finally(() => {
    if (tierModelDiscoveries.get(provider) === tracked) {
      tierModelDiscoveries.delete(provider)
    }
  })
  tierModelDiscoveries.set(provider, tracked)
  return tracked
}

async function maybeDiscoverModelsForStrategy(): Promise<void> {
  if (section.value !== 'modelStrategy') return
  const providers = new Set(
    routerPanel.value.tierRows
      .map(row => normalizeProviderId(row.provider))
      .filter(Boolean),
  )
  const selectedProvider = normalizeProviderId(providerForm.selectedProvider.value)
  if (selectedProvider) providers.add(selectedProvider)
  await Promise.all(Array.from(providers, provider => discoverTierProviderModels(provider)))
}

watch(section, () => {
  void maybeDiscoverModelsForStrategy()
})

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
    resetTierModelDiscovery()

    // Initialize form values from config
    providerForm.initFromConfig(config.value.llm || {}, status.value, runtimeProviders.value)
    behaviorForm.initFromConfig(config.value)
    routerForm.initFromConfig(config.value.squilla_router || {}, currentRouterProfile.value?.tiers || {}, currentProvider.value)
    ensembleForm.initFromConfig(config.value.llm_ensemble || {})
    reconcileEnsembleProviderCompatibility()
    capabilitiesForm.initSearchFromConfig(config.value, searchProviders.value)
    capabilitiesForm.initMemoryFromConfig(config.value)
    capabilitiesForm.initImageFromConfig(config.value, status.value, imageProviders.value)
    channelsForm.initFromCatalog(catalog.value.channels || [])
    promotedForm.initFromConfig(config.value)
    disableNetworkObservability.value = currentDisableNetworkObservability.value
    // Model listing is an optional UI accelerator and may involve an external
    // provider. Start it after core state is ready, but never hold settings
    // loading/saving open while that network request runs.
    void maybeDiscoverModelsForStrategy()
    // Every save funnels through this reload, so this is the one spot that can
    // tell snapshot holders outside the dialog (the sidebar banner) that the
    // hot-applied config may have changed readiness.
    invalidateReadiness()
  } catch (err) {
    pushToast(t('setup.toast.loadFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
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
const currentModel = computed(() => (config.value.llm || {}).model || '')
const hasSavedProvider = computed(() => hasEffectiveProvider(currentProviderConfig.value, status.value))
// Lazy: routerPanel is declared below; this computed is only evaluated from
// user-triggered strategy switches, long after setup completes.
const modelStrategyTierCandidates = computed(() => ensembleTierCandidates.value)
const modelStrategyForm = useSetupModelStrategyForm(
  routerForm,
  ensembleForm,
  currentProvider,
  modelStrategyTierCandidates,
)

const runtimeProviders = computed(() => (catalog.value.providers || []).filter(p => p.runtimeSupported))
const catalogChannels = computed(() => catalog.value.channels || [])
const searchProviders = computed(() => (catalog.value.searchProviders || []).filter(p => p.runtimeSupported))
const imageProviders = computed(() => (catalog.value.imageGenerationProviders || []).filter(p => p.runtimeSupported))
const memoryProviders = computed(() => catalog.value.memoryEmbeddingProviders || [])
const routerProfiles = computed(() => catalog.value.routerProfiles?.profiles || [])
const currentRouterProfile = computed(() => routerProfiles.value.find(p => p.providerId === currentProvider.value))
const providerSpec = computed(() => runtimeProviders.value.find(p => p.providerId === providerForm.selectedProvider.value) || null)
const providerFields = computed(() => providerSpec.value?.fields || [])
const providerCoreFields = computed(() => providerFields.value.filter(f => !isProviderCredentialField(f) && !isProviderAdvancedField(f)))
const providerAdvancedFields = computed(() => providerFields.value.filter(f => !isProviderCredentialField(f) && isProviderAdvancedField(f)))

// Providers that run on the user's own hardware, where the runtime frequently
// defaults to a much smaller context window than the model supports. Mirrors the
// backend LOCAL_RUNTIME_PROVIDERS in provider/registry.py — keep in sync.
const LOCAL_PROVIDER_IDS = new Set(['ollama', 'vllm', 'lm_studio', 'ovms', 'local', 'custom'])
const providerIsLocal = computed(() => {
  const spec = providerSpec.value
  if (!spec) return false
  // Union, not either/or: the backend budgets 'custom' (deployment='custom') at
  // the local 8192 default too, so a deployment tag that isn't 'local' must not
  // suppress the known-local-id match.
  const deployment = String(spec.deployment || '').trim().toLowerCase()
  return deployment === 'local' || LOCAL_PROVIDER_IDS.has(spec.providerId)
})

// The global llm.context_window_tokens layer sits between the per-model override
// and catalog auto-detection in the backend's precedence. Surface it so the
// panel readout reflects it when no per-model override is set.
const contextWindowGlobal = computed<number | null>(() => {
  const raw = Number((config.value.llm || {}).context_window_tokens)
  return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : null
})

const providerSummary = computed(() => {
  if (!hasSavedProvider.value) return t('setup.summary.notConfigured')
  const spec = runtimeProviders.value.find(p => p.providerId === currentProvider.value)
  return spec?.label || currentProvider.value
})

const routerSupportText = computed(() => {
  if (!providerSpec.value) return t('setup.provider.chooseProviderShort')
  return providerSpec.value.routerSupported === true ? t('setup.provider.routerReady') : t('setup.provider.directOnly')
})

const routerSupportTone = computed(() => {
  if (!providerSpec.value) return 'is-neutral'
  return providerSpec.value.routerSupported === true ? 'is-ready' : 'is-direct'
})

// The "Configure the router →" affordance must only appear when jumping to the
// Router section shows a consistent, ready view. routerSupportTone tracks the
// *selected* provider (so the pill updates live as you browse providers), but the
// Router panel reflects the *saved* config — so gating the link on the tone alone
// could land on the previously-saved provider's tiers or the "provider first"
// empty state. Require a router-capable provider to actually be saved AND the
// selection to be clean, so selected == saved and the Router view is not stale.
const canConfigureRouter = computed(() =>
  hasSavedProvider.value
  && !providerForm.isDirty.value
  && routerSupportTone.value === 'is-ready',
)

const providerNeeds = computed(() => {
  if (!providerSpec.value) return [t('setup.provider.chooseToSeeFields')]
  return providerSpec.value.whatYouNeed || []
})

const providerAdvancedOpen = computed(() => {
  if (promotedForm.llmTimeoutSeconds.value !== DEFAULT_LLM_TIMEOUT_SECONDS) return true
  if (promotedForm.contextWindowTokens.value.trim() !== '') return true
  return providerAdvancedFields.value.some(f => {
    if (f.required) return true
    const val = providerForm.fieldValue(f, config.value.llm || {}).trim()
    const def = String(f.default || '').trim()
    if (def) return val !== def
    return val.length > 0
  })
})

const providerEnvMissing = computed(() => status.value.llmSource === 'missing_env')
const providerEnvKey = computed(() => (config.value.llm || {}).api_key_env || t('setup.provider.envKeyFallback'))
const providerEnvCommand = computed(() => envRecoveryCommand('llm'))
const searchEnvCommand = computed(() => envRecoveryCommand('search'))
const memoryEnvCommand = computed(() => envRecoveryCommand('memory_embedding'))
const imageEnvCommand = computed(() => envRecoveryCommand('image_generation'))

const routerSummary = computed(() => {
  if (!hasSavedProvider.value) return t('setup.router.chooseProviderFirst')
  if (ensembleProfileActive.value) return t('setup.router.summaryEnsemble')
  if (routerForm.mode.value === 'disabled') return t('setup.router.summaryDisabled')
  if (routerForm.mode.value === 'openrouter-mix') return t('setup.preset.modeCustom')
  return t('setup.router.modeRecommended')
})
const ensembleProfileActive = computed(() => config.value.llm_ensemble?.enabled === true)

const behaviorStatusText = computed(() => {
  return behaviorForm.autoSessionTitles.value
    ? t('setup.behavior.statusOn')
    : t('setup.behavior.statusOff')
})
const currentDisableNetworkObservability = computed(() => config.value.privacy?.disable_network_observability === true)
const currentEffectiveNetworkObservabilityDisabled = computed(() => (
  config.value.privacy?.network_observability_disabled_effective === true
))
const networkObservabilityDisabledByEnvironment = computed(() => (
  currentEffectiveNetworkObservabilityDisabled.value && !currentDisableNetworkObservability.value
))
const privacyDirty = computed(() => disableNetworkObservability.value !== currentDisableNetworkObservability.value)
const privacyStatusText = computed(() => {
  if (networkObservabilityDisabledByEnvironment.value && !disableNetworkObservability.value) {
    return t('setup.privacy.statusDisabledByEnv')
  }
  return disableNetworkObservability.value
    ? t('setup.privacy.statusDisabled')
    : t('setup.privacy.statusEnabled')
})

const channelSpec = computed(() => catalogChannels.value.find(c => c.type === channelsForm.selectedChannelType.value) || null)
const channelSpecFields = computed(() => channelSpec.value?.fields || [])
const channelRuntimeRows = computed(() => (channelStatus.value.channels || []).filter(row => row.configured !== false))

const modelSummary = computed(() => {
  if (!hasSavedProvider.value) return t('setup.summary.notConfigured')
  return (config.value.llm || {}).model || t('setup.summary.routerDefaults')
})

const providerProxy = computed(() => {
  if (!hasSavedProvider.value) return ''
  return ((config.value.llm || {}).proxy || '').trim()
})

const configPath = computed(() => status.value.configPath || '')

const searchSpec = computed(() => searchProviders.value.find(p => p.providerId === capabilitiesForm.selectedSearchProvider.value) || searchProviders.value[0] || null)
const searchRequiresKey = computed(() => searchSpec.value?.requiresApiKey === true)
const searchEnvPlaceholder = computed(() => searchRequiresKey.value ? (searchSpec.value?.envKey || 'SEARCH_API_KEY') : t('setup.common.notRequiredForProvider'))
const searchNeeds = computed(() => credentialNeedList(searchSpec.value?.whatYouNeed, capabilitiesForm.searchApiKeyEnvValue.value || searchSpec.value?.envKey))

const memorySpec = computed(() => memoryProviders.value.find(p => p.providerId === capabilitiesForm.selectedMemoryProvider.value) || memoryProviders.value[0] || null)
const memoryApiKeyEnabled = computed(() => capabilitiesForm.selectedMemoryProvider.value === 'auto' || memorySpec.value?.requiresApiKey === true)
const memoryApiKeyPlaceholder = computed(() => memoryApiKeyEnabled.value ? t('setup.common.leaveBlankKeep') : t('setup.common.notRequiredForProvider'))
const memoryEnvPlaceholder = computed(() => memorySpec.value?.envKey || 'PROVIDER_API_KEY')
const memoryNeeds = computed(() => memoryNeedList(memorySpec.value, capabilitiesForm.selectedMemoryProvider.value, capabilitiesForm.memoryApiKeyEnvValue.value || memorySpec.value?.envKey))
const memoryStatusText = computed(() => _memoryEmbeddingStatusText(capabilitiesForm.selectedMemoryProvider.value))

const imageSpec = computed(() => imageProviders.value.find(p => p.providerId === capabilitiesForm.selectedImageProvider.value) || imageProviders.value[0] || null)
const imageNeeds = computed(() => {
  if (!capabilitiesForm.imageIsEnabled.value) return [t('setup.image.noKeyWhileDisabled')]
  return credentialNeedList(imageSpec.value?.whatYouNeed, capabilitiesForm.imageApiKeyEnvValue.value || imageSpec.value?.envKey)
})
const imageStatusText = computed(() => _imageGenerationStatusText())

const audioKeyReferenced = computed(() => promotedForm.audioKeyConfigured.value || Boolean(promotedForm.audioApiKeyEnv.value.trim()) || Boolean(promotedForm.audioApiKey.value.trim()))
const audioStatusText = computed(() => {
  if (!promotedForm.audioEnabled.value) return t('setup.audio.statusDisabled')
  if (audioKeyReferenced.value) return t('setup.audio.statusReady')
  return t('setup.audio.statusNeedsKey')
})
const audioBadgeTone = computed(() => {
  if (!promotedForm.audioEnabled.value) return 'is-muted'
  return audioKeyReferenced.value ? 'is-ok' : 'is-warn'
})
const audioBadgeLabel = computed(() => {
  if (!promotedForm.audioEnabled.value) return t('setup.readiness.optional')
  return audioKeyReferenced.value ? t('setup.readiness.ready') : t('setup.readiness.needsAction')
})
const audioKeyPlaceholder = computed(() => promotedForm.audioKeyConfigured.value ? t('setup.common.leaveBlankKeep') : t('setup.audio.pasteKey'))

const providerProbeMissingFields = computed(() => {
  if (!providerForm.selectedProvider.value) return []
  return providerFields.value
    .filter(field => field.required === true && !isProviderCredentialField(field))
    .filter(field => !String(providerForm.fieldValue(field, currentProviderConfig.value) ?? '').trim())
    .map(providerProbeFieldLabel)
})

const providerProbeDisabledReason = computed(() => {
  if (providerProbeMissingFields.value.length === 0) return ''
  return t('setup.provider.probeMissingRequired', {
    fields: providerProbeMissingFields.value.join(t('setup.provider.requiredFieldJoiner')),
  })
})

const providerCredentialPanel = computed(() => {
  if (!providerSpec.value) return null
  const selectedProviderId = String(providerForm.selectedProvider.value || '').trim().toLowerCase()
  const savedCredential = status.value.llmCredentialStatus || {}
  const savedProviderId = String(savedCredential.provider || '').trim().toLowerCase()
  const savedMatchesSelected = selectedProviderId !== '' && savedProviderId === selectedProviderId
  const requiresApiKey = providerSpec.value.requiresApiKey !== false
  const acceptsApiKey = providerSpec.value.acceptsApiKey !== undefined
    ? providerSpec.value.acceptsApiKey === true
    // Older gateways do not publish acceptsApiKey. Fall back conservatively:
    // a provider that requires a key necessarily accepts one, while an
    // optional/keyless provider stays keyless instead of exposing a control
    // whose semantics that gateway never advertised.
    : requiresApiKey

  return {
    providerLabel: providerSpec.value.label || providerForm.selectedProvider.value,
    providerSelected: Boolean(providerForm.selectedProvider.value),
    acceptsApiKey,
    requiresApiKey,
    available: savedMatchesSelected ? savedCredential.available === true : !requiresApiKey,
    source: savedMatchesSelected
      ? String(savedCredential.source || 'none')
      : (requiresApiKey ? 'none' : 'not_required'),
    envKey: savedMatchesSelected
      ? String(savedCredential.envKey || providerSpec.value.envKey || '')
      : String(providerSpec.value.envKey || ''),
    masked: savedMatchesSelected ? String(savedCredential.masked || '') : '',
    revealAllowed: savedMatchesSelected ? savedCredential.revealAllowed === true : false,
    revealed: providerForm.revealedCredential.value,
    revealError: providerForm.revealError.value,
    replacing: providerForm.replacingCredential.value,
    apiKeyValue: String(providerForm.providerFieldValues.value.api_key || ''),
    apiKeyEnvValue: providerForm.fieldValue(
      { name: 'api_key_env', label: t('setup.common.apiKeyEnv'), default: providerSpec.value.envKey || '' },
      savedMatchesSelected ? (config.value.llm || {}) : {},
    ),
    probeReady: Boolean(providerForm.selectedProvider.value) && providerProbeMissingFields.value.length === 0,
    probeDisabledReason: providerProbeDisabledReason.value,
    connection: providerForm.connection.value,
    onReveal: revealProviderCredential,
    onReplace: providerForm.startCredentialReplace,
    onCancelReplace: providerForm.cancelCredentialReplace,
  }
})

const providerPanel = providerForm.createPanel({
  currentConfig: currentProviderConfig,
  providerSummary,
  runtimeProviders,
  routerSupportTone,
  routerSupportText,
  canConfigureRouter,
  providerNeeds,
  providerCoreFields,
  providerAdvancedFields,
  providerCredentialPanel,
  providerAdvancedOpen,
  providerEnvMissing,
  providerEnvKey,
  providerEnvCommand,
  llmTimeoutSeconds: promotedForm.llmTimeoutSeconds,
  contextWindowTokens: promotedForm.contextWindowTokens,
  contextWindowGlobal,
  providerIsLocal,
})

const behaviorPanel = behaviorForm.createPanel({
  statusText: behaviorStatusText,
})

const privacyPanel = computed(() => ({
  disableNetworkObservability: disableNetworkObservability.value,
  disableNetworkObservabilityDirty: privacyDirty.value,
  statusText: privacyStatusText.value,
}))

const isOpenrouterProvider = computed(() => currentProvider.value.toLowerCase() === 'openrouter')
const normalizedProvider = computed(() => currentProvider.value.toLowerCase())
function reconcileEnsembleProviderCompatibility() {
  const provider = normalizedProvider.value
  const staticProfile = STATIC_B5_PROFILES[ensembleForm.selectionMode.value]
  if (provider && staticProfile && provider !== staticProfile.provider) {
    // The stored static profile belongs to another provider: move to this
    // provider's own static profile when it has one, else to an explicit
    // custom lineup (seeded from the router tiers so it can actually run).
    const ownPreset = staticB5ModeForProvider(provider)
    if (ownPreset) {
      ensembleForm.setSelectionMode(ownPreset)
    } else {
      ensembleForm.activateForProvider(provider, ensembleTierCandidates.value)
    }
  }
}

// openrouter-mix is only valid for the openrouter provider. When the selection
// moves off openrouter while a stored mix mode is loaded, coerce the mode back
// to recommended so the save payload stays valid for the new provider. watch
// only fires on transitions, so an initial load never trips this.
watch(normalizedProvider, (provider) => {
  if (provider !== 'openrouter' && routerForm.mode.value === 'openrouter-mix') {
    routerForm.setRouterMode('recommended')
  }
  reconcileEnsembleProviderCompatibility()
})
const routerPanel = routerForm.createPanel({
  routerSummary,
  ensembleProfileActive,
  hasSavedProvider,
  isOpenrouter: isOpenrouterProvider,
  textTiers: TEXT_TIERS,
  tierLabel,
  discoveredModelsByProvider: computed(() => {
    const catalogs: DiscoveredModelsByProvider = { ...tierModelCatalogs.value }
    const provider = normalizeProviderId(providerForm.selectedProvider.value)
    if (provider) {
      catalogs[provider] = {
        models: providerForm.connection.value.models,
        source: providerForm.connection.value.modelSource,
      }
    }
    return catalogs
  }),
})

const ensembleTierCandidates = computed(() => routerPanel.value.tierRows.map(row => ({
  provider: row.provider,
  model: row.model,
  tier: row.name,
})))

// ---------------------------------------------------------------------------
// Routing preset card (Provider panel)
// ---------------------------------------------------------------------------

const selectedPreset = computed<ProviderPresetSpec | null>(() => providerSpec.value?.presets?.[0] || null)

const presetRouterMode = computed(() => (
  String(((status.value.sectionDetails || {}).router || {}).routerMode || 'recommended')
))

// "Configured beyond defaults": any unsaved router edits, or a persisted
// non-recommended mode. A pristine install (no config file yet) defaults to
// openrouter-mix on the wire, but nothing deliberate exists to clobber there,
// so the apply path stays available for true first-run beginners.
const presetRouterCustomized = computed(() => {
  if (routerForm.isDirty.value) return true
  if (status.value.hasConfig === false) return false
  return presetRouterMode.value !== 'recommended'
})

function presetTierRows(preset: ProviderPresetSpec | null): SetupTierRow[] {
  const tiers = preset?.tiers || {}
  const order: string[] = [...TEXT_TIERS, IMAGE_TIER]
  return Object.entries(tiers)
    .map(([name, tier]) => ({ name: normalizeRouterTier(name) || name, tier }))
    .filter(({ name }) => order.includes(name))
    .sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
    .map(({ name, tier }) => ({
      name,
      provider: tier.provider || '',
      model: tier.model || '',
      thinkingLevel: tier.thinkingLevel || tier.thinking_level || '',
      supportsImage: tier.supportsImage || tier.supports_image || false,
    }))
}

const presetPanel = computed(() => ({
  hasPreset: Boolean(selectedPreset.value),
  presetLabel: selectedPreset.value?.label || '',
  presetDescription: selectedPreset.value?.description || '',
  synthesized: selectedPreset.value?.synthesized === true,
  tierRows: presetTierRows(selectedPreset.value),
  tierLabel,
  routerMode: presetRouterMode.value,
  routerCustomized: presetRouterCustomized.value,
}))

const ensembleStatusText = computed(() => (
  ensembleForm.enabled.value ? t('setup.ensemble.statusOn') : t('setup.ensemble.statusOff')
))

const ensemblePanel = ensembleForm.createPanel({
  statusText: ensembleStatusText,
  activeProvider: currentProvider,
  activeModel: currentModel,
  tierCandidates: ensembleTierCandidates,
  credentialStatus: computed(() => status.value.ensembleCredentialStatus || []),
})

const modelStrategyPanel = modelStrategyForm.createPanel({
  hasSavedProvider,
  providerLabel: providerSummary,
  routerPanel,
  ensemblePanel,
  routerTemplateState: routerForm.tierTemplateState,
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
  audioBaseUrl: promotedForm.audioBaseUrl,
  audioTtsVoice: promotedForm.audioTtsVoice,
  audioTtsModel: promotedForm.audioTtsModel,
  audioLanguageCode: promotedForm.audioLanguageCode,
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
    push(t('setup.action.envNotVisible', { envKey: providerEnvKey.value }), 'provider')
  } else if (!llm.provider || !llm.model) {
    push(t('setup.action.connectProvider'), 'provider')
  }
  const details = status.value.sectionDetails || {}
  Object.entries(details).forEach(([name, detail]) => {
    if (!detail.blocking && !detail.actionRequired) return
    if (name === 'llm' || name === 'provider') {
      push(t('setup.action.connectProvider'), 'provider')
      return
    }
    push(setupActionReason(name, detail), sectionForDetailName(name) || 'provider')
  })
  if (!items.length) push(t('setup.action.reviewPending'), 'provider')
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
    .map(entry => ({ label: entry.label || t('setup.command.setEnvKey'), command: entry.command || '' }))
})

const fixCommands = computed(() => {
  if (!envRecoveryCommands.value.length) return []
  return [
    ...envRecoveryCommands.value,
    { label: t('setup.command.restartAfterEnv'), command: `opensquilla gateway restart${configCliArg.value}` },
  ]
})

const handoffCommands = computed(() => [
  { label: t('setup.command.cliOnboarding'), command: `opensquilla onboard --if-needed${configCliArg.value}` },
  { label: t('setup.command.checkStatus'), command: `opensquilla onboard status${configCliArg.value}` },
])

const recipeCommands = computed(() => [
  { label: t('setup.command.providerOptions'), command: `opensquilla onboard catalog providers${configCliArg.value}` },
  { label: t('setup.command.routerTiers'), command: `opensquilla onboard catalog router${configCliArg.value}` },
  { label: t('setup.command.searchOptions'), command: `opensquilla onboard catalog search${configCliArg.value}` },
  { label: t('setup.command.channelOptions'), command: `opensquilla onboard catalog channels${configCliArg.value}` },
  { label: t('setup.command.imageOptions'), command: `opensquilla onboard catalog image${configCliArg.value}` },
  { label: t('setup.command.memoryOptions'), command: `opensquilla onboard catalog memory${configCliArg.value}` },
])

const configSummary = computed(() => {
  const rows: Array<{ label: string; value: string }> = [
    { label: t('setup.summary.provider'), value: providerSummary.value },
    { label: t('setup.summary.model'), value: modelSummary.value },
  ]
  if (providerProxy.value) rows.push({ label: t('setup.summary.proxy'), value: providerProxy.value })
  rows.push({ label: t('setup.summary.router'), value: routerSummary.value })
  rows.push({ label: t('setup.summary.channels'), value: String(status.value.channelCount || 0) })
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
  // Kept in sync with the SETTINGS_SECTIONS rail order so `/settings/auto` lands
  // on the first not-ready section in the same top-to-bottom order the rail reads
  // (Provider -> Model Strategy -> Capabilities -> Channels).
  const sectionOrder: Array<[string, SettingsSectionId]> = [
    ['llm', 'provider'],
    ['router', 'modelStrategy'],
    ['ensemble', 'modelStrategy'],
    ['search', 'capabilities'],
    ['image_generation', 'capabilities'],
    ['memory_embedding', 'capabilities'],
    ['audio', 'capabilities'],
    ['channels', 'channels'],
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
    if (rpc.isConnected) return { label: t('setup.connection.connected'), tone: 'is-ok' }
    if (rpc.isConnecting) return { label: t('setup.connection.connecting'), tone: 'is-muted' }
    return { label: t('setup.connection.disconnected'), tone: 'is-warn' }
  }
  if (sectionId === 'provider') {
    if (providerEnvMissing.value) return { label: t('setup.readiness.needsAction'), tone: 'is-warn' }
    return detailStepStatus((status.value.sectionDetails || {}).llm || (status.value.sectionDetails || {}).provider)
  }
  // Behavior/Privacy/Ensemble are always-valid preference toggles, not
  // readiness milestones — a neutral dot (rather than a green "Live" that
  // overstates earned readiness) is honest; the dirty pip already signals
  // unsaved edits.
  if (sectionId === 'behavior' || sectionId === 'privacy' || sectionId === 'ensemble') {
    return { label: t('setup.status.appliesOnSave'), tone: 'is-muted' }
  }
  if (sectionId === 'modelStrategy' && !hasSavedProvider.value) {
    return { label: t('setup.status.providerFirst'), tone: 'is-muted' }
  }
  if (sectionId === 'modelStrategy') return aggregateStepStatus(['router', 'ensemble'])
  if (sectionId === 'channels') return detailStepStatus((status.value.sectionDetails || {}).channels)
  if (sectionId === 'capabilities') {
    return aggregateStepStatus(['search', 'image_generation', 'memory_embedding', 'audio'])
  }
  return { label: t('setup.status.review'), tone: 'is-muted' }
}

function detailStepStatus(detail?: SectionDetail): { label: string; tone: string } {
  if (!detail) return { label: t('setup.status.review'), tone: 'is-muted' }
  if (stepDetailNeedsAction(detail)) return { label: t('setup.readiness.needsAction'), tone: 'is-warn' }
  if (detail.status === 'ok') return { label: t('setup.readiness.ready'), tone: 'is-ok' }
  return { label: readinessLabel(detail.status || '') || t('setup.readiness.optional'), tone: 'is-muted' }
}

function aggregateStepStatus(sectionNames: string[]): { label: string; tone: string } {
  const details = status.value.sectionDetails || {}
  const entries = sectionNames.map(name => details[name]).filter(Boolean) as SectionDetail[]
  if (entries.some(detail => stepDetailNeedsAction(detail))) {
    return { label: t('setup.readiness.needsAction'), tone: 'is-warn' }
  }
  if (entries.length && entries.every(detail => detail.status === 'ok')) {
    return { label: t('setup.readiness.ready'), tone: 'is-ok' }
  }
  return { label: t('setup.readiness.optional'), tone: 'is-muted' }
}

function stepDetailNeedsAction(detail: SectionDetail): boolean {
  return Boolean(detail && (detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'))
}

function setupActionReason(name: string, detail: SectionDetail): string {
  const missingEnvPrefix = 'env key not visible: '
  const detailText = String(detail.detail || '')
  if (detailText.startsWith(missingEnvPrefix)) {
    const envKey = detailText.slice(missingEnvPrefix.length).trim()
    if (envKey) return t('setup.action.envNotVisible', { envKey })
  }
  return t('setup.action.setupNeeded', { label: detail.label || name })
}

function sectionForDetailName(name: string): SettingsSectionId | null {
  if (name === 'llm' || name === 'provider') return 'provider'
  if (name === 'router' || name === 'ensemble') return 'modelStrategy'
  if (name === 'channels') return 'channels'
  if (name === 'search' || name === 'image_generation' || name === 'memory_embedding' || name === 'audio') return 'capabilities'
  return null
}

// ---------------------------------------------------------------------------
// Dirty state
// ---------------------------------------------------------------------------

const providerDirty = computed(() => (
  providerForm.isDirty.value
  || promotedForm.timeoutDirty.value
  || promotedForm.contextWindowDirty.value
))
const behaviorDirty = computed(() => behaviorForm.isDirty.value)
const privacySectionDirty = computed(() => privacyDirty.value)
const modelStrategyDirty = computed(() => modelStrategyForm.isDirty.value)
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
  if (sectionId === 'behavior') return behaviorDirty.value
  if (sectionId === 'privacy') return privacySectionDirty.value
  if (sectionId === 'modelStrategy') return modelStrategyDirty.value
  if (sectionId === 'channels') return channelsDirty.value
  if (sectionId === 'capabilities') return capabilitiesDirty.value
  return false
}

const dirtySections = computed(() => SETTINGS_SECTIONS.filter(s => sectionDirty(s.id)))
const hasUnsavedChanges = computed(() => dirtySections.value.length > 0)

async function saveDirtySections() {
  const otherSectionsDirty = (
    providerDirty.value
    || behaviorDirty.value
    || modelStrategyDirty.value
    || channelsDirty.value
    || capabilitiesForm.searchDirty.value
    || capabilitiesForm.memoryDirty.value
    || promotedForm.captureDirty.value
    || capabilitiesForm.imageDirty.value
    || promotedForm.audioDirty.value
  )
  if (privacySectionDirty.value) {
    const saved = await savePrivacy(disableNetworkObservability.value, { reload: !otherSectionsDirty })
    if (!saved) return
  }
  if (providerDirty.value) await saveProvider()
  if (behaviorDirty.value) await saveBehavior()
  if (modelStrategyDirty.value) await saveModelStrategy()
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

function isProviderCredentialField(field: FieldSpec): boolean {
  return field.name === 'api_key' || field.name === 'api_key_env'
}

function providerProbeFieldLabel(field: FieldSpec): string {
  if (field.name === 'model') return t('setup.common.model')
  if (field.name === 'base_url') return t('setup.common.baseUrl')
  return field.label
}

function selectProvider(value: string) {
  providerForm.selectProvider(value)
}

function setAutoSessionTitles(enabled: boolean) {
  behaviorForm.setAutoSessionTitles(enabled)
}

function setDisableNetworkObservability(enabled: boolean) {
  disableNetworkObservability.value = enabled
}

function onProviderChange() {
  providerForm.resetForProvider(providerSpec.value)
  // The context-window override is per provider+model, so a provider switch must
  // reseed the field (value + baseline) from the newly-selected provider's saved
  // override — otherwise it keeps showing/saving the previous provider's value.
  promotedForm.reseedContextWindow(config.value, providerForm.selectedProvider.value, currentFormModelValue())
}

// The model id currently entered in the provider form (form value → saved
// config → spec default), trimmed. Drives the per-model context-window override.
function currentFormModelValue(): string {
  const modelField = providerFields.value.find(f => f.name === 'model') || { name: 'model', label: 'model' }
  return String(providerForm.fieldValue(modelField, config.value.llm || {}) || '').trim()
}

function updateProviderField(name: string, value: unknown) {
  providerForm.updateField(name, value)
  // Editing the model field switches which per-model override applies, so reseed
  // the context-window field from the saved override for the new model id.
  if (name === 'model') {
    promotedForm.reseedContextWindow(config.value, providerForm.selectedProvider.value, String(value ?? '').trim())
  }
}

async function revealProviderCredential() {
  const providerId = String(providerForm.selectedProvider.value || '').trim()
  if (!providerId) return
  try {
    const res = await rpc.call<{ ok?: boolean; apiKey?: string }>('onboarding.provider.credential.reveal', { providerId })
    if (res?.ok && typeof res.apiKey === 'string' && res.apiKey.length > 0) {
      providerForm.setRevealedCredential(res.apiKey)
      return
    }
    providerForm.setRevealError(t('setup.provider.credentialRevealUnavailable'))
  } catch (err) {
    providerForm.setRevealError(saveFailedMessage(err))
  }
}

// Optional accelerator: live-probe the CURRENT (possibly unsaved) provider
// form values. Never gates saving. The probe RPC requires a model id, so an
// empty model field falls back to the catalog's default for the provider.
function probeProviderConnection() {
  if (providerProbeMissingFields.value.length > 0) return
  void providerForm.probeConnection({ defaultModel: providerSpec.value?.defaultModel || '' })
}

function updateLlmTimeout(value: number) {
  promotedForm.setLlmTimeoutSeconds(value)
}

function updateContextWindow(value: string) {
  promotedForm.setContextWindowTokens(value)
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
// Ensemble helpers
// ---------------------------------------------------------------------------

function setEnsembleEnabled(value: boolean) {
  ensembleForm.setEnabled(value)
}

function setEnsembleSelectionMode(value: string) {
  ensembleForm.setSelectionMode(value)
}

function addEnsembleModelOption(value: string) {
  ensembleForm.addModelOption(value)
}

function removeEnsembleModelOption(value: string) {
  ensembleForm.removeModelOption(value)
}

function addEnsembleCandidate(provider: string, model: string, role: EnsembleCandidateRole = '') {
  ensembleForm.addCandidate(provider, model, role)
}

function removeEnsembleCandidate(candidate: EnsembleCandidateView) {
  ensembleForm.removeCandidate(candidate)
}

function setEnsembleCandidateRole(candidate: EnsembleCandidateView, role: EnsembleCandidateRole) {
  ensembleForm.setCandidateRole(candidate, role)
}

function importEnsembleTierCandidates() {
  ensembleForm.importTierCandidates(ensembleTierCandidates.value)
}

function migrateEnsembleLegacy() {
  ensembleForm.migrateLegacyToCustom(ensembleTierCandidates.value)
}

function resetEnsembleCandidates() {
  ensembleForm.resetModelOptions()
}

function setEnsembleScheme(scheme: 'preset' | 'custom') {
  ensembleForm.setScheme(scheme, staticB5ModeForProvider(currentProvider.value))
}

function setEnsembleMinSuccessful(value: number) {
  ensembleForm.setMinSuccessfulProposers(value)
}

function setEnsembleAllFailedPolicy(value: string) {
  ensembleForm.setAllFailedPolicy(value)
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
    return t('setup.search.statusOff')
  }
  if (status.value.searchConfigured === true) {
    return t('setup.search.statusReady')
  }
  if (status.value.searchSource === 'missing_env') {
    return _missingEnvStatusText(t('setup.search.title'), status.value.searchEnvKey, t('setup.search.statusNeedsKey'))
  }
  return t('setup.search.statusNeedsKey')
}

function _imageGenerationStatusText(): string {
  if (status.value.imageGenerationEnabled === false) {
    return t('setup.image.statusDisabled')
  }
  if (status.value.imageGenerationConfigured === true) {
    if (status.value.imageGenerationSource === 'llm_fallback') {
      return t('setup.image.statusReadyFallback')
    }
    return t('setup.image.statusReady')
  }
  if (status.value.imageGenerationSource === 'missing_env') {
    return _missingEnvStatusText(t('setup.image.title'), status.value.imageGenerationEnvKey, t('setup.image.statusNeedsKey'))
  }
  return t('setup.image.statusNeedsKey')
}

function _memoryEmbeddingStatusText(providerId = ''): string {
  const current = config.value.memory?.embedding || {}
  const savedProvider = current.provider || current.mode || status.value.memoryEmbeddingProvider || 'auto'
  const provider = providerId || savedProvider
  if (provider === 'none') {
    return t('setup.memory.statusNone')
  }
  if (provider === 'local') {
    return t('setup.memory.statusLocal')
  }
  if (provider === 'ollama') {
    return t('setup.memory.statusOllama')
  }
  if (provider === 'auto') {
    return t('setup.memory.statusAuto')
  }
  if (provider === savedProvider && status.value.memoryEmbeddingConfigured === true) {
    return t('setup.memory.statusConfigured')
  }
  if (provider === savedProvider && status.value.memoryEmbeddingSource === 'missing_env') {
    return _missingEnvStatusText(t('setup.memory.remoteEmbeddings'), status.value.memoryEmbeddingEnvKey, t('setup.memory.statusNeedsKey'))
  }
  return t('setup.memory.statusNeedsKey')
}

function _missingEnvStatusText(capability: string, envKey: string | undefined, fallback: string): string {
  const key = String(envKey || '').trim()
  if (!key) return fallback
  return t('setup.status.envNotVisible', { capability, envKey: key })
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
  if (detail.blocking || detail.actionRequired) return t('setup.readiness.needsAction')
  return readinessLabel(detail.status || '') || t('setup.readiness.optional')
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

function sameEndpointOrigin(candidateValue: unknown, storedValue: unknown): boolean {
  const candidate = String(candidateValue || '').trim()
  if (!candidate) return true
  const stored = String(storedValue || '').trim()
  if (!stored) return false
  if (candidate === stored) return true
  try {
    const candidateOrigin = new URL(candidate).origin
    const storedOrigin = new URL(stored).origin
    return candidateOrigin !== 'null' && candidateOrigin === storedOrigin
  } catch {
    return false
  }
}

function providerConfigurePayload(): Record<string, unknown> {
  const payload = providerForm.payload()
  const selectedProviderId = String(providerForm.selectedProvider.value || '').trim().toLowerCase()
  const savedCredential = status.value.llmCredentialStatus || {}
  const savedProviderId = String(savedCredential.provider || '').trim().toLowerCase()
  const credentialPanel = providerCredentialPanel.value
  const hasReplacement = payload.apiKey !== undefined || payload.apiKeyEnv !== undefined
  const endpointMatches = sameEndpointOrigin(payload.baseUrl, config.value.llm?.base_url)
  if (
    credentialPanel?.acceptsApiKey === true
    && credentialPanel.requiresApiKey === false
    && savedCredential.source === 'explicit'
    && selectedProviderId !== ''
    && selectedProviderId === savedProviderId
    && !hasReplacement
    && endpointMatches
  ) {
    payload.preserveApiKey = true
  }
  return payload
}

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

// Deep-merge form of config.patch: `patch` is a nested object merged into the
// config tree (null deletes a key). Required for the models.<provider>.<model>
// subtree, whose model-id keys contain dots/colons that dot-path patches would
// misparse as path separators.
async function deepPatchConfig(patch: Record<string, unknown>): Promise<boolean> {
  if (!Object.keys(patch).length) return false
  const res = await rpc.call<{ restartRequired?: boolean }>('config.patch', { patch })
  return res?.restartRequired === true
}

async function saveProvider() {
  if (!providerForm.selectedProvider.value) {
    pushToast(t('setup.toast.chooseProvider'), { tone: 'danger' })
    return
  }
  try {
    const payload = providerConfigurePayload()
    await rpc.call('onboarding.provider.configure', payload)
    const restart = await patchConfig(promotedForm.providerPatches())
    // The per-model context-window override rides the deep-merge patch form. Key
    // it on the CURRENT form model field (not payload.model, which is empty when
    // the user didn't retype the model, nor the pre-save config model) and skip
    // the patch entirely when no model is selected.
    const contextModel = currentFormModelValue()
    if (contextModel) {
      const contextPatch = promotedForm.contextWindowPatch(providerForm.selectedProvider.value, contextModel)
      if (contextPatch) await deepPatchConfig(contextPatch)
    }
    await loadData()
    if (providerEnvMissing.value) {
      pushToast(t('setup.toast.envNotVisibleGateway', { envKey: providerEnvKey.value }), { tone: 'danger' })
      return
    }
    pushToast(restart ? t('setup.toast.providerSavedRestart') : t('setup.toast.providerSaved'))
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveBehavior() {
  try {
    const restart = await safePatchConfig(behaviorForm.patches())
    pushToast(restart ? t('setup.toast.behaviorSavedRestart') : t('setup.toast.behaviorSaved'))
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function savePrivacy(
  value = disableNetworkObservability.value,
  options: { reload?: boolean } = {},
): Promise<boolean> {
  try {
    const restart = await safePatchConfig({
      'privacy.disable_network_observability': value,
    })
    if (options.reload === false) {
      config.value = {
        ...config.value,
        privacy: {
          ...(config.value.privacy || {}),
          disable_network_observability: value,
          network_observability_disabled_effective: value || networkObservabilityDisabledByEnvironment.value,
        },
      }
      disableNetworkObservability.value = value
    } else {
      await loadData()
    }
    pushToast(restart ? t('setup.toast.privacySavedRestart') : t('setup.toast.privacySaved'))
    return true
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
    return false
  }
}

async function saveRouter() {
  if (!hasSavedProvider.value && routerForm.routingDirty.value) {
    pushToast(t('setup.toast.chooseProviderRouter'), { tone: 'danger' })
    return
  }
  try {
    if (routerForm.routingDirty.value) {
      await rpc.call('onboarding.router.configure', routerForm.payload())
    }
    const restart = await safePatchConfig(routerForm.visualModePatches())
    pushToast(restart ? t('setup.toast.routerSavedRestart') : t('setup.toast.routerSaved'))
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveEnsemble() {
  try {
    // Partial payload: only the keys the user actually changed; the gateway
    // keeps current values for everything omitted. No restart — the turn
    // loop reads [llm_ensemble] live.
    const params = ensembleForm.payload()
    if (Object.keys(params).length) {
      await rpc.call('onboarding.ensemble.configure', params)
    }
    pushToast(t('setup.toast.ensembleSaved'))
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveModelStrategy() {
  const routerRoutingPayload = routerForm.routingDirty.value ? routerForm.payload() : null
  const routerVisualPatches = routerForm.visualModePatches()
  const ensemblePayload = ensembleForm.payload()
  const hasRouterWork = Boolean(routerRoutingPayload) || Object.keys(routerVisualPatches).length > 0
  const hasEnsembleWork = Object.keys(ensemblePayload).length > 0
  if (!hasRouterWork && !hasEnsembleWork) return

  let savedAny = false
  try {
    if (!hasSavedProvider.value && routerRoutingPayload) {
      pushToast(t('setup.toast.chooseProviderRouter'), { tone: 'danger' })
    } else if (hasRouterWork) {
      if (routerRoutingPayload) {
        await rpc.call('onboarding.router.configure', routerRoutingPayload)
      }
      const restart = await safePatchConfig(routerVisualPatches)
      pushToast(restart ? t('setup.toast.routerSavedRestart') : t('setup.toast.routerSaved'))
      savedAny = true
    }

    if (hasEnsembleWork) {
      await rpc.call('onboarding.ensemble.configure', ensemblePayload)
      pushToast(t('setup.toast.ensembleSaved'))
      savedAny = true
    }

    if (savedAny) await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

// Explicit-user-action preset application (the ONLY path that sends presetId):
// saves the current provider form values plus the preset, then reloads so the
// Router section and routerMode reflect the applied tiers. Confirm-free by
// design — the Router section can always change the result afterwards.
async function applyProviderPreset() {
  if (!providerForm.selectedProvider.value) {
    pushToast(t('setup.toast.chooseProvider'), { tone: 'danger' })
    return
  }
  const presetId = selectedPreset.value?.presetId || providerForm.selectedProvider.value
  try {
    await rpc.call('onboarding.provider.configure', { ...providerConfigurePayload(), presetId })
    const restart = await patchConfig(promotedForm.providerPatches())
    await loadData()
    if (providerEnvMissing.value) {
      pushToast(t('setup.toast.envNotVisibleGateway', { envKey: providerEnvKey.value }), { tone: 'danger' })
      return
    }
    pushToast(restart ? t('setup.toast.presetAppliedRestart') : t('setup.toast.presetApplied'))
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveChannel() {
  const entry = channelsForm.payload()
  try {
    await rpc.call('onboarding.channel.probe', { entry })
    await rpc.call('onboarding.channel.upsert', { entry })
    pushToast(t('setup.toast.channelSaved'))
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

// Lifecycle actions on already-configured channels. The enable/disable/remove
// RPCs all require a gateway restart to take effect; refresh only the runtime
// list (loadChannelStatus) so the in-progress entry draft is preserved.
async function setChannelEnabled(name: string, enabled: boolean) {
  try {
    await rpc.call(enabled ? 'onboarding.channel.enable' : 'onboarding.channel.disable', { name })
    pushToast(enabled ? t('setup.toast.channelEnabled') : t('setup.toast.channelDisabled'))
    await loadChannelStatus()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

function enableChannel(name: string) {
  return setChannelEnabled(name, true)
}

function disableChannel(name: string) {
  return setChannelEnabled(name, false)
}

async function removeChannel(name: string) {
  const ok = await confirm({
    title: t('setup.channels.removeConfirmTitle'),
    body: t('setup.channels.removeConfirmBody', { name }),
    primaryLabel: t('setup.channels.removeConfirmPrimary'),
  })
  if (!ok) return
  try {
    await rpc.call('onboarding.channel.remove', { name })
    pushToast(t('setup.toast.channelRemoved'))
    await loadChannelStatus()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveSearch() {
  const params = capabilitiesForm.searchPayload()
  try {
    await rpc.call('onboarding.search.configure', params)
    pushToast(t('setup.toast.searchSaved'))
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
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
      envToastShown = _toastEnvReferenceSave(t('setup.toast.memorySurface'), remote.api_key_env, '', remote.api_key ?? '', res?.restartRequired)
    }
    // The capture toggle rides config.patch and hot-applies; only embedding
    // changes need a gateway restart.
    await patchConfig(promotedForm.memoryPatches())
    if (!envToastShown) {
      pushToast(embeddingDirty ? t('setup.toast.memorySavedRestart') : t('setup.toast.memorySaved'))
    }
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveImage() {
  const params = capabilitiesForm.imagePayload()
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.imageGeneration.configure', params)
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave(t('setup.image.title'), entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      pushToast(t('setup.toast.imageSaved'))
    }
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
  }
}

async function saveAudio() {
  if (!promotedForm.audioDirty.value) {
    pushToast(t('setup.toast.noAudioChanges'))
    return
  }
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.audio.configure', promotedForm.audioPayload())
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave(t('setup.audio.title'), entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      pushToast(res?.restartRequired ? t('setup.toast.audioSavedRestart') : t('setup.toast.audioSaved'))
    }
    await loadData()
  } catch (err) {
    pushToast(saveFailedMessage(err), { tone: 'danger' })
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
    pushToast(t('setup.toast.envSavedRestart', { surface, envKey: key }))
    return true
  }
  pushToast(t('setup.toast.envSavedReference', { surface, envKey: key }))
  return true
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function tierLabel(tier: string): string {
  return t(routerTierLabelKey(tier))
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
    pushToast(t('setup.toast.copyFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  }
}

async function copyCommand(command: string) {
  await copyText(command, t('setup.toast.copiedCommand'))
}

async function copyConfigPath() {
  await copyText(configPath.value, t('setup.toast.copiedPath'))
}

  return {
    status,
    config,
    section,
    setSection,
    loaded,
    providerPanel,
    behaviorPanel,
    privacyPanel,
    modelStrategyPanel,
    routerPanel,
    presetPanel,
    ensemblePanel,
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
    setAutoSessionTitles,
    setDisableNetworkObservability,
    setModelStrategy: modelStrategyForm.setStrategy,
    setRouterMode,
    setRouterDefaultTier,
    setRouterVisualMode,
    setEnsembleEnabled,
    setEnsembleSelectionMode,
    addEnsembleModelOption,
    removeEnsembleModelOption,
    addEnsembleCandidate,
    removeEnsembleCandidate,
    setEnsembleCandidateRole,
    importEnsembleTierCandidates,
    migrateEnsembleLegacy,
    resetEnsembleCandidates,
    setEnsembleScheme,
    setEnsembleMinSuccessful,
    setEnsembleAllFailedPolicy,
    selectChannelType,
    updateProviderField,
    updateLlmTimeout,
    updateContextWindow,
    probeProviderConnection,
    revealProviderCredential,
    updateTierField,
    updateChannelField,
    updateCapabilityField,
    onProviderChange,
    onChannelTypeChange,
    onSearchProviderChange,
    onMemoryProviderChange,
    onImageProviderChange,
    saveProvider,
    saveBehavior,
    savePrivacy,
    saveRouter,
    saveEnsemble,
    saveModelStrategy,
    applyProviderPreset,
    saveChannel,
    enableChannel,
    disableChannel,
    removeChannel,
    saveSearch,
    saveMemory,
    saveImage,
    saveAudio,
    copyCommand,
    copyConfigPath,
  }
}
