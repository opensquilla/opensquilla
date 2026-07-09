import { describe, it, expect } from 'vitest'
import { computed } from 'vue'
import {
  LEGACY_OPENROUTER_MODEL_OPTIONS,
  OPENROUTER_FIXED_ENSEMBLE_AGGREGATOR,
  OPENROUTER_FIXED_ENSEMBLE_PROPOSERS,
  TOKENRHYTHM_FIXED_ENSEMBLE_AGGREGATOR,
  TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS,
  staticB5ModeForProvider,
  useSetupEnsembleForm,
  type EnsembleConfigSlice,
} from './useSetupEnsembleForm'

// onboarding.ensemble.configure has partial-payload semantics (omitted keys
// keep their current value on the gateway), so the form's contract is: track
// dirtiness PER KEY and only ever send the keys the user actually changed.

const SAVED = {
  enabled: false,
  selection_mode: 'router_dynamic',
  model_options: ['custom/model-a', 'custom/model-b'],
  candidates: [{ provider: 'deepseek', model: 'deepseek-v4-pro', source: 'custom', enabled: true }],
  min_successful_proposers: 2,
  all_failed_policy: 'error',
} satisfies EnsembleConfigSlice

function makePanel(
  form: ReturnType<typeof useSetupEnsembleForm>,
  provider = 'openrouter',
  tierCandidates: Array<{ provider: string; model: string }> = [],
) {
  return form.createPanel({
    statusText: computed(() => ''),
    activeProvider: computed(() => provider),
    tierCandidates: computed(() => tierCandidates),
    credentialStatus: computed(() => [
      { provider: 'openrouter', available: false, source: 'missing_env', envKey: 'OPENROUTER_API_KEY' },
      { provider: 'deepseek', available: true, source: 'explicit', envKey: 'DEEPSEEK_API_KEY' },
    ]),
  })
}

describe('useSetupEnsembleForm — init + dirty tracking', () => {
  it('is pristine before and after initFromConfig', () => {
    const f = useSetupEnsembleForm()
    expect(f.isDirty.value).toBe(false)

    f.initFromConfig(SAVED)
    expect(f.isDirty.value).toBe(false)
    expect(f.enabled.value).toBe(false)
    expect(f.selectionMode.value).toBe('router_dynamic')
    expect(f.modelOptions.value).toEqual(['custom/model-a', 'custom/model-b'])
    expect(f.candidates.value).toEqual([{ provider: 'deepseek', model: 'deepseek-v4-pro', source: 'custom', enabled: true }])
    expect(f.minSuccessfulProposers.value).toBe(2)
    expect(f.allFailedPolicy.value).toBe('error')
  })

  it('falls back to the shipped defaults for an empty or invalid config slice', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'bogus', all_failed_policy: 'bogus', min_successful_proposers: -3 })

    expect(f.enabled.value).toBe(false)
    expect(f.selectionMode.value).toBe('static_openrouter_b5')
    expect(f.modelOptions.value).toEqual([])
    expect(f.candidates.value).toEqual([])
    expect(f.minSuccessfulProposers.value).toBe(1)
    expect(f.allFailedPolicy.value).toBe('fallback_single')
    expect(f.isDirty.value).toBe(false)
  })

  it('reverting an edit back to the baseline clears the dirty state', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.setEnabled(true)
    expect(f.isDirty.value).toBe(true)
    f.setEnabled(false)
    expect(f.isDirty.value).toBe(false)

    f.removeModelOption('custom/model-b')
    expect(f.isDirty.value).toBe(true)
    f.addModelOption('custom/model-b')
    expect(f.isDirty.value).toBe(false)
  })
})

describe('useSetupEnsembleForm — partial payload building', () => {
  it('builds an empty payload when nothing changed', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)
    expect(f.payload()).toEqual({})
  })

  it('sends ONLY the changed key (enabled-only save never clobbers the rest)', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.setEnabled(true)
    expect(f.payload()).toEqual({ enabled: true })
  })

  it('sends only the selection mode when only it changed', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.setSelectionMode('static_openrouter_b5')
    expect(f.payload()).toEqual({ selectionMode: 'static_openrouter_b5' })
  })

  it('accumulates exactly the dirty keys across several edits', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.addModelOption('custom/model-c')
    f.setMinSuccessfulProposers(3)
    expect(f.payload()).toEqual({
      modelOptions: ['custom/model-a', 'custom/model-b', 'custom/model-c'],
      minSuccessfulProposers: 3,
    })
  })

  it('sends structured candidates when custom candidates changed', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.addCandidate('OpenRouter', 'qwen/qwen3.7-max')

    expect(f.payload()).toEqual({
      candidates: [
        { provider: 'deepseek', model: 'deepseek-v4-pro', source: 'custom', enabled: true },
        { provider: 'openrouter', model: 'qwen/qwen3.7-max', source: 'custom', enabled: true },
      ],
    })
  })

  it('switches OpenRouter fixed ensemble into custom dynamic candidates using the legacy template', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({
      enabled: true,
      selection_mode: 'static_openrouter_b5',
      model_options: [...LEGACY_OPENROUTER_MODEL_OPTIONS],
    })

    f.setOpenRouterCustomEnsemble(true)

    expect(f.selectionMode.value).toBe('router_dynamic')
    expect(f.modelOptions.value).toEqual([])
    expect(f.candidates.value).toEqual(
      LEGACY_OPENROUTER_MODEL_OPTIONS.map(model => ({
        provider: 'openrouter',
        model,
        source: 'custom',
        enabled: true,
      })),
    )
    expect(f.payload()).toEqual({
      selectionMode: 'router_dynamic',
      modelOptions: [],
      candidates: LEGACY_OPENROUTER_MODEL_OPTIONS.map(model => ({
        provider: 'openrouter',
        model,
        source: 'custom',
        enabled: true,
      })),
    })
  })

  it('turns OpenRouter customization back off without leaking seeded candidates into a pristine static save', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ enabled: true, selection_mode: 'static_openrouter_b5' })

    f.setOpenRouterCustomEnsemble(true)
    f.setOpenRouterCustomEnsemble(false)

    expect(f.selectionMode.value).toBe('static_openrouter_b5')
    expect(f.isDirty.value).toBe(false)
    expect(f.payload()).toEqual({})
  })

  it('sends allFailedPolicy alone when only it changed', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.setAllFailedPolicy('fallback_single')
    expect(f.payload()).toEqual({ allFailedPolicy: 'fallback_single' })
  })
})

describe('useSetupEnsembleForm — model option edits', () => {
  it('trims, ignores empties, and deduplicates on add', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ model_options: ['a/one'] })

    f.addModelOption('  b/two  ')
    f.addModelOption('')
    f.addModelOption('a/one')
    expect(f.modelOptions.value).toEqual(['a/one', 'b/two'])
  })

  it('removes exactly the named option', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'router_dynamic', model_options: ['a/one', 'b/two'] })

    f.removeModelOption('a/one')
    expect(f.modelOptions.value).toEqual(['b/two'])
    expect(f.payload()).toEqual({ modelOptions: ['b/two'] })
  })

  it('resets custom model options and structured candidates back to the tier-derived baseline', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({
      selection_mode: 'router_dynamic',
      model_options: ['a/one', 'b/two'],
      candidates: [{ provider: 'deepseek', model: 'deepseek-v4-pro' }],
    })

    f.resetModelOptions()

    expect(f.modelOptions.value).toEqual([])
    expect(f.candidates.value).toEqual([])
    expect(f.payload()).toEqual({ modelOptions: [], candidates: [] })
  })

  it('clamps min successful proposers to a positive integer', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig(SAVED)

    f.setMinSuccessfulProposers(0)
    expect(f.minSuccessfulProposers.value).toBe(1)
    f.setMinSuccessfulProposers(2.9)
    expect(f.minSuccessfulProposers.value).toBe(2)
    f.setMinSuccessfulProposers(Number.NaN)
    expect(f.minSuccessfulProposers.value).toBe(1)
  })
})

describe('useSetupEnsembleForm — panel contract', () => {
  it('shows the candidate list only for the dynamic selection', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'router_dynamic' })
    expect(makePanel(f).value.showModelOptions).toBe(true)

    f.setSelectionMode('static_openrouter_b5')
    expect(makePanel(f).value.showModelOptions).toBe(false)
  })

  it('shows only tier-derived candidates for DeepSeek when legacy OpenRouter defaults are present', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({
      selection_mode: 'router_dynamic',
      model_options: [...LEGACY_OPENROUTER_MODEL_OPTIONS],
    })

    const panel = makePanel(f, 'deepseek', [
      { provider: 'deepseek', model: 'deepseek-v4-flash' },
      { provider: 'deepseek', model: 'deepseek-v4-pro' },
    ])

    expect(panel.value.tierCandidates.map(candidate => candidate.model)).toEqual([
      'deepseek-v4-flash',
      'deepseek-v4-pro',
    ])
    expect(panel.value.customCandidates).toEqual([])
  })

  it('materializes non-default legacy options as legacy candidates with provider credentials', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({
      selection_mode: 'router_dynamic',
      model_options: ['moonshotai/kimi-k2.7-code'],
    })

    const panel = makePanel(f, 'deepseek')

    expect(panel.value.customCandidates).toMatchObject([
      {
        provider: 'openrouter',
        model: 'moonshotai/kimi-k2.7-code',
        source: 'legacy_model_options',
        credential: { available: false, source: 'missing_env' },
      },
    ])
  })

  it('uses the fixed OpenRouter 4+1 profile for static selection', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_openrouter_b5' })

    const panel = makePanel(f, 'openrouter').value
    const profile = panel.fixedOpenRouterProfile

    expect(profile?.proposers.map(candidate => candidate.model)).toEqual([...OPENROUTER_FIXED_ENSEMBLE_PROPOSERS])
    expect(profile?.aggregator.model).toBe(OPENROUTER_FIXED_ENSEMBLE_AGGREGATOR)
    expect(panel.showCandidateEditor).toBe(false)
    expect(panel.showOpenRouterFixedSwitch).toBe(true)
    expect(panel.openRouterCustomEnsemble).toBe(false)
  })

  it('uses the fixed TokenRhythm 4+1 profile for the tokenrhythm static selection', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_tokenrhythm_b5' })

    // The stored mode round-trips (it must not normalize back to the default).
    expect(f.selectionMode.value).toBe('static_tokenrhythm_b5')
    expect(staticB5ModeForProvider('tokenrhythm')).toBe('static_tokenrhythm_b5')

    const panel = makePanel(f, 'tokenrhythm').value
    const profile = panel.fixedOpenRouterProfile

    expect(profile?.providerLabel).toBe('TokenRhythm')
    expect(profile?.proposers.map(candidate => candidate.model)).toEqual([...TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS])
    expect(profile?.aggregator.model).toBe(TOKENRHYTHM_FIXED_ENSEMBLE_AGGREGATOR)
    expect(profile?.proposers.every(candidate => candidate.provider === 'tokenrhythm')).toBe(true)
    expect(panel.showCandidateEditor).toBe(false)
    expect(panel.showOpenRouterFixedSwitch).toBe(true)
    expect(panel.openRouterCustomEnsemble).toBe(false)
  })

  it('switches the tokenrhythm fixed ensemble into custom candidates seeded from its own lineup', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_tokenrhythm_b5' })

    f.setOpenRouterCustomEnsemble(true, 'static_tokenrhythm_b5')
    expect(f.selectionMode.value).toBe('router_dynamic')
    expect(f.candidates.value.every(candidate => candidate.provider === 'tokenrhythm')).toBe(true)
    expect(f.candidates.value.map(candidate => candidate.model)).toEqual([
      ...TOKENRHYTHM_FIXED_ENSEMBLE_PROPOSERS,
    ])

    f.setOpenRouterCustomEnsemble(false, 'static_tokenrhythm_b5')
    expect(f.selectionMode.value).toBe('static_tokenrhythm_b5')
    expect(f.isDirty.value).toBe(false)
  })

  it('uses the custom candidate panel for non-OpenRouter providers even if static mode is stored', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_openrouter_b5' })

    const panel = makePanel(f, 'deepseek').value

    expect(panel.fixedOpenRouterProfile).toBeNull()
    expect(panel.showCandidateEditor).toBe(true)
    expect(panel.showOpenRouterFixedSwitch).toBe(false)
  })

  it('does not surface OpenRouter fixed hints outside the OpenRouter provider path', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_openrouter_b5' })

    expect(makePanel(f, 'deepseek').value.showOpenrouterHint).toBe(false)
    expect(makePanel(f, 'openrouter').value.showOpenrouterHint).toBe(false)
    expect(makePanel(f, 'OpenRouter').value.showOpenrouterHint).toBe(false)

    f.setSelectionMode('router_dynamic')
    expect(makePanel(f, 'deepseek').value.showOpenrouterHint).toBe(false)
  })

  it('opens the Advanced disclosure only when advanced values differ from defaults', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({})
    expect(makePanel(f).value.advancedOpen).toBe(false)

    f.setMinSuccessfulProposers(2)
    expect(makePanel(f).value.advancedOpen).toBe(true)

    f.setMinSuccessfulProposers(1)
    f.setAllFailedPolicy('error')
    expect(makePanel(f).value.advancedOpen).toBe(true)
  })
})
