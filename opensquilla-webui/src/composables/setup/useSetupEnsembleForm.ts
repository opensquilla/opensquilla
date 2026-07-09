import { computed, ref, type ComputedRef } from 'vue'

// Settings form for the [llm_ensemble] routing surface, saved through
// onboarding.ensemble.configure. That RPC has partial-payload semantics (the
// gateway merges over the current section), so this form tracks dirtiness PER
// KEY and payload() only carries the keys the user actually changed — an
// enabled-only save can never clobber an operator's other customizations.

export const ENSEMBLE_SELECTION_MODES = [
  'static_openrouter_b5',
  'static_tokenrhythm_b5',
  'router_dynamic',
] as const
export const ENSEMBLE_ALL_FAILED_POLICIES = ['fallback_single', 'error'] as const
export const OPENROUTER_FIXED_ENSEMBLE_PROPOSERS = [
  'deepseek/deepseek-v4-pro',
  'z-ai/glm-5.2',
  'moonshotai/kimi-k2.7-code',
  'qwen/qwen3.7-max',
] as const
export const OPENROUTER_FIXED_ENSEMBLE_AGGREGATOR = 'z-ai/glm-5.2'
export const TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS = [
  'deepseek-v4-pro',
  'glm-5.1',
  'kimi-k2.7-code',
  'qwen3.7-max',
] as const
export const TOKENRHYTHM_FIXED_ENSEMBLE_AGGREGATOR = 'glm-5.1'

// Static B5 lineups keyed by selection mode. Mirrors the gateway's
// STATIC_B5_SELECTION_MODE_PROVIDERS + provider.ensemble.STATIC_B5_PROFILES.
export interface StaticB5Profile {
  provider: string
  label: string
  proposers: readonly string[]
  aggregator: string
}

export const STATIC_B5_PROFILES: Record<string, StaticB5Profile> = {
  static_openrouter_b5: {
    provider: 'openrouter',
    label: 'OpenRouter',
    proposers: OPENROUTER_FIXED_ENSEMBLE_PROPOSERS,
    aggregator: OPENROUTER_FIXED_ENSEMBLE_AGGREGATOR,
  },
  static_tokenrhythm_b5: {
    provider: 'tokenrhythm',
    label: 'TokenRhythm',
    proposers: TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS,
    aggregator: TOKENRHYTHM_FIXED_ENSEMBLE_AGGREGATOR,
  },
}

export function staticB5ModeForProvider(provider: unknown): string | null {
  const id = String(provider || '').trim().toLowerCase()
  if (!id) return null
  for (const [mode, profile] of Object.entries(STATIC_B5_PROFILES)) {
    if (profile.provider === id) return mode
  }
  return null
}
export const LEGACY_OPENROUTER_MODEL_OPTIONS = [
  'deepseek/deepseek-v4-pro',
  'z-ai/glm-5.2',
  'qwen/qwen3.7-plus',
  'deepseek/deepseek-v4-flash',
  'qwen/qwen3.7-max',
  'moonshotai/kimi-k2.6',
  'moonshotai/kimi-k2.7-code',
  'minimax/minimax-m3',
] as const

const DEFAULT_SELECTION_MODE = 'static_openrouter_b5'
const DEFAULT_MIN_SUCCESSFUL_PROPOSERS = 1
const DEFAULT_ALL_FAILED_POLICY = 'fallback_single'

export type EnsembleCandidateSource = 'tier' | 'custom' | 'legacy_model_options' | 'openrouter_fixed'

export interface EnsembleCandidateConfig {
  provider: string
  model: string
  source?: 'custom' | 'legacy_model_options'
  enabled?: boolean
}

export interface EnsembleCredentialStatus {
  provider: string
  available: boolean
  source: 'explicit' | 'env' | 'missing_env' | 'not_required' | 'none' | string
  envKey?: string
}

export interface EnsembleCandidateView {
  key: string
  provider: string
  model: string
  source: EnsembleCandidateSource
  enabled: boolean
  credential?: EnsembleCredentialStatus
}

export interface EnsembleFixedOpenRouterProfile {
  providerLabel: string
  proposers: EnsembleCandidateView[]
  aggregator: EnsembleCandidateView
  credential?: EnsembleCredentialStatus
}

export interface EnsembleConfigSlice {
  enabled?: boolean
  selection_mode?: string
  model_options?: string[]
  candidates?: EnsembleCandidateConfig[]
  min_successful_proposers?: number
  all_failed_policy?: string
}

interface EnsemblePanelContext {
  statusText: ComputedRef<string>
  activeProvider: ComputedRef<string>
  tierCandidates?: ComputedRef<Array<{ provider: string; model: string }>>
  credentialStatus?: ComputedRef<EnsembleCredentialStatus[]>
}

function normalizeSelectionMode(value: unknown): string {
  const raw = String(value || '').trim()
  return (ENSEMBLE_SELECTION_MODES as readonly string[]).includes(raw)
    ? raw
    : DEFAULT_SELECTION_MODE
}

function normalizeAllFailedPolicy(value: unknown): string {
  const raw = String(value || '').trim()
  return (ENSEMBLE_ALL_FAILED_POLICIES as readonly string[]).includes(raw)
    ? raw
    : DEFAULT_ALL_FAILED_POLICY
}

function normalizeMinSuccessful(value: unknown): number {
  const num = Math.trunc(Number(value))
  return Number.isFinite(num) && num >= 1 ? num : DEFAULT_MIN_SUCCESSFUL_PROPOSERS
}

function normalizeModelOptions(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const entry of value) {
    const id = String(entry || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push(id)
  }
  return out
}

function normalizeProvider(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function normalizeModel(value: unknown): string {
  return String(value || '').trim()
}

function normalizeCandidateSource(value: unknown): 'custom' | 'legacy_model_options' {
  return value === 'legacy_model_options' ? 'legacy_model_options' : 'custom'
}

function normalizeCandidates(value: unknown): EnsembleCandidateConfig[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  const out: EnsembleCandidateConfig[] = []
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') continue
    const raw = entry as Record<string, unknown>
    const provider = normalizeProvider(raw.provider)
    const model = normalizeModel(raw.model)
    if (!provider || !model) continue
    const source = normalizeCandidateSource(raw.source)
    const key = `${provider}\n${model}\n${source}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      provider,
      model,
      source,
      enabled: raw.enabled === false ? false : true,
    })
  }
  return out
}

function legacyDefaultModelOptions(options: readonly string[]): boolean {
  if (options.length !== LEGACY_OPENROUTER_MODEL_OPTIONS.length) return false
  return options.every((option, index) => option === LEGACY_OPENROUTER_MODEL_OPTIONS[index])
}

function customEnsembleSeedConfigs(staticMode: string): EnsembleCandidateConfig[] {
  // OpenRouter keeps the historical candidate template; other static
  // profiles seed from their own B5 lineup (proposers + aggregator, deduped
  // by normalizeCandidates).
  if (staticMode === 'static_openrouter_b5') {
    return LEGACY_OPENROUTER_MODEL_OPTIONS.map(model => ({
      provider: 'openrouter',
      model,
      source: 'custom',
      enabled: true,
    }))
  }
  const profile = STATIC_B5_PROFILES[staticMode]
  if (!profile) return []
  return normalizeCandidates([...profile.proposers, profile.aggregator].map(model => ({
    provider: profile.provider,
    model,
    source: 'custom',
    enabled: true,
  })))
}

function candidateKey(candidate: { provider: string; model: string; source: string }): string {
  return `${candidate.source}:${candidate.provider}:${candidate.model}`
}

function credentialFor(provider: string, statuses: readonly EnsembleCredentialStatus[]): EnsembleCredentialStatus | undefined {
  const id = normalizeProvider(provider)
  return statuses.find(status => normalizeProvider(status.provider) === id)
}

function withCredential(
  provider: string,
  model: string,
  source: EnsembleCandidateSource,
  status: readonly EnsembleCredentialStatus[],
  enabled = true,
): EnsembleCandidateView {
  const normalizedProvider = normalizeProvider(provider)
  const cleanModel = normalizeModel(model)
  return {
    key: candidateKey({ provider: normalizedProvider, model: cleanModel, source }),
    provider: normalizedProvider,
    model: cleanModel,
    source,
    enabled,
    credential: credentialFor(normalizedProvider, status),
  }
}

function uniqueCandidateViews(candidates: EnsembleCandidateView[]): EnsembleCandidateView[] {
  const seen = new Set<string>()
  const out: EnsembleCandidateView[] = []
  for (const candidate of candidates) {
    const key = `${candidate.provider}\n${candidate.model}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(candidate)
  }
  return out
}

export function useSetupEnsembleForm() {
  const enabled = ref(false)
  const selectionMode = ref(DEFAULT_SELECTION_MODE)
  const modelOptions = ref<string[]>([])
  const candidates = ref<EnsembleCandidateConfig[]>([])
  const minSuccessfulProposers = ref(DEFAULT_MIN_SUCCESSFUL_PROPOSERS)
  const allFailedPolicy = ref(DEFAULT_ALL_FAILED_POLICY)

  // Per-key baselines: partial payloads need to know WHICH keys changed, not
  // just that something did. Seeded from the initial state so the pristine
  // form is never dirty while config loads.
  const baseline = ref({
    enabled: enabled.value,
    selectionMode: selectionMode.value,
    modelOptions: JSON.stringify(modelOptions.value),
    candidates: JSON.stringify(candidates.value),
    minSuccessfulProposers: minSuccessfulProposers.value,
    allFailedPolicy: allFailedPolicy.value,
  })

  const enabledDirty = computed(() => enabled.value !== baseline.value.enabled)
  const selectionModeDirty = computed(() => selectionMode.value !== baseline.value.selectionMode)
  const modelOptionsDirty = computed(() => JSON.stringify(modelOptions.value) !== baseline.value.modelOptions)
  const candidatesDirty = computed(() => JSON.stringify(candidates.value) !== baseline.value.candidates)
  const dynamicCandidateInputsActive = computed(() => selectionMode.value === 'router_dynamic')
  const effectiveModelOptionsDirty = computed(() => dynamicCandidateInputsActive.value && modelOptionsDirty.value)
  const effectiveCandidatesDirty = computed(() => dynamicCandidateInputsActive.value && candidatesDirty.value)
  const minSuccessfulDirty = computed(() => minSuccessfulProposers.value !== baseline.value.minSuccessfulProposers)
  const allFailedPolicyDirty = computed(() => allFailedPolicy.value !== baseline.value.allFailedPolicy)
  const isDirty = computed(() => (
    enabledDirty.value
    || selectionModeDirty.value
    || effectiveModelOptionsDirty.value
    || effectiveCandidatesDirty.value
    || minSuccessfulDirty.value
    || allFailedPolicyDirty.value
  ))

  function snapshotBaseline() {
    baseline.value = {
      enabled: enabled.value,
      selectionMode: selectionMode.value,
      modelOptions: JSON.stringify(modelOptions.value),
      candidates: JSON.stringify(candidates.value),
      minSuccessfulProposers: minSuccessfulProposers.value,
      allFailedPolicy: allFailedPolicy.value,
    }
  }

  function initFromConfig(config: EnsembleConfigSlice) {
    enabled.value = config.enabled === true
    selectionMode.value = normalizeSelectionMode(config.selection_mode)
    modelOptions.value = normalizeModelOptions(config.model_options)
    candidates.value = normalizeCandidates(config.candidates)
    minSuccessfulProposers.value = normalizeMinSuccessful(
      config.min_successful_proposers ?? DEFAULT_MIN_SUCCESSFUL_PROPOSERS,
    )
    allFailedPolicy.value = normalizeAllFailedPolicy(config.all_failed_policy)
    snapshotBaseline()
  }

  function setEnabled(value: boolean) {
    enabled.value = Boolean(value)
  }

  function setSelectionMode(value: string) {
    selectionMode.value = normalizeSelectionMode(value)
  }

  function addModelOption(value: string) {
    const id = String(value || '').trim()
    if (!id || modelOptions.value.includes(id)) return
    modelOptions.value = [...modelOptions.value, id]
  }

  function removeModelOption(value: string) {
    modelOptions.value = modelOptions.value.filter(option => option !== value)
  }

  function addCandidate(provider: string, model: string) {
    const cleanProvider = normalizeProvider(provider)
    const cleanModel = normalizeModel(model)
    if (!cleanProvider || !cleanModel) return
    const next = normalizeCandidates([
      ...candidates.value,
      { provider: cleanProvider, model: cleanModel, source: 'custom', enabled: true },
    ])
    candidates.value = next
  }

  function removeCandidate(candidate: { provider: string; model: string; source?: string }) {
    const provider = normalizeProvider(candidate.provider)
    const model = normalizeModel(candidate.model)
    const source = normalizeCandidateSource(candidate.source)
    if (source === 'legacy_model_options') {
      removeModelOption(model)
      return
    }
    candidates.value = candidates.value.filter(entry => !(
      normalizeProvider(entry.provider) === provider
      && normalizeModel(entry.model) === model
      && normalizeCandidateSource(entry.source) === source
    ))
  }

  function resetModelOptions() {
    modelOptions.value = []
    candidates.value = []
  }

  function restoreBaselineCandidateInputs() {
    try {
      modelOptions.value = JSON.parse(baseline.value.modelOptions) as string[]
    } catch {
      modelOptions.value = []
    }
    try {
      candidates.value = JSON.parse(baseline.value.candidates) as EnsembleCandidateConfig[]
    } catch {
      candidates.value = []
    }
  }

  function setOpenRouterCustomEnsemble(value: boolean, staticMode = 'static_openrouter_b5') {
    const mode = staticMode in STATIC_B5_PROFILES ? staticMode : 'static_openrouter_b5'
    if (value) {
      selectionMode.value = 'router_dynamic'
      modelOptions.value = []
      candidates.value = customEnsembleSeedConfigs(mode)
      return
    }
    selectionMode.value = mode
    restoreBaselineCandidateInputs()
  }

  function setMinSuccessfulProposers(value: number) {
    minSuccessfulProposers.value = normalizeMinSuccessful(value)
  }

  function setAllFailedPolicy(value: string) {
    allFailedPolicy.value = normalizeAllFailedPolicy(value)
  }

  // Partial by design: only user-changed keys are sent; the gateway keeps the
  // current value for every omitted key.
  function payload(): Record<string, unknown> {
    const params: Record<string, unknown> = {}
    if (enabledDirty.value) params.enabled = enabled.value
    if (selectionModeDirty.value) params.selectionMode = selectionMode.value
    if (effectiveModelOptionsDirty.value) params.modelOptions = [...modelOptions.value]
    if (effectiveCandidatesDirty.value) params.candidates = candidates.value.map(candidate => ({
      provider: candidate.provider,
      model: candidate.model,
      source: candidate.source || 'custom',
      enabled: candidate.enabled !== false,
    }))
    if (minSuccessfulDirty.value) params.minSuccessfulProposers = minSuccessfulProposers.value
    if (allFailedPolicyDirty.value) params.allFailedPolicy = allFailedPolicy.value
    return params
  }

  function createPanel(context: EnsemblePanelContext) {
    return computed(() => {
      const credentialStatus = context.credentialStatus?.value ?? []
      const activeProvider = normalizeProvider(context.activeProvider.value)
      const providerStaticMode = staticB5ModeForProvider(activeProvider)
      const openRouterCustomEnsemble = providerStaticMode !== null
        ? selectionMode.value !== providerStaticMode
        : false
      const tierCandidates = uniqueCandidateViews((context.tierCandidates?.value ?? [])
        .map(candidate => withCredential(candidate.provider, candidate.model, 'tier', credentialStatus))
        .filter(candidate => candidate.provider && candidate.model))
      const structuredCandidates = candidates.value
        .filter(candidate => candidate.enabled !== false)
        .map(candidate => withCredential(candidate.provider, candidate.model, normalizeCandidateSource(candidate.source), credentialStatus))
      const legacyCandidates = legacyDefaultModelOptions(modelOptions.value)
        ? []
        : modelOptions.value.map((model) => {
          const provider = model.includes('/') ? 'openrouter' : activeProvider
          return withCredential(provider, model, 'legacy_model_options', credentialStatus)
        })
      const customCandidates = uniqueCandidateViews([...structuredCandidates, ...legacyCandidates])
      const activeStaticProfile = (
        providerStaticMode !== null && selectionMode.value === providerStaticMode
      )
        ? STATIC_B5_PROFILES[providerStaticMode]
        : null
      const fixedOpenRouterProfile: EnsembleFixedOpenRouterProfile | null = activeStaticProfile
        ? {
            providerLabel: activeStaticProfile.label,
            proposers: activeStaticProfile.proposers.map(model => withCredential(activeStaticProfile.provider, model, 'openrouter_fixed', credentialStatus)),
            aggregator: withCredential(activeStaticProfile.provider, activeStaticProfile.aggregator, 'openrouter_fixed', credentialStatus),
            credential: credentialFor(activeStaticProfile.provider, credentialStatus),
          }
        : null

      return {
        enabled: enabled.value,
        selectionMode: selectionMode.value,
        modelOptions: [...modelOptions.value],
        candidates: candidates.value.map(candidate => ({ ...candidate })),
        tierCandidates,
        customCandidates,
        fixedOpenRouterProfile,
        showOpenRouterFixedSwitch: providerStaticMode !== null,
        openRouterCustomEnsemble,
        staticSelectionMode: providerStaticMode,
        minSuccessfulProposers: minSuccessfulProposers.value,
        allFailedPolicy: allFailedPolicy.value,
        // model_options only drives the dynamic selection; static ignores it.
        showModelOptions: selectionMode.value === 'router_dynamic' || activeStaticProfile === null,
        showCandidateEditor: selectionMode.value === 'router_dynamic' || activeStaticProfile === null,
        // A static selection routes through its profile provider regardless of
        // the primary provider — surface the credential dependency instead of
        // failing quietly.
        showOpenrouterHint: false,
        advancedOpen: (
          minSuccessfulProposers.value !== DEFAULT_MIN_SUCCESSFUL_PROPOSERS
          || allFailedPolicy.value !== DEFAULT_ALL_FAILED_POLICY
        ),
        statusText: context.statusText.value,
      }
    })
  }

  return {
    enabled,
    selectionMode,
    modelOptions,
    candidates,
    minSuccessfulProposers,
    allFailedPolicy,
    enabledDirty,
    selectionModeDirty,
    modelOptionsDirty,
    candidatesDirty,
    minSuccessfulDirty,
    allFailedPolicyDirty,
    isDirty,
    initFromConfig,
    setEnabled,
    setSelectionMode,
    addModelOption,
    removeModelOption,
    addCandidate,
    removeCandidate,
    resetModelOptions,
    setOpenRouterCustomEnsemble,
    setMinSuccessfulProposers,
    setAllFailedPolicy,
    payload,
    createPanel,
  }
}
