import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'

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
  providerCredentialPanel: ComputedRef<ProviderCredentialPanelState | null>
  providerAdvancedOpen: ComputedRef<boolean>
  providerEnvMissing: ComputedRef<boolean>
  providerEnvKey: ComputedRef<string>
  providerEnvCommand: ComputedRef<string>
  llmTimeoutSeconds: Ref<number>
  contextWindowTokens: Ref<string>
  contextWindowGlobal: ComputedRef<number | null>
  providerIsLocal: ComputedRef<boolean>
}

// ---------------------------------------------------------------------------
// Connection state machine (probe + model discovery)
// ---------------------------------------------------------------------------

/**
 * Lifecycle of the optional "Test connection" accelerator. Saving is NEVER
 * gated on this state — a user can save an unverified (or even failing)
 * config at any time; the machine only powers inline feedback and the
 * discovered-model combobox.
 *
 *   unconfigured -- selectProvider(id) --> unverified
 *   unverified   -- probeConnection()  --> probing
 *   probing      -- probe ok           --> verified (auto-fires discoverModels)
 *   probing      -- auth-ish failure   --> key_invalid
 *   probing      -- other failure/RPC error --> unreachable
 *   any          -- credential/provider/baseUrl/proxy edit --> unverified
 */
export type ConnectionPhase =
  | 'unconfigured'
  | 'unverified'
  | 'probing'
  | 'verified'
  | 'key_invalid'
  | 'unreachable'

export interface DiscoveredModelPricing {
  inputPer1k: number
  outputPer1k: number
}

/** One row of the onboarding.models.discover wire envelope (camelCase, frozen). */
export interface DiscoveredModel {
  id: string
  name: string
  contextWindow: number | null
  maxOutputTokens: number | null
  capabilities: string[]
  pricing: DiscoveredModelPricing | null
  capabilitySource: string
}

export interface DiscoveredModelCatalog {
  models: DiscoveredModel[]
  source: 'live' | 'none'
}

/** Provider ids are normalized before they become catalog keys. */
export type DiscoveredModelsByProvider = Record<string, DiscoveredModelCatalog>

export interface ConnectionState {
  phase: ConnectionPhase
  failureKind: string
  detail: string
  /** Round-trip time of the last probe (success or failure), null when unknown. */
  latencyMs: number | null
  models: DiscoveredModel[]
  modelSource: 'live' | 'none'
  discoverError: string
}

export interface ProviderCredentialPanelState {
  providerLabel: string
  providerSelected: boolean
  acceptsApiKey: boolean
  requiresApiKey: boolean
  source: string
  available: boolean
  envKey: string
  masked: string
  revealAllowed: boolean
  revealed: string
  revealError: string
  replacing: boolean
  apiKeyValue: string
  apiKeyEnvValue: string
  probeReady: boolean
  probeDisabledReason: string
  connection: ConnectionState
  onReveal?: () => void
  onReplace?: () => void
  onCancelReplace?: () => void
}

// Probe failure kinds that mean "the credential itself was rejected" (vs. the
// endpoint being unreachable/unhappy). Kept to the unambiguous case: other
// kinds (rate limits, credits, overload) get their own human sentence under
// the generic "couldn't connect" headline.
const AUTH_FAILURE_KINDS = new Set(['auth_invalid'])

// Editing any of these form fields changes what a probe would test, so a
// previously earned verdict no longer applies. (Model is deliberately absent:
// the connection verdict is about credentials + endpoint, not the model id.)
const CONNECTION_FIELDS = new Set(['api_key', 'api_key_env', 'base_url', 'proxy'])

export const PROVIDER_CREDENTIAL_REVEAL_TIMEOUT_MS = 30_000

function freshConnection(providerId: string): ConnectionState {
  return {
    phase: providerId ? 'unverified' : 'unconfigured',
    failureKind: '',
    detail: '',
    latencyMs: null,
    models: [],
    modelSource: 'none',
    discoverError: '',
  }
}

function normalizeLatencyMs(value: unknown): number | null {
  // The gateway sends latencyMs=0 as the "never reached the network" sentinel
  // (missing key / build failure), so a zero is not a real round trip — treat
  // it as unknown rather than rendering a bogus "· 0ms".
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

export function normalizeDiscoveredModels(rows: unknown): DiscoveredModel[] {
  if (!Array.isArray(rows)) return []
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    .map(row => {
      const pricing = row.pricing
      return {
        id: String(row.id ?? ''),
        name: String(row.name ?? row.id ?? ''),
        contextWindow: typeof row.contextWindow === 'number' ? row.contextWindow : null,
        maxOutputTokens: typeof row.maxOutputTokens === 'number' ? row.maxOutputTokens : null,
        capabilities: Array.isArray(row.capabilities) ? row.capabilities.map(String) : [],
        pricing: pricing && typeof pricing === 'object'
          ? {
              inputPer1k: Number((pricing as Record<string, unknown>).inputPer1k ?? 0),
              outputPer1k: Number((pricing as Record<string, unknown>).outputPer1k ?? 0),
            }
          : null,
        capabilitySource: String(row.capabilitySource ?? ''),
      }
    })
    .filter(model => model.id)
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
  const replacingCredential = ref(false)
  const revealedCredential = ref('')
  const revealError = ref('')
  const selectedProvider = computed(() => providerSelected.value)
  let revealTimer: ReturnType<typeof setTimeout> | null = null

  const serialized = computed(() => JSON.stringify({ p: providerSelected.value, v: providerFieldValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  // -------------------------------------------------------------------------
  // Connection state machine
  // -------------------------------------------------------------------------

  const connection = ref<ConnectionState>(freshConnection(''))
  // Monotonic token: bumped by every reset and probe start so an in-flight
  // RPC result that raced a credential edit is discarded instead of applied.
  let connectionEpoch = 0
  let discoverPromise: Promise<void> | null = null

  function resetConnection() {
    connectionEpoch += 1
    discoverPromise = null
    connection.value = freshConnection(providerSelected.value)
  }

  function clearRevealTimer() {
    if (revealTimer) {
      clearTimeout(revealTimer)
      revealTimer = null
    }
  }

  function clearRevealedCredential() {
    clearRevealTimer()
    revealedCredential.value = ''
  }

  function resetCredentialUiState() {
    clearRevealTimer()
    replacingCredential.value = false
    revealedCredential.value = ''
    revealError.value = ''
  }

  // Params for probe/discover: the CURRENT form values, including an unsaved
  // pasted key — this is what makes "test before save" possible. Empty values
  // are dropped (the gateway falls back to the stored config / spec env key).
  function connectionParams(defaultModel = ''): Record<string, unknown> {
    const p = payload()
    const params: Record<string, unknown> = { providerId: providerSelected.value }
    for (const key of ['apiKey', 'apiKeyEnv', 'baseUrl', 'proxy'] as const) {
      if (p[key] !== undefined) params[key] = p[key]
    }
    const model = String(p.model ?? '').trim() || String(defaultModel || '').trim()
    if (model) params.model = model
    return params
  }

  async function probeConnection(options: { defaultModel?: string } = {}): Promise<void> {
    if (!providerSelected.value || connection.value.phase === 'probing') return
    const epoch = ++connectionEpoch
    discoverPromise = null
    connection.value = { ...freshConnection(providerSelected.value), phase: 'probing' }
    const rpc = useRpcStore()
    let outcome: ConnectionState
    try {
      const res = await rpc.call<{ ok?: boolean; failureKind?: string; message?: string; latencyMs?: number }>(
        'onboarding.provider.probe',
        connectionParams(options.defaultModel),
      )
      if (epoch !== connectionEpoch) return
      const latencyMs = normalizeLatencyMs(res?.latencyMs)
      if (res?.ok) {
        outcome = { ...freshConnection(providerSelected.value), phase: 'verified', latencyMs }
      } else {
        const kind = String(res?.failureKind || '')
        outcome = {
          ...freshConnection(providerSelected.value),
          phase: AUTH_FAILURE_KINDS.has(kind) ? 'key_invalid' : 'unreachable',
          failureKind: kind,
          detail: String(res?.message || ''),
          latencyMs,
        }
      }
    } catch (err) {
      if (epoch !== connectionEpoch) return
      outcome = {
        ...freshConnection(providerSelected.value),
        phase: 'unreachable',
        detail: err instanceof Error ? err.message : String(err),
      }
    }
    connection.value = outcome
    if (outcome.phase === 'verified') {
      // Verified endpoint: immediately offer discovered models. The combined
      // verified+models state is kept live only; every explicit test click
      // re-probes so a newly issued key or recovered provider is not masked by
      // a stale verdict.
      await discoverModels()
    }
  }

  function discoverModels(): Promise<void> {
    if (!providerSelected.value) return Promise.resolve()
    if (discoverPromise) return discoverPromise
    const epoch = connectionEpoch
    const rpc = useRpcStore()
    const request = (async () => {
      try {
        const res = await rpc.call<{
          ok?: boolean
          failureKind?: string
          detail?: string
          source?: string
          models?: unknown
        }>('onboarding.models.discover', connectionParams())
        if (epoch !== connectionEpoch) return
        if (res?.ok) {
          const modelSource = res.source === 'live' ? 'live' : 'none'
          connection.value = {
            ...connection.value,
            models: modelSource === 'live' ? normalizeDiscoveredModels(res.models) : [],
            modelSource,
            discoverError: '',
          }
        } else {
          connection.value = {
            ...connection.value,
            models: [],
            modelSource: 'none',
            discoverError: String(res?.detail || res?.failureKind || 'discover failed'),
          }
        }
      } catch (err) {
        if (epoch !== connectionEpoch) return
        connection.value = {
          ...connection.value,
          models: [],
          modelSource: 'none',
          discoverError: err instanceof Error ? err.message : String(err),
        }
      }
    })()
    const tracked = request.finally(() => {
      if (discoverPromise === tracked) {
        discoverPromise = null
      }
    })
    discoverPromise = tracked
    return tracked
  }

  function initFromConfig(config: ProviderConfig, status: SetupStatus, providers: ProviderSpec[]) {
    resetCredentialUiState()
    providerSelected.value = ''
    providerFieldValues.value = {}
    if (hasEffectiveProvider(config, status) && config.provider) {
      providerSelected.value = config.provider
      const spec = providers.find(p => p.providerId === config.provider)
      spec?.fields?.forEach(field => {
        // Secrets are write-only: config.get returns the literal "[redacted]",
        // which must never be seeded into the form or echoed back on save.
        if (field.secret || field.type === 'password') return
        if (field.name === 'api_key_env') return
        const value = config[field.name]
        if (value !== undefined) providerFieldValues.value[field.name] = value
      })
    }
    baseline.value = serialized.value
    resetConnection()
  }

  function resetForProvider(spec: { fields?: ProviderField[] } | null | undefined) {
    resetCredentialUiState()
    providerFieldValues.value = {}
    spec?.fields?.forEach(field => {
      if (field.name === 'api_key_env') return
      providerFieldValues.value[field.name] = field.default ?? ''
    })
    resetConnection()
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
    if (name === 'api_key' || name === 'api_key_env') {
      clearRevealedCredential()
      revealError.value = ''
    }
    // A credential/endpoint edit invalidates any earned connection verdict
    // (model edits deliberately don't — the verdict is about reachability).
    if (CONNECTION_FIELDS.has(name)) resetConnection()
  }

  function startCredentialReplace() {
    replacingCredential.value = true
    clearRevealedCredential()
    revealError.value = ''
  }

  function cancelCredentialReplace() {
    replacingCredential.value = false
    providerFieldValues.value.api_key = ''
    clearRevealedCredential()
    revealError.value = ''
  }

  function setRevealedCredential(value: string) {
    clearRevealTimer()
    revealedCredential.value = value
    revealError.value = ''
    if (value) {
      revealTimer = setTimeout(() => {
        revealedCredential.value = ''
        revealTimer = null
      }, PROVIDER_CREDENTIAL_REVEAL_TIMEOUT_MS)
    }
  }

  function setRevealError(value: string) {
    clearRevealedCredential()
    revealError.value = value
  }

  function selectProvider(value: string) {
    providerSelected.value = value
    resetCredentialUiState()
    resetConnection()
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
      if (!isNonEmpty(values.api_key_env)) delete values.api_key_env
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
      credentialPanel: context.providerCredentialPanel.value,
      providerAdvancedOpen: context.providerAdvancedOpen.value,
      providerEnvMissing: context.providerEnvMissing.value,
      providerEnvKey: context.providerEnvKey.value,
      providerEnvCommand: context.providerEnvCommand.value,
      llmTimeoutSeconds: context.llmTimeoutSeconds.value,
      contextWindowTokens: context.contextWindowTokens.value,
      contextWindowGlobal: context.contextWindowGlobal.value,
      providerIsLocal: context.providerIsLocal.value,
      connection: connection.value,
      providerFieldValue: (field: ProviderField) => fieldValue(field, context.currentConfig.value),
    }))
  }

  return {
    selectedProvider,
    isDirty,
    connection,
    providerFieldValues,
    replacingCredential,
    revealedCredential,
    revealError,
    initFromConfig,
    resetForProvider,
    fieldValue,
    selectProvider,
    updateField,
    startCredentialReplace,
    cancelCredentialReplace,
    setRevealedCredential,
    setRevealError,
    payload,
    probeConnection,
    discoverModels,
    createPanel,
  }
}
