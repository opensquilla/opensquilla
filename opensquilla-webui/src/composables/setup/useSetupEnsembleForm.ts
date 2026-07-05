import { computed, ref, type ComputedRef } from 'vue'

// Settings form for the [llm_ensemble] routing surface, saved through
// onboarding.ensemble.configure. That RPC has partial-payload semantics (the
// gateway merges over the current section), so this form tracks dirtiness PER
// KEY and payload() only carries the keys the user actually changed — an
// enabled-only save can never clobber an operator's other customizations.

export const ENSEMBLE_SELECTION_MODES = ['static_openrouter_b5', 'router_dynamic'] as const
export const ENSEMBLE_ALL_FAILED_POLICIES = ['fallback_single', 'error'] as const

const DEFAULT_SELECTION_MODE = 'static_openrouter_b5'
const DEFAULT_MIN_SUCCESSFUL_PROPOSERS = 1
const DEFAULT_ALL_FAILED_POLICY = 'fallback_single'

export interface EnsembleConfigSlice {
  enabled?: boolean
  selection_mode?: string
  model_options?: string[]
  min_successful_proposers?: number
  all_failed_policy?: string
}

interface EnsemblePanelContext {
  statusText: ComputedRef<string>
  activeProvider: ComputedRef<string>
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

export function useSetupEnsembleForm() {
  const enabled = ref(true)
  const selectionMode = ref(DEFAULT_SELECTION_MODE)
  const modelOptions = ref<string[]>([])
  const minSuccessfulProposers = ref(DEFAULT_MIN_SUCCESSFUL_PROPOSERS)
  const allFailedPolicy = ref(DEFAULT_ALL_FAILED_POLICY)

  // Per-key baselines: partial payloads need to know WHICH keys changed, not
  // just that something did. Seeded from the initial state so the pristine
  // form is never dirty while config loads.
  const baseline = ref({
    enabled: enabled.value,
    selectionMode: selectionMode.value,
    modelOptions: JSON.stringify(modelOptions.value),
    minSuccessfulProposers: minSuccessfulProposers.value,
    allFailedPolicy: allFailedPolicy.value,
  })

  const enabledDirty = computed(() => enabled.value !== baseline.value.enabled)
  const selectionModeDirty = computed(() => selectionMode.value !== baseline.value.selectionMode)
  const modelOptionsDirty = computed(() => JSON.stringify(modelOptions.value) !== baseline.value.modelOptions)
  const minSuccessfulDirty = computed(() => minSuccessfulProposers.value !== baseline.value.minSuccessfulProposers)
  const allFailedPolicyDirty = computed(() => allFailedPolicy.value !== baseline.value.allFailedPolicy)
  const isDirty = computed(() => (
    enabledDirty.value
    || selectionModeDirty.value
    || modelOptionsDirty.value
    || minSuccessfulDirty.value
    || allFailedPolicyDirty.value
  ))

  function snapshotBaseline() {
    baseline.value = {
      enabled: enabled.value,
      selectionMode: selectionMode.value,
      modelOptions: JSON.stringify(modelOptions.value),
      minSuccessfulProposers: minSuccessfulProposers.value,
      allFailedPolicy: allFailedPolicy.value,
    }
  }

  function initFromConfig(config: EnsembleConfigSlice) {
    enabled.value = config.enabled !== false
    selectionMode.value = normalizeSelectionMode(config.selection_mode)
    modelOptions.value = normalizeModelOptions(config.model_options)
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
    if (modelOptionsDirty.value) params.modelOptions = [...modelOptions.value]
    if (minSuccessfulDirty.value) params.minSuccessfulProposers = minSuccessfulProposers.value
    if (allFailedPolicyDirty.value) params.allFailedPolicy = allFailedPolicy.value
    return params
  }

  function createPanel(context: EnsemblePanelContext) {
    return computed(() => ({
      enabled: enabled.value,
      selectionMode: selectionMode.value,
      modelOptions: [...modelOptions.value],
      minSuccessfulProposers: minSuccessfulProposers.value,
      allFailedPolicy: allFailedPolicy.value,
      // model_options only drives the dynamic selection; static ignores it.
      showModelOptions: selectionMode.value === 'router_dynamic',
      // Static selection routes through OpenRouter regardless of the primary
      // provider — surface the credential dependency instead of failing quietly.
      showOpenrouterHint: (
        selectionMode.value === 'static_openrouter_b5'
        && context.activeProvider.value.toLowerCase() !== 'openrouter'
      ),
      advancedOpen: (
        minSuccessfulProposers.value !== DEFAULT_MIN_SUCCESSFUL_PROPOSERS
        || allFailedPolicy.value !== DEFAULT_ALL_FAILED_POLICY
      ),
      statusText: context.statusText.value,
    }))
  }

  return {
    enabled,
    selectionMode,
    modelOptions,
    minSuccessfulProposers,
    allFailedPolicy,
    enabledDirty,
    selectionModeDirty,
    modelOptionsDirty,
    minSuccessfulDirty,
    allFailedPolicyDirty,
    isDirty,
    initFromConfig,
    setEnabled,
    setSelectionMode,
    addModelOption,
    removeModelOption,
    setMinSuccessfulProposers,
    setAllFailedPolicy,
    payload,
    createPanel,
  }
}
