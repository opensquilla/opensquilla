import { describe, expect, it } from 'vitest'
import {
  G8_ENSEMBLE_PROFILE_ID,
  LEGACY_G8_ENSEMBLE_PROFILE_ID,
  useSetupEnsembleForm,
} from './useSetupEnsembleForm'

describe('useSetupEnsembleForm', () => {
  it('initializes the G8 defaults', () => {
    const form = useSetupEnsembleForm()

    form.initFromConfig({})

    const panel = form.createPanel()
    expect(panel.value.enabled).toBe(false)
    expect(panel.value.profileId).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(panel.value.proposerRows).toHaveLength(4)
    expect(panel.value.proposerRows.map(row => row.model)).toEqual([
      'deepseek/deepseek-v4-pro',
      'z-ai/glm-5.2',
      'google/gemini-3-flash-preview',
      'qwen/qwen3.7-plus',
    ])
    expect(panel.value.aggregatorRow.model).toBe('z-ai/glm-5.2')
    expect(panel.value.proposerRows.every(row => row.provider === 'openrouter')).toBe(true)
    expect(panel.value.proposerRows.every(row => row.thinking === 'high')).toBe(true)
    expect(panel.value.modelOptions.map(option => option.value)).toEqual(expect.arrayContaining([
      'deepseek/deepseek-v4-pro',
      'z-ai/glm-5.2',
      'google/gemini-3-flash-preview',
      'qwen/qwen3.7-plus',
    ]))
    expect(form.isDirty.value).toBe(false)
  })

  it('merges sparse saved G8 profile rows with defaults', () => {
    const form = useSetupEnsembleForm()

    form.initFromConfig({
      enabled: true,
      active_profile: 'other',
      profiles: {
        [G8_ENSEMBLE_PROFILE_ID]: {
          proposers: [
            { provider: 'openrouter', model: 'custom/proposer', thinking: 'medium' },
          ],
          aggregator: { provider: 'openrouter', model: 'custom/aggregator', thinking: 'low' },
        },
      },
    })

    const panel = form.createPanel()
    expect(panel.value.enabled).toBe(true)
    expect(panel.value.profileId).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(panel.value.proposerRows[0].model).toBe('custom/proposer')
    expect(panel.value.proposerRows[1].model).toBe('z-ai/glm-5.2')
    expect(panel.value.aggregatorRow.model).toBe('custom/aggregator')
    expect(panel.value.proposerRows[0].thinking).toBe('high')
    expect(panel.value.aggregatorRow.thinking).toBe('high')
    expect(panel.value.modelOptions.map(option => option.value)).toEqual(expect.arrayContaining([
      'custom/proposer',
      'custom/aggregator',
    ]))
    expect(form.isDirty.value).toBe(false)
  })

  it('reads legacy G8 profile rows and saves them back as the default profile', () => {
    const form = useSetupEnsembleForm()

    form.initFromConfig({
      enabled: true,
      active_profile: LEGACY_G8_ENSEMBLE_PROFILE_ID,
      profiles: {
        [LEGACY_G8_ENSEMBLE_PROFILE_ID]: {
          proposers: [
            { provider: 'openrouter', model: 'legacy/proposer', thinking: 'high' },
          ],
          aggregator: { provider: 'openrouter', model: 'legacy/aggregator', thinking: 'high' },
        },
      },
    })

    const panel = form.createPanel()
    const payload = form.payload() as {
      llm_ensemble: {
        active_profile: string
        profiles: Record<string, unknown>
      }
    }

    expect(panel.value.profileId).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(panel.value.proposerRows[0].model).toBe('legacy/proposer')
    expect(panel.value.aggregatorRow.model).toBe('legacy/aggregator')
    expect(payload.llm_ensemble.active_profile).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(payload.llm_ensemble.profiles[G8_ENSEMBLE_PROFILE_ID]).toBeTruthy()
    expect(payload.llm_ensemble.profiles[LEGACY_G8_ENSEMBLE_PROFILE_ID]).toBeUndefined()
  })

  it('builds a config.patch merge payload for the edited G8 profile', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    form.setEnabled(true)
    form.updateProposerField(2, 'model', 'google/gemini-3-flash-preview:free')

    const payload = form.payload() as {
      llm_ensemble: {
        enabled: boolean
        active_profile: string
        profiles: Record<string, {
          proposers: Array<Record<string, unknown>>
          aggregator: Record<string, unknown>
        }>
      }
    }
    const profile = payload.llm_ensemble.profiles[G8_ENSEMBLE_PROFILE_ID]

    expect(form.isDirty.value).toBe(true)
    expect(payload.llm_ensemble.enabled).toBe(true)
    expect(payload.llm_ensemble.active_profile).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(profile.proposers[2]).toEqual({
      provider: 'openrouter',
      model: 'google/gemini-3-flash-preview:free',
      thinking: 'high',
    })
    expect(profile.aggregator).toEqual({
      provider: 'openrouter',
      model: 'z-ai/glm-5.2',
      thinking: 'high',
    })
    expect(JSON.stringify(payload)).not.toMatch(/api_key|apiKey/)
  })

  it('always saves high thinking even if an internal caller edits the hidden field', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    form.updateAggregatorField('thinking', 'medium')

    const payload = form.payload() as {
      llm_ensemble: {
        profiles: Record<string, { aggregator: Record<string, unknown> }>
      }
    }
    expect(payload.llm_ensemble.profiles[G8_ENSEMBLE_PROFILE_ID].aggregator.thinking).toBe('high')
  })

  it('resets edited models to G8 defaults without changing the enabled switch', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    form.setEnabled(true)
    form.updateProposerField(0, 'model', 'custom/model')
    form.resetToDefaults()

    const panel = form.createPanel()
    expect(panel.value.enabled).toBe(true)
    expect(panel.value.proposerRows[0].model).toBe('deepseek/deepseek-v4-pro')
    expect(form.isDirty.value).toBe(true)
  })

  it('accepts provider and model option sources from the settings catalog', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    const panel = form.createPanel({
      providerOptions: [{ value: 'ollama', label: 'ollama' }],
      modelOptions: [{ value: 'local/custom-model', label: 'local/custom-model' }],
    })

    expect(panel.value.providerOptions.map(option => option.value)).toEqual(expect.arrayContaining(['openrouter', 'ollama']))
    expect(panel.value.modelOptions.map(option => option.value)).toContain('local/custom-model')
  })
})
