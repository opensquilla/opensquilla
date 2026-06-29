import { describe, it, expect } from 'vitest'
import { computed } from 'vue'
import { useSetupRouterForm } from './useSetupRouterForm'

// openrouter-mix is backend-supported but was unreachable in the WebUI. The
// round-trip is subtle: it is the only enabled mode whose tier_profile is null,
// and only valid for the openrouter provider — a default config for another
// provider must NOT be mistaken for it.

function makePanel(form: ReturnType<typeof useSetupRouterForm>, isOpenrouter: boolean) {
  return form.createPanel({
    routerSummary: computed(() => ''),
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
})
