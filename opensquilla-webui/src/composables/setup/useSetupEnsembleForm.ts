import { computed, ref } from 'vue'

export const G8_ENSEMBLE_PROFILE_ID = 'default'
export const LEGACY_G8_ENSEMBLE_PROFILE_ID = 'g8_four_proposers'

export interface EnsembleMemberValue {
  provider: string
  model: string
  thinking: string
}

export interface EnsembleMemberRow extends EnsembleMemberValue {
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
  profiles?: Record<string, EnsembleProfileConfig>
}

export interface EnsembleSelectOption {
  value: string
  label: string
}

type EnsembleOptionSource = readonly EnsembleSelectOption[] | { value: readonly EnsembleSelectOption[] }

export interface EnsemblePanelContext {
  providerOptions?: EnsembleOptionSource
  modelOptions?: EnsembleOptionSource
}

const DEFAULT_THINKING = 'high'

const DEFAULT_PROPOSERS: EnsembleMemberValue[] = [
  { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', thinking: DEFAULT_THINKING },
  { provider: 'openrouter', model: 'z-ai/glm-5.2', thinking: DEFAULT_THINKING },
  { provider: 'openrouter', model: 'google/gemini-3-flash-preview', thinking: DEFAULT_THINKING },
  { provider: 'openrouter', model: 'qwen/qwen3.7-plus', thinking: DEFAULT_THINKING },
]

const DEFAULT_AGGREGATOR: EnsembleMemberValue = {
  provider: 'openrouter',
  model: 'z-ai/glm-5.2',
  thinking: DEFAULT_THINKING,
}

const DEFAULT_PROVIDER_OPTIONS: EnsembleSelectOption[] = [
  { value: 'openrouter', label: 'openrouter' },
]

const DEFAULT_MODEL_OPTIONS: EnsembleSelectOption[] = [
  ...DEFAULT_PROPOSERS.map(member => ({ value: member.model, label: member.model })),
  { value: DEFAULT_AGGREGATOR.model, label: DEFAULT_AGGREGATOR.model },
]

function cloneMember(member: EnsembleMemberValue): EnsembleMemberValue {
  return { provider: member.provider, model: member.model, thinking: DEFAULT_THINKING }
}

function normalizeMember(
  value: EnsembleMemberConfig | undefined,
  fallback: EnsembleMemberValue,
): EnsembleMemberValue {
  return {
    provider: String(value?.provider || fallback.provider || 'openrouter').trim(),
    model: String(value?.model || fallback.model || '').trim(),
    thinking: DEFAULT_THINKING,
  }
}

function memberPayload(member: EnsembleMemberValue): Record<string, unknown> {
  return {
    provider: member.provider.trim(),
    model: member.model.trim(),
    thinking: DEFAULT_THINKING,
  }
}

function optionFromValue(value: string): EnsembleSelectOption | null {
  const normalized = String(value || '').trim()
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

function optionSourceValues(source: EnsembleOptionSource | undefined): readonly EnsembleSelectOption[] {
  if (!source) return []
  return 'value' in source ? source.value : source
}

export function useSetupEnsembleForm() {
  const enabled = ref(false)
  const profileId = ref(G8_ENSEMBLE_PROFILE_ID)
  const proposers = ref<EnsembleMemberValue[]>(DEFAULT_PROPOSERS.map(cloneMember))
  const aggregator = ref<EnsembleMemberValue>(cloneMember(DEFAULT_AGGREGATOR))

  const serialized = computed(() => JSON.stringify({
    enabled: enabled.value,
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
    enabled.value = cfg.enabled === true
    profileId.value = G8_ENSEMBLE_PROFILE_ID
    proposers.value = DEFAULT_PROPOSERS.map((fallback, index) => (
      normalizeMember(profile.proposers?.[index], fallback)
    ))
    aggregator.value = normalizeMember(profile.aggregator, DEFAULT_AGGREGATOR)
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
    row[key] = String(value)
  }

  function updateAggregatorField(key: keyof EnsembleMemberValue, value: string) {
    aggregator.value[key] = String(value)
  }

  function resetToDefaults() {
    profileId.value = G8_ENSEMBLE_PROFILE_ID
    proposers.value = DEFAULT_PROPOSERS.map(cloneMember)
    aggregator.value = cloneMember(DEFAULT_AGGREGATOR)
  }

  function payload(): Record<string, unknown> {
    return {
      llm_ensemble: {
        enabled: enabled.value,
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

  function createPanel(context: EnsemblePanelContext = {}) {
    return computed(() => ({
      enabled: enabled.value,
      profileId: profileId.value,
      dirty: isDirty.value,
      providerOptions: uniqueOptions([
        ...optionSourceValues(context.providerOptions),
        ...DEFAULT_PROVIDER_OPTIONS,
        ...proposers.value.map(member => optionFromValue(member.provider)),
        optionFromValue(aggregator.value.provider),
      ]),
      modelOptions: uniqueOptions([
        ...optionSourceValues(context.modelOptions),
        ...DEFAULT_MODEL_OPTIONS,
        ...proposers.value.map(member => optionFromValue(member.model)),
        optionFromValue(aggregator.value.model),
      ]),
      proposerRows: proposers.value.map((member, index): EnsembleMemberRow => ({
        ...member,
        thinking: DEFAULT_THINKING,
        role: 'proposer',
        index,
        label: `Proposer ${index + 1}`,
      })),
      aggregatorRow: {
        ...aggregator.value,
        thinking: DEFAULT_THINKING,
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
    resetToDefaults,
    payload,
    createPanel,
  }
}
