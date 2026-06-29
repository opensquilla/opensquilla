import { computed, ref } from 'vue'

export const G8_ENSEMBLE_PROFILE_ID = 'default'
export const LEGACY_G8_ENSEMBLE_PROFILE_ID = 'g8_four_proposers'

export interface EnsembleMemberValue {
  provider: string
  model: string
  thinking: string
}

export interface EnsembleMemberRow extends EnsembleMemberValue {
  canRemove: boolean
  label: string
  role: 'proposer' | 'aggregator'
  index: number
}

interface EnsembleMemberConfig {
  provider?: string
  model?: string
  thinking?: string | null
}

interface EnsembleProfileConfig {
  proposers?: EnsembleMemberConfig[]
  aggregator?: EnsembleMemberConfig
}

export interface EnsembleConfig {
  enabled?: boolean
  active_profile?: string
  model_options?: string[]
  profiles?: Record<string, EnsembleProfileConfig>
}

export interface EnsembleSelectOption {
  value: string
  label: string
}

const DEFAULT_PROVIDER = 'openrouter'
const DEFAULT_THINKING = 'high'

const DEFAULT_MODEL_VALUES = [
  'deepseek/deepseek-v4-pro',
  'z-ai/glm-5.2',
  'google/gemini-3-flash-preview',
  'qwen/qwen3.7-plus',
  'deepseek/deepseek-v4-flash',
  'qwen/qwen3.7-max',
  'anthropic/claude-sonnet-4.6',
  'anthropic/claude-opus-4.8',
  'openai/gpt-5.5',
  'openai/gpt-5.4-mini',
  'x-ai/grok-4.3',
  'moonshotai/kimi-k2.6',
  'mistralai/mistral-large-2512',
  'meta-llama/llama-4-maverick',
]

const DEFAULT_PROPOSERS: EnsembleMemberValue[] = [
  { provider: DEFAULT_PROVIDER, model: DEFAULT_MODEL_VALUES[0], thinking: DEFAULT_THINKING },
  { provider: DEFAULT_PROVIDER, model: DEFAULT_MODEL_VALUES[1], thinking: DEFAULT_THINKING },
  { provider: DEFAULT_PROVIDER, model: DEFAULT_MODEL_VALUES[2], thinking: DEFAULT_THINKING },
  { provider: DEFAULT_PROVIDER, model: DEFAULT_MODEL_VALUES[3], thinking: DEFAULT_THINKING },
]

const DEFAULT_AGGREGATOR: EnsembleMemberValue = {
  provider: DEFAULT_PROVIDER,
  model: DEFAULT_MODEL_VALUES[1],
  thinking: DEFAULT_THINKING,
}

const DEFAULT_PROVIDER_OPTIONS: EnsembleSelectOption[] = [
  { value: DEFAULT_PROVIDER, label: DEFAULT_PROVIDER },
]

function cloneMember(member: EnsembleMemberValue): EnsembleMemberValue {
  return { provider: DEFAULT_PROVIDER, model: member.model, thinking: DEFAULT_THINKING }
}

function optionFromModel(model: string): EnsembleSelectOption | null {
  const normalized = String(model || '').trim()
  return normalized ? { value: normalized, label: normalized } : null
}

function uniqueOptions(options: Array<EnsembleSelectOption | null | undefined>): EnsembleSelectOption[] {
  const seen = new Set<string>()
  const out: EnsembleSelectOption[] = []
  for (const option of options) {
    const value = String(option?.value || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    out.push({ value, label: String(option?.label || value).trim() || value })
  }
  return out
}

function optionsFromConfig(config: EnsembleConfig | undefined): EnsembleSelectOption[] {
  const configured = Array.isArray(config?.model_options)
    ? config.model_options.map(model => optionFromModel(model))
    : []
  const configuredOptions = uniqueOptions(configured)
  if (configuredOptions.length) return configuredOptions
  return DEFAULT_MODEL_VALUES.map(model => ({ value: model, label: model }))
}

function firstModel(options: readonly EnsembleSelectOption[]): string {
  return options[0]?.value || DEFAULT_MODEL_VALUES[0]
}

function normalizeModel(
  model: string | undefined,
  fallback: string,
  options: readonly EnsembleSelectOption[],
): string {
  const allowed = new Set(options.map(option => option.value))
  const candidate = String(model || '').trim()
  if (candidate && allowed.has(candidate)) return candidate
  if (fallback && allowed.has(fallback)) return fallback
  return firstModel(options)
}

function normalizeMember(
  value: EnsembleMemberConfig | undefined,
  fallback: EnsembleMemberValue,
  options: readonly EnsembleSelectOption[],
): EnsembleMemberValue {
  return {
    provider: DEFAULT_PROVIDER,
    model: normalizeModel(value?.model, fallback.model, options),
    thinking: DEFAULT_THINKING,
  }
}

function memberPayload(member: EnsembleMemberValue): Record<string, unknown> {
  return {
    provider: DEFAULT_PROVIDER,
    model: member.model.trim(),
    thinking: DEFAULT_THINKING,
  }
}

export function useSetupEnsembleForm() {
  const enabled = ref(false)
  const profileId = ref(G8_ENSEMBLE_PROFILE_ID)
  const modelOptions = ref<EnsembleSelectOption[]>(optionsFromConfig(undefined))
  const proposers = ref<EnsembleMemberValue[]>(DEFAULT_PROPOSERS.map(cloneMember))
  const aggregator = ref<EnsembleMemberValue>(cloneMember(DEFAULT_AGGREGATOR))

  const serialized = computed(() => JSON.stringify({
    profileId: profileId.value,
    proposers: proposers.value,
    aggregator: aggregator.value,
  }))
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  function initFromConfig(config: EnsembleConfig | undefined) {
    const cfg = config || {}
    const profiles = cfg.profiles || {}
    const profile = profiles[G8_ENSEMBLE_PROFILE_ID]
      || profiles[LEGACY_G8_ENSEMBLE_PROFILE_ID]
      || {}
    const options = optionsFromConfig(cfg)
    modelOptions.value = options
    enabled.value = cfg.enabled === true
    profileId.value = G8_ENSEMBLE_PROFILE_ID
    const savedProposers = Array.isArray(profile.proposers)
      ? profile.proposers.filter(member => String(member?.model || '').trim())
      : []
    proposers.value = (savedProposers.length ? savedProposers : DEFAULT_PROPOSERS)
      .map((member, index) => normalizeMember(member, DEFAULT_PROPOSERS[index] || DEFAULT_PROPOSERS[0], options))
    if (!proposers.value.length) {
      proposers.value = [normalizeMember(undefined, DEFAULT_PROPOSERS[0], options)]
    }
    aggregator.value = normalizeMember(profile.aggregator, DEFAULT_AGGREGATOR, options)
    baseline.value = serialized.value
  }

  function setEnabled(value: boolean) {
    enabled.value = Boolean(value)
  }

  function updateProposerField(
    index: number,
    key: keyof EnsembleMemberValue,
    value: string,
  ) {
    const row = proposers.value[index]
    if (!row) return
    if (key === 'provider') {
      row.provider = DEFAULT_PROVIDER
      return
    }
    if (key === 'thinking') {
      row.thinking = DEFAULT_THINKING
      return
    }
    row.model = normalizeModel(value, row.model, modelOptions.value)
  }

  function updateAggregatorField(key: keyof EnsembleMemberValue, value: string) {
    if (key === 'provider') {
      aggregator.value.provider = DEFAULT_PROVIDER
      return
    }
    if (key === 'thinking') {
      aggregator.value.thinking = DEFAULT_THINKING
      return
    }
    aggregator.value.model = normalizeModel(value, aggregator.value.model, modelOptions.value)
  }

  function addProposer() {
    proposers.value.push({
      provider: DEFAULT_PROVIDER,
      model: firstModel(modelOptions.value),
      thinking: DEFAULT_THINKING,
    })
  }

  function removeProposer(index: number) {
    if (proposers.value.length <= 1) return
    if (index < 0 || index >= proposers.value.length) return
    proposers.value.splice(index, 1)
  }

  function resetToDefaults() {
    profileId.value = G8_ENSEMBLE_PROFILE_ID
    proposers.value = DEFAULT_PROPOSERS.map(member => normalizeMember(member, member, modelOptions.value))
    aggregator.value = normalizeMember(DEFAULT_AGGREGATOR, DEFAULT_AGGREGATOR, modelOptions.value)
  }

  function payload(): Record<string, unknown> {
    return {
      llm_ensemble: {
        active_profile: G8_ENSEMBLE_PROFILE_ID,
        profiles: {
          [G8_ENSEMBLE_PROFILE_ID]: {
            proposers: proposers.value.map(memberPayload),
            aggregator: memberPayload(aggregator.value),
          },
        },
      },
    }
  }

  function patches(): Record<string, unknown> {
    return {
      'llm_ensemble.active_profile': G8_ENSEMBLE_PROFILE_ID,
      'llm_ensemble.profiles.default.proposers': proposers.value.map(memberPayload),
      'llm_ensemble.profiles.default.aggregator': memberPayload(aggregator.value),
    }
  }

  function createPanel() {
    return computed(() => ({
      profileId: profileId.value,
      dirty: isDirty.value,
      providerOptions: DEFAULT_PROVIDER_OPTIONS,
      modelOptions: modelOptions.value,
      proposerRows: proposers.value.map((member, index): EnsembleMemberRow => ({
        ...member,
        provider: DEFAULT_PROVIDER,
        thinking: DEFAULT_THINKING,
        canRemove: proposers.value.length > 1,
        role: 'proposer',
        index,
        label: `Proposer ${index + 1}`,
      })),
      aggregatorRow: {
        ...aggregator.value,
        provider: DEFAULT_PROVIDER,
        thinking: DEFAULT_THINKING,
        canRemove: false,
        role: 'aggregator' as const,
        index: 0,
        label: 'Aggregator',
      },
    }))
  }

  return {
    enabled,
    profileId,
    proposers,
    aggregator,
    isDirty,
    initFromConfig,
    setEnabled,
    updateProposerField,
    updateAggregatorField,
    addProposer,
    removeProposer,
    resetToDefaults,
    payload,
    patches,
    createPanel,
  }
}
