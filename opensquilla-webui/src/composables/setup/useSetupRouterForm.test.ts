import { describe, it, expect } from 'vitest'
import { computed } from 'vue'
import { useSetupRouterForm } from './useSetupRouterForm'

// openrouter-mix is backend-supported but was unreachable in the WebUI. The
// round-trip is subtle: it is the only enabled mode whose tier_profile is null,
// and only valid for the openrouter provider — a default config for another
// provider must NOT be mistaken for it.

function makePanel(form: ReturnType<typeof useSetupRouterForm>, isOpenrouter: boolean, ensembleProfileActive = false) {
  return form.createPanel({
    routerSummary: computed(() => ''),
    ensembleProfileActive: computed(() => ensembleProfileActive),
    hasSavedProvider: computed(() => true),
    isOpenrouter: computed(() => isOpenrouter),
    textTiers: ['c0'],
    tierLabel: (t) => t,
  })
}

describe('useSetupRouterForm — openrouter-mix round-trip', () => {
  it('classifies an enabled openrouter config with no tier_profile as openrouter-mix', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openrouter')
    expect(f.mode.value).toBe('openrouter-mix')
    expect(f.payload().mode).toBe('openrouter-mix')
  })

  it('classifies an openrouter config WITH a tier_profile as recommended', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: 'openrouter' }, {}, 'openrouter')
    expect(f.mode.value).toBe('recommended')
  })

  it('does NOT mistake a non-openrouter provider for openrouter-mix', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openai')
    expect(f.mode.value).toBe('recommended')
  })

  it('classifies a disabled config as disabled regardless of provider', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: false }, {}, 'openrouter')
    expect(f.mode.value).toBe('disabled')
  })

  it('offers the openrouter-mix option only for openrouter providers', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: 'openai' }, {}, 'openai')
    expect(makePanel(f, false).value.canUseOpenrouterMix).toBe(false)
    expect(makePanel(f, true).value.canUseOpenrouterMix).toBe(true)
  })

  it('passes the LLM ensemble profile state to the router panel', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: 'openai' }, {}, 'openai')

    expect(makePanel(f, false, true).value.ensembleProfileActive).toBe(true)
  })

  it('keeps tier provider values in the save payload even when the panel renders them read-only', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({
      enabled: true,
      tier_profile: null,
      tiers: {
        c0: {
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-flash',
          thinking_level: 'high',
          supports_image: false,
        },
      },
    }, {}, 'openrouter')

    expect(f.payload()).toMatchObject({
      mode: 'openrouter-mix',
      tiers: {
        c0: {
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-flash',
          thinkingLevel: 'high',
          supportsImage: false,
        },
      },
    })
  })

  it('surfaces openrouter-mix as its own honest select value and round-trips the payload', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openrouter')

    const panel = makePanel(f, true)
    expect(panel.value.routerMode).toBe('openrouter-mix')
    expect(panel.value.routerModeChoice).toBe('openrouter-mix')
    expect(panel.value.canUseOpenrouterMix).toBe(true)
    expect(panel.value.routerConfigDisabled).toBe(false)
    expect(f.payload().mode).toBe('openrouter-mix')
  })

  it('coerces a stored openrouter-mix mode back to recommended and marks the form dirty', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openrouter')
    expect(f.mode.value).toBe('openrouter-mix')

    f.setRouterMode('recommended')
    expect(f.mode.value).toBe('recommended')
    expect(f.routingDirty.value).toBe(true)
  })

  it('maps disabled router config to the single-model UI choice', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: false }, {}, 'openrouter')

    const panel = makePanel(f, true)
    expect(panel.value.routerMode).toBe('disabled')
    expect(panel.value.routerModeChoice).toBe('disabled')
    expect(panel.value.routerConfigDisabled).toBe(true)
  })

  it('marks standard router configuration read-only while LLM ensemble routing is active', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: true, tier_profile: 'openai' }, {}, 'openai')

    const panel = makePanel(f, false, true)
    expect(panel.value.routerMode).toBe('recommended')
    expect(panel.value.routerModeChoice).toBe('recommended')
    expect(panel.value.ensembleProfileActive).toBe(true)
    expect(panel.value.routerConfigDisabled).toBe(true)
    expect(panel.value.routerConfigDisabledReason).toBe('ensemble')
    expect(f.payload().mode).toBe('recommended')
  })

  it('uses the ensemble disabled reason when ensemble routing is active over single-model settings', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: false }, {}, 'openrouter')

    const panel = makePanel(f, true, true)
    expect(panel.value.routerMode).toBe('disabled')
    expect(panel.value.routerModeChoice).toBe('disabled')
    expect(panel.value.routerConfigDisabled).toBe(true)
    expect(panel.value.routerConfigDisabledReason).toBe('ensemble')
  })

  it('uses the single-model disabled reason when model routing is disabled and ensemble routing is inactive', () => {
    const f = useSetupRouterForm()
    f.initFromConfig({ enabled: false }, {}, 'openrouter')

    const panel = makePanel(f, true, false)
    expect(panel.value.routerMode).toBe('disabled')
    expect(panel.value.routerModeChoice).toBe('disabled')
    expect(panel.value.routerConfigDisabled).toBe(true)
    expect(panel.value.routerConfigDisabledReason).toBe('single-model')
  })
})
