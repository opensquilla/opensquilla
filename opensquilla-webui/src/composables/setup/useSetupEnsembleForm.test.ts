import { describe, it, expect } from 'vitest'
import { computed } from 'vue'
import { useSetupEnsembleForm } from './useSetupEnsembleForm'

// onboarding.ensemble.configure has partial-payload semantics (omitted keys
// keep their current value on the gateway), so the form's contract is: track
// dirtiness PER KEY and only ever send the keys the user actually changed.

const SAVED = {
  enabled: false,
  selection_mode: 'router_dynamic',
  model_options: ['custom/model-a', 'custom/model-b'],
  min_successful_proposers: 2,
  all_failed_policy: 'error',
}

function makePanel(form: ReturnType<typeof useSetupEnsembleForm>, provider = 'openrouter') {
  return form.createPanel({
    statusText: computed(() => ''),
    activeProvider: computed(() => provider),
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
    expect(f.minSuccessfulProposers.value).toBe(2)
    expect(f.allFailedPolicy.value).toBe('error')
  })

  it('falls back to the shipped defaults for an empty or invalid config slice', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'bogus', all_failed_policy: 'bogus', min_successful_proposers: -3 })

    expect(f.enabled.value).toBe(true)
    expect(f.selectionMode.value).toBe('static_openrouter_b5')
    expect(f.modelOptions.value).toEqual([])
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
    f.initFromConfig({ model_options: ['a/one', 'b/two'] })

    f.removeModelOption('a/one')
    expect(f.modelOptions.value).toEqual(['b/two'])
    expect(f.payload()).toEqual({ modelOptions: ['b/two'] })
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

  it('surfaces the OpenRouter credential hint only for static selection on a non-openrouter provider', () => {
    const f = useSetupEnsembleForm()
    f.initFromConfig({ selection_mode: 'static_openrouter_b5' })

    expect(makePanel(f, 'deepseek').value.showOpenrouterHint).toBe(true)
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
