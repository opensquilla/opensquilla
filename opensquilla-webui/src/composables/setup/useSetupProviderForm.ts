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
}

interface ProviderPanelContext {
  currentConfig: ComputedRef<ProviderConfig>
  providerSummary: ComputedRef<string>
  runtimeProviders: ComputedRef<Array<{ providerId: string; label: string }>>
  routerSupportTone: ComputedRef<string>
  routerSupportText: ComputedRef<string>
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

export function useSetupProviderForm() {
  const providerSelected = ref('')
  const providerFieldValues = ref<Record<string, unknown>>({})
  const selectedProvider = computed(() => providerSelected.value)

  const serialized = computed(() => JSON.stringify({ p: providerSelected.value, v: providerFieldValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  function initFromConfig(config: ProviderConfig, status: SetupStatus, providers: ProviderSpec[]) {
    const hasSaved = Boolean(config.provider) && status.hasConfig !== false
    if (hasSaved && config.provider) {
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

  function updateField(name: string, value: unknown) {
    providerFieldValues.value[name] = value
  }

  function selectProvider(value: string) {
    providerSelected.value = value
  }

  function payload(): Record<string, unknown> {
    return buildProviderPayload(providerSelected.value, providerFieldValues.value)
  }

  function createPanel(context: ProviderPanelContext) {
    return computed(() => ({
      providerSummary: context.providerSummary.value,
      providerSelected: providerSelected.value,
      runtimeProviders: context.runtimeProviders.value,
      routerSupportTone: context.routerSupportTone.value,
      routerSupportText: context.routerSupportText.value,
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
