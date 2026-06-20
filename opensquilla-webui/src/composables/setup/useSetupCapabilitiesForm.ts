import { computed, ref, type ComputedRef, type Ref } from 'vue'

interface ProviderSpec {
  providerId: string
  envKey?: string
  requiresApiKey?: boolean
  defaultBaseUrl?: string
  defaultModel?: string
  [key: string]: unknown
}

interface ConfigData {
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
        api_key_env?: string
        base_url?: string
      }
      local?: { onnx_dir?: string }
    }
  }
  image_generation?: {
    providers?: Record<string, { api_key_env?: string; base_url?: string }>
  }
}

interface StatusData {
  imageGenerationEnabled?: boolean
  imageGenerationProvider?: string
  imageGenerationPrimary?: string
}

interface CapabilitiesPanelContext {
  searchProviders: ComputedRef<Array<{ providerId: string; label: string }>>
  memoryProviders: ComputedRef<Array<{ providerId: string; label: string }>>
  imageProviders: ComputedRef<Array<{ providerId: string; label: string }>>
  imageSpec: ComputedRef<ProviderSpec | null>
  searchRequiresKey: ComputedRef<boolean>
  searchEnvPlaceholder: ComputedRef<string>
  searchAdvancedOpen: ComputedRef<boolean>
  searchNeeds: ComputedRef<string[]>
  searchEnvCommand: ComputedRef<string>
  searchStatusText: () => string
  memoryApiKeyEnabled: ComputedRef<boolean>
  memoryRemoteOptionsOpen: ComputedRef<boolean>
  memoryRemoteOptionsSummary: ComputedRef<string>
  memoryModelPlaceholder: ComputedRef<string>
  memoryBasePlaceholder: ComputedRef<string>
  memoryOnnxPlaceholder: ComputedRef<string>
  memoryApiKeyLabel: ComputedRef<string>
  memoryApiKeyPlaceholder: ComputedRef<string>
  memoryEnvPlaceholder: ComputedRef<string>
  memoryNeeds: ComputedRef<string[]>
  memoryStatusText: ComputedRef<string>
  memoryEnvCommand: ComputedRef<string>
  imageNeeds: ComputedRef<string[]>
  imageStatusText: ComputedRef<string>
  imageEnvCommand: ComputedRef<string>
  capabilityBadgeTone: (name: string) => string
  capabilityBadgeLabel: (name: string) => string
  capabilitySaveButtonClass: (name: string) => string
  memoryAutoCapture: Ref<boolean>
  audioEnabled: Ref<boolean>
  audioApiKey: Ref<string>
  audioApiKeyEnv: Ref<string>
  audioStatusText: ComputedRef<string>
  audioBadgeTone: ComputedRef<string>
  audioBadgeLabel: ComputedRef<string>
  audioKeyPlaceholder: ComputedRef<string>
}

export interface SearchFormValues {
  providerId: string
  apiKey: string
  apiKeyEnv: string
  maxResults: number
  proxy: string
  useEnvProxy: boolean
  fallbackPolicy: string
  diagnostics: boolean
}

export interface MemoryFormValues {
  providerId: string
  model: string
  apiKey: string
  apiKeyEnv: string
  baseUrl: string
  onnxDir: string
}

export interface ImageFormValues {
  providerId: string
  enabled: boolean
  primary: string
  apiKey: string
  apiKeyEnv: string
  baseUrl: string
}

export function buildSearchPayload(values: SearchFormValues): Record<string, unknown> {
  const params: Record<string, unknown> = { providerId: values.providerId }
  if (values.apiKey) params.apiKey = values.apiKey
  if (values.apiKeyEnv) params.apiKeyEnv = values.apiKeyEnv
  params.maxResults = values.maxResults
  if (values.proxy) params.proxy = values.proxy
  params.useEnvProxy = values.useEnvProxy
  params.fallbackPolicy = values.fallbackPolicy
  params.diagnostics = values.diagnostics
  return params
}

export function buildMemoryPayload(values: MemoryFormValues): Record<string, unknown> {
  const params: Record<string, unknown> = { providerId: values.providerId }
  if (values.model) params.model = values.model
  if (values.apiKey) params.apiKey = values.apiKey
  if (values.apiKeyEnv) params.apiKeyEnv = values.apiKeyEnv
  if (values.baseUrl) params.baseUrl = values.baseUrl
  if (values.onnxDir) params.onnxDir = values.onnxDir
  return params
}

export function buildImagePayload(values: ImageFormValues): Record<string, unknown> {
  const params: Record<string, unknown> = {
    providerId: values.providerId,
    enabled: values.enabled,
  }
  if (values.primary) params.primary = values.primary
  if (values.apiKey) params.apiKey = values.apiKey
  if (values.apiKeyEnv) params.apiKeyEnv = values.apiKeyEnv
  if (values.baseUrl) params.baseUrl = values.baseUrl
  return params
}

export function useSetupCapabilitiesForm() {
  const searchProvider = ref('duckduckgo')
  const searchMaxResults = ref(5)
  const searchApiKey = ref('')
  const searchApiKeyEnv = ref('')
  const searchProxy = ref('')
  const searchUseEnvProxy = ref(false)
  const searchFallbackPolicy = ref('off')
  const searchDiagnostics = ref(false)

  const memoryProvider = ref('auto')
  const memoryModel = ref('')
  const memoryApiKey = ref('')
  const memoryApiKeyEnv = ref('')
  const memoryBaseUrl = ref('')
  const memoryOnnxDir = ref('')

  const imageProvider = ref('openrouter')
  const imagePrimary = ref('')
  const imageApiKey = ref('')
  const imageApiKeyEnv = ref('')
  const imageBaseUrl = ref('')
  const imageEnabled = ref(true)

  const searchSerialized = computed(() => JSON.stringify([
    searchProvider.value, searchMaxResults.value, searchApiKey.value, searchApiKeyEnv.value,
    searchProxy.value, searchUseEnvProxy.value, searchFallbackPolicy.value, searchDiagnostics.value,
  ]))
  const memorySerialized = computed(() => JSON.stringify([
    memoryProvider.value, memoryModel.value, memoryApiKey.value, memoryApiKeyEnv.value,
    memoryBaseUrl.value, memoryOnnxDir.value,
  ]))
  const imageSerialized = computed(() => JSON.stringify([
    imageProvider.value, imagePrimary.value, imageApiKey.value, imageApiKeyEnv.value,
    imageBaseUrl.value, imageEnabled.value,
  ]))
  // Seed from the initial state so the pristine forms are never dirty while config loads.
  const searchBaseline = ref(searchSerialized.value)
  const memoryBaseline = ref(memorySerialized.value)
  const imageBaseline = ref(imageSerialized.value)
  const searchDirty = computed(() => searchSerialized.value !== searchBaseline.value)
  const memoryDirty = computed(() => memorySerialized.value !== memoryBaseline.value)
  const imageDirty = computed(() => imageSerialized.value !== imageBaseline.value)

  const memoryRemoteControlEnabled = computed(() => !['none', 'local'].includes(memoryProvider.value))
  const memoryLocalControlEnabled = computed(() => memoryProvider.value === 'local')
  const selectedSearchProvider = computed(() => searchProvider.value)
  const selectedMemoryProvider = computed(() => memoryProvider.value)
  const selectedImageProvider = computed(() => imageProvider.value)
  const imageIsEnabled = computed(() => imageEnabled.value)
  const searchAdvancedOpen = computed(() => Boolean(searchProxy.value || searchUseEnvProxy.value || searchFallbackPolicy.value !== 'off' || searchDiagnostics.value))
  const searchApiKeyEnvValue = computed(() => searchApiKeyEnv.value)
  const memoryApiKeyEnvValue = computed(() => memoryApiKeyEnv.value)
  const imageApiKeyEnvValue = computed(() => imageApiKeyEnv.value)
  const memoryRemoteOptionsOpen = computed(() => memoryProvider.value !== 'auto' || Boolean(memoryModel.value || memoryApiKey.value || memoryApiKeyEnv.value || memoryBaseUrl.value))
  const memoryRemoteOptionsSummary = computed(() => memoryProvider.value === 'auto' ? 'Remote fallback options' : 'Connection options')
  const memoryModelPlaceholder = computed(() => memoryProvider.value === 'ollama' ? 'nomic-embed-text' : (memoryRemoteControlEnabled.value ? 'remote-embedding-model' : 'not used by this provider'))
  const memoryBasePlaceholder = computed(() => memoryProvider.value === 'ollama' ? 'http://localhost:11434' : (memoryRemoteControlEnabled.value ? 'https://api.example.com/v1' : 'not used by this provider'))
  const memoryOnnxPlaceholder = computed(() => memoryLocalControlEnabled.value ? 'models/bge-onnx' : 'only for bundled local provider')
  const memoryApiKeyLabel = computed(() => memoryProvider.value === 'auto' ? 'Fallback API key' : 'API key')

  function initSearchFromConfig(config: ConfigData, providers: ProviderSpec[]) {
    searchProvider.value = config.search_provider || providers.find(p => p.providerId === 'duckduckgo')?.providerId || providers[0]?.providerId || 'duckduckgo'
    searchMaxResults.value = config.search_max_results || 5
    searchApiKeyEnv.value = config.search_api_key_env || ''
    searchProxy.value = config.search_proxy || ''
    searchUseEnvProxy.value = config.search_use_env_proxy === true
    searchFallbackPolicy.value = config.search_fallback_policy || 'off'
    searchDiagnostics.value = config.search_diagnostics === true
    searchApiKey.value = ''
    searchBaseline.value = searchSerialized.value
  }

  function initMemoryFromConfig(config: ConfigData) {
    const current = config.memory?.embedding || {}
    const effective = current.provider || current.mode || 'auto'
    memoryProvider.value = effective
    const remote = current.remote || {}
    memoryModel.value = remote.model || ''
    memoryApiKeyEnv.value = remote.api_key_env || ''
    memoryBaseUrl.value = remote.base_url || ''
    const local = current.local || {}
    memoryOnnxDir.value = local.onnx_dir || ''
    memoryApiKey.value = ''
    memoryBaseline.value = memorySerialized.value
  }

  function initImageFromConfig(config: ConfigData, status: StatusData, providers: ProviderSpec[]) {
    const imageConfig = config.image_generation || {}
    const selected = status.imageGenerationProvider || (status.imageGenerationPrimary || '').split('/')[0] || providers[0]?.providerId || 'openrouter'
    imageProvider.value = selected
    imagePrimary.value = status.imageGenerationPrimary || ''
    const providerConfig = (imageConfig.providers || {})[selected] || {}
    imageApiKeyEnv.value = providerConfig.api_key_env || ''
    imageBaseUrl.value = providerConfig.base_url || ''
    imageEnabled.value = status.imageGenerationEnabled !== false
    imageApiKey.value = ''
    imageBaseline.value = imageSerialized.value
  }

  function onSearchProviderChange(spec: ProviderSpec | null | undefined) {
    if (spec?.requiresApiKey) {
      searchApiKeyEnv.value = spec.envKey || ''
    } else {
      searchApiKeyEnv.value = ''
      searchApiKey.value = ''
    }
  }

  function onMemoryProviderChange(spec: ProviderSpec | null | undefined, apiKeyEnabled: boolean) {
    if (apiKeyEnabled && spec && !memoryApiKeyEnv.value) {
      memoryApiKeyEnv.value = spec.envKey || ''
    }
  }

  function onImageProviderChange(spec: ProviderSpec | null | undefined) {
    if (!spec) return
    imageApiKeyEnv.value = spec.requiresApiKey ? (spec.envKey || '') : ''
    if (!imagePrimary.value) imagePrimary.value = spec.defaultModel || ''
    if (!imageBaseUrl.value) imageBaseUrl.value = spec.defaultBaseUrl || ''
  }

  function updateField(
    group: 'search' | 'memory' | 'image',
    key: string,
    value: string | number | boolean,
  ) {
    if (group === 'search') {
      if (key === 'provider') searchProvider.value = String(value)
      else if (key === 'maxResults') searchMaxResults.value = Number(value)
      else if (key === 'apiKey') searchApiKey.value = String(value)
      else if (key === 'apiKeyEnv') searchApiKeyEnv.value = String(value)
      else if (key === 'proxy') searchProxy.value = String(value)
      else if (key === 'useEnvProxy') searchUseEnvProxy.value = Boolean(value)
      else if (key === 'fallbackPolicy') searchFallbackPolicy.value = String(value)
      else if (key === 'diagnostics') searchDiagnostics.value = Boolean(value)
      return
    }
    if (group === 'memory') {
      if (key === 'provider') memoryProvider.value = String(value)
      else if (key === 'model') memoryModel.value = String(value)
      else if (key === 'apiKey') memoryApiKey.value = String(value)
      else if (key === 'apiKeyEnv') memoryApiKeyEnv.value = String(value)
      else if (key === 'baseUrl') memoryBaseUrl.value = String(value)
      else if (key === 'onnxDir') memoryOnnxDir.value = String(value)
      return
    }
    if (key === 'provider') imageProvider.value = String(value)
    else if (key === 'primary') imagePrimary.value = String(value)
    else if (key === 'apiKey') imageApiKey.value = String(value)
    else if (key === 'apiKeyEnv') imageApiKeyEnv.value = String(value)
    else if (key === 'baseUrl') imageBaseUrl.value = String(value)
    else if (key === 'enabled') imageEnabled.value = Boolean(value)
  }

  function searchPayload(): Record<string, unknown> {
    return buildSearchPayload({
      providerId: searchProvider.value,
      apiKey: searchApiKey.value,
      apiKeyEnv: searchApiKeyEnv.value,
      maxResults: searchMaxResults.value,
      proxy: searchProxy.value,
      useEnvProxy: searchUseEnvProxy.value,
      fallbackPolicy: searchFallbackPolicy.value,
      diagnostics: searchDiagnostics.value,
    })
  }

  function memoryPayload(): Record<string, unknown> {
    return buildMemoryPayload({
      providerId: memoryProvider.value,
      model: memoryModel.value,
      apiKey: memoryApiKey.value,
      apiKeyEnv: memoryApiKeyEnv.value,
      baseUrl: memoryBaseUrl.value,
      onnxDir: memoryOnnxDir.value,
    })
  }

  function imagePayload(): Record<string, unknown> {
    return buildImagePayload({
      providerId: imageProvider.value,
      enabled: imageEnabled.value,
      primary: imagePrimary.value,
      apiKey: imageApiKey.value,
      apiKeyEnv: imageApiKeyEnv.value,
      baseUrl: imageBaseUrl.value,
    })
  }

  function createPanel(context: CapabilitiesPanelContext) {
    return computed(() => ({
      form: {
        searchProvider: searchProvider.value,
        searchMaxResults: searchMaxResults.value,
        searchApiKey: searchApiKey.value,
        searchApiKeyEnv: searchApiKeyEnv.value,
        searchProxy: searchProxy.value,
        searchUseEnvProxy: searchUseEnvProxy.value,
        searchFallbackPolicy: searchFallbackPolicy.value,
        searchDiagnostics: searchDiagnostics.value,
        memoryProvider: memoryProvider.value,
        memoryModel: memoryModel.value,
        memoryApiKey: memoryApiKey.value,
        memoryApiKeyEnv: memoryApiKeyEnv.value,
        memoryBaseUrl: memoryBaseUrl.value,
        memoryOnnxDir: memoryOnnxDir.value,
        imageProvider: imageProvider.value,
        imagePrimary: imagePrimary.value,
        imageApiKey: imageApiKey.value,
        imageApiKeyEnv: imageApiKeyEnv.value,
        imageBaseUrl: imageBaseUrl.value,
        imageEnabled: imageEnabled.value,
        memoryAutoCapture: context.memoryAutoCapture.value,
        audioEnabled: context.audioEnabled.value,
        audioApiKey: context.audioApiKey.value,
        audioApiKeyEnv: context.audioApiKeyEnv.value,
      },
      options: {
        searchProviders: context.searchProviders.value,
        memoryProviders: context.memoryProviders.value,
        imageProviders: context.imageProviders.value,
        imageSpec: context.imageSpec.value,
      },
      state: {
        searchRequiresKey: context.searchRequiresKey.value,
        searchEnvPlaceholder: context.searchEnvPlaceholder.value,
        searchAdvancedOpen: searchAdvancedOpen.value,
        searchNeeds: context.searchNeeds.value,
        searchEnvCommand: context.searchEnvCommand.value,
        searchStatusText: context.searchStatusText(),
        memoryLocalControlEnabled: memoryLocalControlEnabled.value,
        memoryRemoteControlEnabled: memoryRemoteControlEnabled.value,
        memoryApiKeyEnabled: context.memoryApiKeyEnabled.value,
        memoryRemoteOptionsOpen: memoryRemoteOptionsOpen.value,
        memoryRemoteOptionsSummary: memoryRemoteOptionsSummary.value,
        memoryModelPlaceholder: memoryModelPlaceholder.value,
        memoryBasePlaceholder: memoryBasePlaceholder.value,
        memoryOnnxPlaceholder: memoryOnnxPlaceholder.value,
        memoryApiKeyLabel: memoryApiKeyLabel.value,
        memoryApiKeyPlaceholder: context.memoryApiKeyPlaceholder.value,
        memoryEnvPlaceholder: context.memoryEnvPlaceholder.value,
        memoryNeeds: context.memoryNeeds.value,
        memoryStatusText: context.memoryStatusText.value,
        memoryEnvCommand: context.memoryEnvCommand.value,
        imageNeeds: context.imageNeeds.value,
        imageStatusText: context.imageStatusText.value,
        imageEnvCommand: context.imageEnvCommand.value,
        capabilityBadgeTone: context.capabilityBadgeTone,
        capabilityBadgeLabel: context.capabilityBadgeLabel,
        capabilitySaveButtonClass: context.capabilitySaveButtonClass,
        audioStatusText: context.audioStatusText.value,
        audioBadgeTone: context.audioBadgeTone.value,
        audioBadgeLabel: context.audioBadgeLabel.value,
        audioKeyPlaceholder: context.audioKeyPlaceholder.value,
      },
    }))
  }

  return {
    selectedSearchProvider,
    selectedMemoryProvider,
    selectedImageProvider,
    imageIsEnabled,
    searchDirty,
    memoryDirty,
    imageDirty,
    searchAdvancedOpen,
    searchApiKeyEnvValue,
    memoryApiKeyEnvValue,
    imageApiKeyEnvValue,
    memoryRemoteOptionsOpen,
    memoryRemoteOptionsSummary,
    memoryModelPlaceholder,
    memoryBasePlaceholder,
    memoryOnnxPlaceholder,
    memoryApiKeyLabel,
    memoryRemoteControlEnabled,
    memoryLocalControlEnabled,
    initSearchFromConfig,
    initMemoryFromConfig,
    initImageFromConfig,
    onSearchProviderChange,
    onMemoryProviderChange,
    onImageProviderChange,
    updateField,
    searchPayload,
    memoryPayload,
    imagePayload,
    createPanel,
  }
}
