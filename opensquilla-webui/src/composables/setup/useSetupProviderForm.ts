import { computed, ref, type ComputedRef, type Ref } from 'vue'

interface ProviderField {
  name: string
  label: string
  type?: string
  secret?: boolean
  default?: string | boolean | number
  [key: string]: unknown
}

interface ProviderSpec {
  providerId: string
  fields?: ProviderField[]
}

interface ProviderConfig {
  provider?: string
  model?: string
  base_url?: string
  proxy?: string
  api_key_env?: string
  api_key?: string
  [key: string]: unknown
}

interface SetupStatus {
  hasConfig?: boolean
  llmConfigured?: boolean
  llmSource?: string
}

interface ProviderPanelContext {
  currentConfig: ComputedRef<ProviderConfig>
  providerSummary: ComputedRef<string>
  runtimeProviders: ComputedRef<Array<{ providerId: string; label: string }>>
  routerSupportTone: ComputedRef<string>
  routerSupportText: ComputedRef<string>
  canConfigureRouter: ComputedRef<boolean>
  providerNeeds: ComputedRef<string[]>
  providerCoreFields: ComputedRef<ProviderField[]>
  providerAdvancedFields: ComputedRef<ProviderField[]>
  providerAdvancedOpen: ComputedRef<boolean>
  providerEnvMissing: ComputedRef<boolean>
  providerEnvKey: ComputedRef<string>
  providerEnvCommand: ComputedRef<string>
  llmTimeoutSeconds: Ref<number>
}

function camel(name: string): string {
  return String(name || '').replace(/_([a-z])/g, (_, c) => c.toUpperCase())
}

export function buildProviderPayload(providerId: string, values: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = { providerId }
  Object.entries(values).forEach(([key, value]) => {
    if (value !== '' && value !== undefined) payload[camel(key)] = value
  })
  return payload
}

export function hasEffectiveProvider(config: ProviderConfig, status: SetupStatus): boolean {
  if (!config.provider) return false
  if (status.hasConfig !== false) return true
  if (status.llmConfigured === true) return true
  if (status.llmConfigured === false) return false
  return ['explicit', 'env', 'not_required'].includes(String(status.llmSource || ''))
}

export function useSetupProviderForm() {
  const providerSelected = ref('')
  const providerFieldValues = ref<Record<string, unknown>>({})
  const selectedProvider = computed(() => providerSelected.value)

  const serialized = computed(() => JSON.stringify({ p: providerSelected.value, v: providerFieldValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  function initFromConfig(config: ProviderConfig, status: SetupStatus, providers: ProviderSpec[]) {
    if (hasEffectiveProvider(config, status) && config.provider) {
      providerSelected.value = config.provider
      const spec = providers.find(p => p.providerId === config.provider)
      spec?.fields?.forEach(field => {
        // Secrets are write-only: config.get returns the literal "[redacted]",
        // which must never be seeded into the form or echoed back on save.
        if (field.secret || field.type === 'password') return
        const value = config[field.name]
        if (value !== undefined) providerFieldValues.value[field.name] = value
      })
    }
    baseline.value = serialized.value
  }

  function resetForProvider(spec: { fields?: ProviderField[] } | null | undefined) {
    providerFieldValues.value = {}
    spec?.fields?.forEach(field => {
      providerFieldValues.value[field.name] = field.default ?? ''
    })
  }

  function fieldValue(field: ProviderField, current: ProviderConfig): string {
    const name = field.name
    if (providerFieldValues.value[name] !== undefined) {
      return String(providerFieldValues.value[name] || '')
    }
    if (name === 'model') return String(current.model || field.default || '')
    if (name === 'base_url') return String(current.base_url || field.default || '')
    if (name === 'proxy') return String(current.proxy || '')
    if (name === 'api_key_env') return String(current.api_key_env || (current.api_key ? '' : field.default || ''))
    return ''
  }

  function isNonEmpty(value: unknown): boolean {
    return typeof value === 'string' ? value.trim() !== '' : value !== undefined && value !== null && value !== ''
  }

  function updateField(name: string, value: unknown) {
    providerFieldValues.value[name] = value
    // api_key (pasted) and api_key_env (env reference) are mutually exclusive:
    // the gateway rejects a save that carries both. Setting one to a non-empty
    // value clears the other in the form so the two can never be submitted
    // together (the env field is often pre-filled from a detected variable).
    if (isNonEmpty(value)) {
      if (name === 'api_key') providerFieldValues.value.api_key_env = ''
      else if (name === 'api_key_env') providerFieldValues.value.api_key = ''
    }
  }

  function selectProvider(value: string) {
    providerSelected.value = value
  }

  function payload(): Record<string, unknown> {
    // Hard guard (independent of UI state): never submit both a pasted key and
    // an env reference. A non-empty pasted api_key wins; otherwise the env
    // reference is used. buildProviderPayload drops empty values.
    const values: Record<string, unknown> = { ...providerFieldValues.value }
    if (isNonEmpty(values.api_key)) {
      delete values.api_key_env // a real pasted key wins
    } else {
      delete values.api_key // blank/whitespace paste is not a credential, keep env reference
    }
    return buildProviderPayload(providerSelected.value, values)
  }

  function createPanel(context: ProviderPanelContext) {
    return computed(() => ({
      providerSummary: context.providerSummary.value,
      providerSelected: providerSelected.value,
      runtimeProviders: context.runtimeProviders.value,
      routerSupportTone: context.routerSupportTone.value,
      routerSupportText: context.routerSupportText.value,
      canConfigureRouter: context.canConfigureRouter.value,
      providerNeeds: context.providerNeeds.value,
      providerCoreFields: context.providerCoreFields.value,
      providerAdvancedFields: context.providerAdvancedFields.value,
      providerAdvancedOpen: context.providerAdvancedOpen.value,
      providerEnvMissing: context.providerEnvMissing.value,
      providerEnvKey: context.providerEnvKey.value,
      providerEnvCommand: context.providerEnvCommand.value,
      llmTimeoutSeconds: context.llmTimeoutSeconds.value,
      providerFieldValue: (field: ProviderField) => fieldValue(field, context.currentConfig.value),
    }))
  }

  return {
    selectedProvider,
    isDirty,
    initFromConfig,
    resetForProvider,
    fieldValue,
    selectProvider,
    updateField,
    payload,
    createPanel,
  }
}
