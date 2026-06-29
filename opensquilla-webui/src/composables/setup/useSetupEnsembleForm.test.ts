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
    expect(panel.value.modelOptions.map(option => option.value)).toEqual([
      'deepseek/deepseek-v4-pro',
      'z-ai/glm-5.2',
      'google/gemini-3-flash-preview',
      'qwen/qwen3.7-plus',
    ])
    expect(form.isDirty.value).toBe(false)
  })

  it('reads a variable proposer list and configured model options', () => {
    const form = useSetupEnsembleForm()

    form.initFromConfig({
      enabled: true,
      active_profile: 'other',
      model_options: [
        'custom/proposer',
        'custom/aggregator',
        'z-ai/glm-5.2',
      ],
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
    expect(panel.value.profileId).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(panel.value.proposerRows).toHaveLength(1)
    expect(panel.value.proposerRows[0].model).toBe('custom/proposer')
    expect(panel.value.aggregatorRow.model).toBe('custom/aggregator')
    expect(panel.value.proposerRows[0].thinking).toBe('high')
    expect(panel.value.aggregatorRow.thinking).toBe('high')
    expect(panel.value.modelOptions.map(option => option.value)).toEqual([
      'custom/proposer',
      'custom/aggregator',
      'z-ai/glm-5.2',
    ])
    expect(form.isDirty.value).toBe(false)
  })

  it('reads legacy G8 profile rows and saves them back as the default profile', () => {
    const form = useSetupEnsembleForm()

    form.initFromConfig({
      enabled: true,
      active_profile: LEGACY_G8_ENSEMBLE_PROFILE_ID,
      model_options: ['legacy/proposer', 'legacy/aggregator'],
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
    form.updateProposerField(2, 'model', 'qwen/qwen3.7-plus')

    const payload = form.payload() as {
      llm_ensemble: {
        active_profile: string
        profiles: Record<string, {
          proposers: Array<Record<string, unknown>>
          aggregator: Record<string, unknown>
        }>
      }
    }
    const profile = payload.llm_ensemble.profiles[G8_ENSEMBLE_PROFILE_ID]

    expect(form.isDirty.value).toBe(true)
    expect('enabled' in payload.llm_ensemble).toBe(false)
    expect(payload.llm_ensemble.active_profile).toBe(G8_ENSEMBLE_PROFILE_ID)
    expect(profile.proposers[2]).toEqual({
      provider: 'openrouter',
      model: 'qwen/qwen3.7-plus',
      thinking: 'high',
    })
    expect(profile.aggregator).toEqual({
      provider: 'openrouter',
      model: 'z-ai/glm-5.2',
      thinking: 'high',
    })
    expect(JSON.stringify(payload)).not.toMatch(/api_key|apiKey/)
  })

  it('builds safe dot patches for non-admin settings saves', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    form.updateProposerField(0, 'model', 'z-ai/glm-5.2')

    expect(form.patches()).toEqual({
      'llm_ensemble.active_profile': G8_ENSEMBLE_PROFILE_ID,
      'llm_ensemble.profiles.default.proposers': [
        { provider: 'openrouter', model: 'z-ai/glm-5.2', thinking: 'high' },
        { provider: 'openrouter', model: 'z-ai/glm-5.2', thinking: 'high' },
        { provider: 'openrouter', model: 'google/gemini-3-flash-preview', thinking: 'high' },
        { provider: 'openrouter', model: 'qwen/qwen3.7-plus', thinking: 'high' },
      ],
      'llm_ensemble.profiles.default.aggregator': {
        provider: 'openrouter',
        model: 'z-ai/glm-5.2',
        thinking: 'high',
      },
    })
    expect(JSON.stringify(form.patches())).not.toMatch(/api_key|apiKey|enabled/)
  })

  it('adds and removes proposer rows while keeping at least one proposer', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({
      model_options: ['a/model', 'b/model'],
      profiles: {
        [G8_ENSEMBLE_PROFILE_ID]: {
          proposers: [{ provider: 'openrouter', model: 'a/model' }],
          aggregator: { provider: 'openrouter', model: 'b/model' },
        },
      },
    })

    expect(form.createPanel().value.proposerRows).toHaveLength(1)
    expect(form.createPanel().value.proposerRows[0].canRemove).toBe(false)

    form.addProposer()
    let panel = form.createPanel()
    expect(panel.value.proposerRows).toHaveLength(2)
    expect(panel.value.proposerRows[1].model).toBe('a/model')
    expect(panel.value.proposerRows.every(row => row.canRemove)).toBe(true)

    form.removeProposer(0)
    panel = form.createPanel()
    expect(panel.value.proposerRows).toHaveLength(1)
    expect(panel.value.proposerRows[0].canRemove).toBe(false)

    form.removeProposer(0)
    expect(form.createPanel().value.proposerRows).toHaveLength(1)
  })

  it('ignores providers outside openrouter and models outside configured options', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({
      model_options: ['allowed/model'],
      profiles: {
        [G8_ENSEMBLE_PROFILE_ID]: {
          proposers: [{ provider: 'ollama', model: 'outside/model' }],
          aggregator: { provider: 'anthropic', model: 'outside/aggregator' },
        },
      },
    })

    let panel = form.createPanel()
    expect(panel.value.providerOptions.map(option => option.value)).toEqual(['openrouter'])
    expect(panel.value.modelOptions.map(option => option.value)).toEqual(['allowed/model'])
    expect(panel.value.proposerRows[0].provider).toBe('openrouter')
    expect(panel.value.proposerRows[0].model).toBe('allowed/model')
    expect(panel.value.aggregatorRow.provider).toBe('openrouter')
    expect(panel.value.aggregatorRow.model).toBe('allowed/model')

    form.updateProposerField(0, 'provider', 'ollama')
    form.updateProposerField(0, 'model', 'outside/model')
    form.updateAggregatorField('provider', 'anthropic')
    form.updateAggregatorField('model', 'outside/aggregator')

    panel = form.createPanel()
    expect(panel.value.proposerRows[0].provider).toBe('openrouter')
    expect(panel.value.proposerRows[0].model).toBe('allowed/model')
    expect(panel.value.aggregatorRow.provider).toBe('openrouter')
    expect(panel.value.aggregatorRow.model).toBe('allowed/model')
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

  it('does not treat the external enabled flag as a Settings form edit', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({})

    form.setEnabled(true)

    expect(form.isDirty.value).toBe(false)
    expect(JSON.stringify(form.payload())).not.toMatch(/"enabled"/)
  })

  it('resets edited models to G8 defaults', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({
      profiles: {
        [G8_ENSEMBLE_PROFILE_ID]: {
          proposers: [
            { provider: 'openrouter', model: 'z-ai/glm-5.2' },
          ],
          aggregator: { provider: 'openrouter', model: 'qwen/qwen3.7-plus' },
        },
      },
    })

    form.resetToDefaults()

    const panel = form.createPanel()
    expect(panel.value.proposerRows[0].model).toBe('deepseek/deepseek-v4-pro')
    expect(form.isDirty.value).toBe(true)
  })

  it('uses only configured model options when present', () => {
    const form = useSetupEnsembleForm()
    form.initFromConfig({
      model_options: ['local/custom-model', 'z-ai/glm-5.2'],
    })

    const panel = form.createPanel()

    expect(panel.value.providerOptions.map(option => option.value)).toEqual(['openrouter'])
    expect(panel.value.modelOptions.map(option => option.value)).toEqual(['local/custom-model', 'z-ai/glm-5.2'])
  })
})
