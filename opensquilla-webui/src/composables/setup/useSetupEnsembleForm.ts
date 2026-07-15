import { computed, ref, type ComputedRef } from 'vue'

// Settings form for the [llm_ensemble] routing surface, saved through
// onboarding.ensemble.configure. That RPC has partial-payload semantics (the
// gateway merges over the current section), so this form tracks dirtiness PER
// KEY and payload() only carries the keys the user actually changed — an
// enabled-only save can never clobber an operator's other customizations.
//
// The UI exposes exactly two schemes:
// - "preset": the provider's fixed B5 lineup (OpenRouter / TokenRhythm only).
// - "custom": an explicit user-authored lineup saved as selection_mode
//   "custom_b5" (roles per candidate, single aggregator).
// The legacy "router_dynamic" mode is read-compatible but hidden: stored
// configs surface a migration banner that converts them to a custom lineup.

export const CUSTOM_B5_SELECTION_MODE = 'custom_b5'

export const ENSEMBLE_SELECTION_MODES = [
  'static_openrouter_b5',
  'static_tokenrhythm_b5',
  CUSTOM_B5_SELECTION_MODE,
  'router_dynamic',
] as const
export const ENSEMBLE_ALL_FAILED_POLICIES = ['fallback_single', 'error'] as const

export type EnsembleCandidateRole =
  | ''
  | 'primary'
  | 'contrast'
  | 'fast_check'
  | 'critic'
  | 'aggregator'

export const ENSEMBLE_PROPOSER_ROLES = ['primary', 'contrast', 'fast_check', 'critic'] as const

// Custom lineup bounds. Mirrors the gateway's CUSTOM_B5_* constants: 2 is the
// smallest lineup where fusion means anything, 3-4 is the value sweet spot
// (the preset lineups run 4), 6 is the hard ceiling before aggregator-context
// and cost pressure outweigh the marginal draft.
export const CUSTOM_B5_MIN_PROPOSERS = 2
export const CUSTOM_B5_MAX_PROPOSERS = 6
export const CUSTOM_B5_RECOMMENDED_MIN = 3
export const CUSTOM_B5_RECOMMENDED_MAX = 4

export const OPENROUTER_FIXED_ENSEMBLE_PROPOSERS = [
  'deepseek/deepseek-v4-pro',
  'z-ai/glm-5.2',
  'moonshotai/kimi-k2.7-code',
  'qwen/qwen3.7-max',
] as const
export const OPENROUTER_FIXED_ENSEMBLE_AGGREGATOR = 'z-ai/glm-5.2'
export const TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS = [
  'deepseek-v4-pro',
  'glm-5.2',
  'kimi-k2.7-code',
  'qwen3.7-max',
] as const
export const TOKENRHYTHM_FIXED_ENSEMBLE_AGGREGATOR = 'glm-5.2'

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

// Runtime default replacements applied by the ensemble builder when the
// stored value still equals the legacy default. The panel surfaces EFFECTIVE
// values so what the user reads matches what actually runs.
const STATIC_B5_EFFECTIVE_QUORUM = 3
const STATIC_B5_PROPOSER_TIMEOUT_SECONDS = 300
const STATIC_B5_AGGREGATOR_TIMEOUT_SECONDS = 480
const STATIC_B5_QUORUM_GRACE_SECONDS = 30

export type EnsembleScheme = 'preset' | 'custom' | 'legacy'

export type EnsembleCandidateSource = 'tier' | 'custom' | 'legacy_model_options' | 'openrouter_fixed'

export interface EnsembleCandidateConfig {
  provider: string
  model: string
  source?: 'custom' | 'legacy_model_options'
  enabled?: boolean
  role?: EnsembleCandidateRole
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
  role: EnsembleCandidateRole
  credential?: EnsembleCredentialStatus
}

export interface EnsembleFixedProfileView {
  providerLabel: string
  proposers: EnsembleCandidateView[]
  aggregator: EnsembleCandidateView
  credential?: EnsembleCredentialStatus
}

export interface EnsembleEffectiveFacts {
  perTurnCalls: number
  quorum: number
  proposerCount: number
  proposerTimeoutSeconds: number
  aggregatorTimeoutSeconds: number
  quorumGraceSeconds: number
}

export type EnsembleCapacityState = 'ok' | 'warn' | 'full'

export interface EnsembleCustomLineupView {
  aggregator: EnsembleCandidateView | null
  aggregatorInherited: boolean
  inheritedAggregatorProvider: string
  inheritedAggregatorModel: string
  proposers: EnsembleCandidateView[]
  proposerCount: number
  minProposers: number
  maxProposers: number
  recommendedMin: number
  recommendedMax: number
  capacity: EnsembleCapacityState
  canAddProposer: boolean
  belowMinimum: boolean
  diversityWarning: boolean
  facts: EnsembleEffectiveFacts
}

export interface EnsembleConfigSlice {
  enabled?: boolean
  selection_mode?: string
  model_options?: string[]
  candidates?: EnsembleCandidateConfig[]
  min_successful_proposers?: number
  all_failed_policy?: string
}

interface EnsembleTierCandidate {
  provider: string
  model: string
  tier?: string
}

interface EnsemblePanelContext {
  statusText: ComputedRef<string>
  activeProvider: ComputedRef<string>
  activeModel?: ComputedRef<string>
  tierCandidates?: ComputedRef<EnsembleTierCandidate[]>
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

export function normalizeCandidateRole(value: unknown): EnsembleCandidateRole {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'aggregator') return 'aggregator'
  return (ENSEMBLE_PROPOSER_ROLES as readonly string[]).includes(raw)
    ? raw as EnsembleCandidateRole
    : ''
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
    const role = normalizeCandidateRole(raw.role)
    // The aggregator row may legitimately duplicate a proposer row (the same
    // model can both draft and fuse), so the identity includes the
    // aggregator/proposer distinction.
    const key = `${provider}\n${model}\n${source}\n${role === 'aggregator' ? 'aggregator' : 'proposer'}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      provider,
      model,
      source,
      enabled: raw.enabled === false ? false : true,
      role,
    })
  }
  return out
}

function legacyDefaultModelOptions(options: readonly string[]): boolean {
  if (options.length !== LEGACY_OPENROUTER_MODEL_OPTIONS.length) return false
  return options.every((option, index) => option === LEGACY_OPENROUTER_MODEL_OPTIONS[index])
}

// Seed roles for lineup rows in display order (advisory labels only).
function seedRoleForIndex(index: number): EnsembleCandidateRole {
  return (ENSEMBLE_PROPOSER_ROLES[index] ?? '') as EnsembleCandidateRole
}

export function roleForTier(tier: unknown): EnsembleCandidateRole {
  const raw = String(tier || '').trim().toLowerCase()
  if (raw === 'c0' || raw === 'c1' || raw === 't0' || raw === 't1') return 'fast_check'
  if (raw === 'c2' || raw === 't2') return 'contrast'
  if (raw === 'c3' || raw === 't3') return 'critic'
  return ''
}

// Model-family key used for the diversity hint; mirrors the backend's model
// identity split (vendor prefix stripped, first two hyphen tokens).
export function modelFamilyKey(model: string): string {
  const bare = String(model || '').trim().toLowerCase()
  const name = bare.includes('/') ? bare.split('/').slice(1).join('/') : bare
  const pieces = name.replace(/_/g, '-').split('-')
  return pieces.length >= 2 ? pieces.slice(0, 2).join('-') : (name || 'unknown')
}

function customSeedFromProfile(profile: StaticB5Profile): EnsembleCandidateConfig[] {
  const rows: EnsembleCandidateConfig[] = profile.proposers.map((model, index) => ({
    provider: profile.provider,
    model,
    source: 'custom',
    enabled: true,
    role: seedRoleForIndex(index),
  }))
  rows.push({
    provider: profile.provider,
    model: profile.aggregator,
    source: 'custom',
    enabled: true,
    role: 'aggregator',
  })
  return normalizeCandidates(rows)
}

function candidateKey(candidate: { provider: string; model: string; source: string; role?: string }): string {
  const slot = candidate.role === 'aggregator' ? 'aggregator' : 'proposer'
  return `${candidate.source}:${slot}:${candidate.provider}:${candidate.model}`
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
  role: EnsembleCandidateRole = '',
): EnsembleCandidateView {
  const normalizedProvider = normalizeProvider(provider)
  const cleanModel = normalizeModel(model)
  return {
    key: candidateKey({ provider: normalizedProvider, model: cleanModel, source, role }),
    provider: normalizedProvider,
    model: cleanModel,
    source,
    enabled,
    role,
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
  // Candidate/model-option inputs only drive the lineup-based modes; static
  // preset saves must not carry stale editor state.
  const dynamicCandidateInputsActive = computed(() => (
    selectionMode.value === 'router_dynamic' || selectionMode.value === CUSTOM_B5_SELECTION_MODE
  ))
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

  const enabledProposerConfigs = computed(() => candidates.value.filter(candidate => (
    candidate.enabled !== false && normalizeCandidateRole(candidate.role) !== 'aggregator'
  )))

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

  // Lineup edits pin the mode to custom_b5 when a static preset is stored:
  // editing candidates under a preset used to leave the pool ineffective at
  // runtime — the root cause of the "edited pool, preset still runs" trap.
  // A stored legacy router_dynamic mode is left alone (its pool IS read at
  // runtime); the migration banner is the explicit conversion path.
  function ensureCustomMode() {
    if (
      selectionMode.value !== CUSTOM_B5_SELECTION_MODE
      && selectionMode.value !== 'router_dynamic'
    ) {
      selectionMode.value = CUSTOM_B5_SELECTION_MODE
    }
  }

  // Keep an explicit quorum consistent with the lineup: quorum > N can never
  // succeed and the gateway rejects it. The legacy default (1) means "auto"
  // (the runtime derives N-1), so it is never clamped.
  function clampQuorumToLineup() {
    const count = enabledProposerConfigs.value.length
    if (
      minSuccessfulProposers.value > 1
      && count >= 1
      && minSuccessfulProposers.value > count
    ) {
      minSuccessfulProposers.value = count
    }
  }

  function addCandidate(provider: string, model: string, role: EnsembleCandidateRole = '') {
    const cleanProvider = normalizeProvider(provider)
    const cleanModel = normalizeModel(model)
    if (!cleanProvider || !cleanModel) return
    const cleanRole = normalizeCandidateRole(role)
    if (
      cleanRole !== 'aggregator'
      && enabledProposerConfigs.value.length >= CUSTOM_B5_MAX_PROPOSERS
    ) return
    ensureCustomMode()
    let next = [
      ...candidates.value,
      { provider: cleanProvider, model: cleanModel, source: 'custom' as const, enabled: true, role: cleanRole },
    ]
    if (cleanRole === 'aggregator') {
      next = next.map((candidate, index) => (
        index < next.length - 1 && normalizeCandidateRole(candidate.role) === 'aggregator'
          ? { ...candidate, role: '' as EnsembleCandidateRole }
          : candidate
      ))
    }
    candidates.value = normalizeCandidates(next)
  }

  function removeCandidate(candidate: { provider: string; model: string; source?: string; role?: string }) {
    const provider = normalizeProvider(candidate.provider)
    const model = normalizeModel(candidate.model)
    const source = normalizeCandidateSource(candidate.source)
    const slot = normalizeCandidateRole(candidate.role) === 'aggregator' ? 'aggregator' : 'proposer'
    ensureCustomMode()
    if (source === 'legacy_model_options') {
      removeModelOption(model)
      clampQuorumToLineup()
      return
    }
    candidates.value = candidates.value.filter(entry => !(
      normalizeProvider(entry.provider) === provider
      && normalizeModel(entry.model) === model
      && normalizeCandidateSource(entry.source) === source
      && (normalizeCandidateRole(entry.role) === 'aggregator' ? 'aggregator' : 'proposer') === slot
    ))
    clampQuorumToLineup()
  }

  function setCandidateRole(
    candidate: { provider: string; model: string; source?: string; role?: string },
    role: EnsembleCandidateRole,
  ) {
    const provider = normalizeProvider(candidate.provider)
    const model = normalizeModel(candidate.model)
    const source = normalizeCandidateSource(candidate.source)
    const currentSlot = normalizeCandidateRole(candidate.role) === 'aggregator' ? 'aggregator' : 'proposer'
    const nextRole = normalizeCandidateRole(role)
    ensureCustomMode()
    const next = candidates.value.map((entry) => {
      const matches = (
        normalizeProvider(entry.provider) === provider
        && normalizeModel(entry.model) === model
        && normalizeCandidateSource(entry.source) === source
        && (normalizeCandidateRole(entry.role) === 'aggregator' ? 'aggregator' : 'proposer') === currentSlot
      )
      if (matches) return { ...entry, role: nextRole }
      // The aggregator is structurally single: promoting a row demotes any
      // previous aggregator to an unassigned proposer.
      if (nextRole === 'aggregator' && normalizeCandidateRole(entry.role) === 'aggregator') {
        return { ...entry, role: '' as EnsembleCandidateRole }
      }
      return entry
    })
    candidates.value = normalizeCandidates(next)
    clampQuorumToLineup()
  }

  function importTierCandidates(tierCandidates: readonly EnsembleTierCandidate[]) {
    ensureCustomMode()
    const existing = new Set(
      enabledProposerConfigs.value.map(entry => `${entry.provider}\n${entry.model}`),
    )
    let added = candidates.value.slice()
    let count = enabledProposerConfigs.value.length
    for (const row of tierCandidates || []) {
      if (count >= CUSTOM_B5_MAX_PROPOSERS) break
      const provider = normalizeProvider(row.provider)
      const model = normalizeModel(row.model)
      if (!provider || !model) continue
      const key = `${provider}\n${model}`
      if (existing.has(key)) continue
      existing.add(key)
      count += 1
      added = [
        ...added,
        { provider, model, source: 'custom' as const, enabled: true, role: roleForTier(row.tier) },
      ]
    }
    candidates.value = normalizeCandidates(added)
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

  // Scheme switching between the provider preset and the explicit custom
  // lineup. Switching to custom seeds the lineup from the preset (roles
  // included) when the editor is empty, so the user starts from a working
  // configuration instead of a blank pool.
  function setScheme(scheme: 'preset' | 'custom', staticMode?: string | null) {
    const presetMode = staticMode && staticMode in STATIC_B5_PROFILES ? staticMode : null
    if (scheme === 'preset') {
      if (presetMode) {
        selectionMode.value = presetMode
        restoreBaselineCandidateInputs()
      }
      return
    }
    selectionMode.value = CUSTOM_B5_SELECTION_MODE
    modelOptions.value = []
    if (!candidates.value.some(candidate => candidate.enabled !== false)) {
      const profile = presetMode ? STATIC_B5_PROFILES[presetMode] : null
      if (profile) candidates.value = customSeedFromProfile(profile)
    }
  }

  // Default activation when the ensemble strategy is switched on: providers
  // with an official preset land on it; every other provider gets an explicit
  // custom lineup seeded from the router tiers (the models the user already
  // configured), never the hidden legacy dynamic mode.
  function activateForProvider(provider: unknown, tierCandidates: readonly EnsembleTierCandidate[] = []) {
    const presetMode = staticB5ModeForProvider(provider)
    if (presetMode) {
      selectionMode.value = presetMode
      return
    }
    selectionMode.value = CUSTOM_B5_SELECTION_MODE
    if (!candidates.value.some(candidate => candidate.enabled !== false)) {
      importTierCandidates(tierCandidates)
    }
  }

  // One-click migration off the hidden legacy router_dynamic mode: fold the
  // legacy inputs (structured candidates + model_options + tier rows) into an
  // explicit custom lineup, capped at the proposer maximum.
  function migrateLegacyToCustom(tierCandidates: readonly EnsembleTierCandidate[] = []) {
    const rows: EnsembleCandidateConfig[] = []
    const seen = new Set<string>()
    const push = (provider: string, model: string, role: EnsembleCandidateRole = '') => {
      const cleanProvider = normalizeProvider(provider)
      const cleanModel = normalizeModel(model)
      if (!cleanProvider || !cleanModel) return
      const key = `${cleanProvider}\n${cleanModel}`
      if (seen.has(key) || rows.length >= CUSTOM_B5_MAX_PROPOSERS) return
      seen.add(key)
      rows.push({ provider: cleanProvider, model: cleanModel, source: 'custom', enabled: true, role })
    }
    for (const candidate of candidates.value) {
      if (candidate.enabled === false) continue
      push(candidate.provider, candidate.model, normalizeCandidateRole(candidate.role))
    }
    if (!legacyDefaultModelOptions(modelOptions.value)) {
      for (const model of modelOptions.value) {
        push(model.includes('/') ? 'openrouter' : '', model)
      }
    }
    for (const row of tierCandidates || []) {
      push(row.provider, row.model, roleForTier(row.tier))
    }
    selectionMode.value = CUSTOM_B5_SELECTION_MODE
    modelOptions.value = []
    candidates.value = normalizeCandidates(rows)
    clampQuorumToLineup()
  }

  function setMinSuccessfulProposers(value: number) {
    const clean = normalizeMinSuccessful(value)
    const count = enabledProposerConfigs.value.length
    minSuccessfulProposers.value = (
      selectionMode.value === CUSTOM_B5_SELECTION_MODE && count >= 1
    )
      ? Math.min(clean, count)
      : clean
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
      role: normalizeCandidateRole(candidate.role),
    }))
    if (minSuccessfulDirty.value) params.minSuccessfulProposers = minSuccessfulProposers.value
    if (allFailedPolicyDirty.value) params.allFailedPolicy = allFailedPolicy.value
    return params
  }

  function effectiveFacts(proposerCount: number, isPreset: boolean): EnsembleEffectiveFacts {
    const configuredQuorum = minSuccessfulProposers.value
    const autoQuorum = isPreset
      ? STATIC_B5_EFFECTIVE_QUORUM
      : Math.max(1, proposerCount - 1)
    const quorum = Math.min(
      configuredQuorum === DEFAULT_MIN_SUCCESSFUL_PROPOSERS ? autoQuorum : configuredQuorum,
      Math.max(1, proposerCount),
    )
    return {
      perTurnCalls: proposerCount + 1,
      quorum,
      proposerCount,
      proposerTimeoutSeconds: STATIC_B5_PROPOSER_TIMEOUT_SECONDS,
      aggregatorTimeoutSeconds: STATIC_B5_AGGREGATOR_TIMEOUT_SECONDS,
      quorumGraceSeconds: STATIC_B5_QUORUM_GRACE_SECONDS,
    }
  }

  function createPanel(context: EnsemblePanelContext) {
    return computed(() => {
      const credentialStatus = context.credentialStatus?.value ?? []
      const activeProvider = normalizeProvider(context.activeProvider.value)
      const activeModel = normalizeModel(context.activeModel?.value ?? '')
      const providerStaticMode = staticB5ModeForProvider(activeProvider)

      const scheme: EnsembleScheme = (
        selectionMode.value === 'router_dynamic'
          ? 'legacy'
          : selectionMode.value === CUSTOM_B5_SELECTION_MODE
            ? 'custom'
            : providerStaticMode !== null
              ? 'preset'
              // A static preset stored for another provider cannot run against
              // this one; the editor presents the custom scheme (edits pin
              // custom_b5 explicitly via ensureCustomMode).
              : 'custom'
      )

      const tierCandidates = uniqueCandidateViews((context.tierCandidates?.value ?? [])
        .map(candidate => withCredential(candidate.provider, candidate.model, 'tier', credentialStatus))
        .filter(candidate => candidate.provider && candidate.model))
      const structuredCandidates = candidates.value
        .filter(candidate => candidate.enabled !== false)
        .map(candidate => withCredential(
          candidate.provider,
          candidate.model,
          normalizeCandidateSource(candidate.source),
          credentialStatus,
          true,
          normalizeCandidateRole(candidate.role),
        ))
      const legacyCandidates = legacyDefaultModelOptions(modelOptions.value)
        ? []
        : modelOptions.value.map((model) => {
          const provider = model.includes('/') ? 'openrouter' : activeProvider
          return withCredential(provider, model, 'legacy_model_options', credentialStatus)
        })
      const customCandidates = uniqueCandidateViews([...structuredCandidates, ...legacyCandidates])

      const activeStaticProfile = (
        scheme === 'preset' && providerStaticMode !== null
      )
        ? STATIC_B5_PROFILES[providerStaticMode]
        : null
      const fixedProfile: EnsembleFixedProfileView | null = activeStaticProfile
        ? {
            providerLabel: activeStaticProfile.label,
            proposers: activeStaticProfile.proposers.map(model => withCredential(activeStaticProfile.provider, model, 'openrouter_fixed', credentialStatus)),
            aggregator: withCredential(activeStaticProfile.provider, activeStaticProfile.aggregator, 'openrouter_fixed', credentialStatus, true, 'aggregator'),
            credential: credentialFor(activeStaticProfile.provider, credentialStatus),
          }
        : null

      const proposerViews = structuredCandidates.filter(view => view.role !== 'aggregator')
      const aggregatorView = structuredCandidates.find(view => view.role === 'aggregator') || null
      const proposerCount = proposerViews.length
      const families = new Set(proposerViews.map(view => `${modelFamilyKey(view.model)}`))
      const capacity: EnsembleCapacityState = proposerCount >= CUSTOM_B5_MAX_PROPOSERS
        ? 'full'
        : proposerCount > CUSTOM_B5_RECOMMENDED_MAX
          ? 'warn'
          : 'ok'
      const customLineup: EnsembleCustomLineupView = {
        aggregator: aggregatorView,
        aggregatorInherited: aggregatorView === null,
        inheritedAggregatorProvider: activeProvider,
        inheritedAggregatorModel: activeModel,
        proposers: proposerViews,
        proposerCount,
        minProposers: CUSTOM_B5_MIN_PROPOSERS,
        maxProposers: CUSTOM_B5_MAX_PROPOSERS,
        recommendedMin: CUSTOM_B5_RECOMMENDED_MIN,
        recommendedMax: CUSTOM_B5_RECOMMENDED_MAX,
        capacity,
        canAddProposer: proposerCount < CUSTOM_B5_MAX_PROPOSERS,
        belowMinimum: proposerCount < CUSTOM_B5_MIN_PROPOSERS,
        diversityWarning: proposerCount >= 2 && families.size < proposerCount,
        facts: effectiveFacts(proposerCount, false),
      }

      return {
        enabled: enabled.value,
        // The provider-level model is the ensemble fallback (and the current
        // model used by single-model mode). Keep it separate from the
        // router's default tier: those can intentionally point at different
        // models, especially while ensemble routing has disabled the router.
        activeProvider,
        activeModel,
        selectionMode: selectionMode.value,
        scheme,
        schemeCardsAvailable: providerStaticMode !== null,
        modelOptions: [...modelOptions.value],
        candidates: candidates.value.map(candidate => ({ ...candidate })),
        tierCandidates,
        customCandidates,
        custom: customLineup,
        fixedProfile,
        presetFacts: effectiveFacts(
          activeStaticProfile ? activeStaticProfile.proposers.length : 4,
          true,
        ),
        // Back-compat aliases (older panel/test names).
        fixedOpenRouterProfile: fixedProfile,
        showOpenRouterFixedSwitch: providerStaticMode !== null,
        openRouterCustomEnsemble: scheme !== 'preset',
        staticSelectionMode: providerStaticMode,
        minSuccessfulProposers: minSuccessfulProposers.value,
        allFailedPolicy: allFailedPolicy.value,
        showModelOptions: scheme !== 'preset',
        showCandidateEditor: scheme === 'custom' || scheme === 'legacy',
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
    setCandidateRole,
    importTierCandidates,
    resetModelOptions,
    setScheme,
    activateForProvider,
    migrateLegacyToCustom,
    setMinSuccessfulProposers,
    setAllFailedPolicy,
    payload,
    createPanel,
  }
}
