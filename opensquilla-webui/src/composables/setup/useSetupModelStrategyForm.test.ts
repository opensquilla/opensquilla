import { describe, expect, it } from 'vitest'
import { computed } from 'vue'
import { useSetupRouterForm } from './useSetupRouterForm'
import { useSetupEnsembleForm } from './useSetupEnsembleForm'
import { useSetupModelStrategyForm } from './useSetupModelStrategyForm'

function makeForm(provider = 'openai') {
  const router = useSetupRouterForm()
  const ensemble = useSetupEnsembleForm()
  router.initFromConfig({ enabled: true, tier_profile: provider }, {}, provider)
  ensemble.initFromConfig({ enabled: false })
  return { router, ensemble, strategy: useSetupModelStrategyForm(router, ensemble, computed(() => provider)) }
}

describe('useSetupModelStrategyForm', () => {
  it('derives model router when router is enabled and ensemble is off', () => {
    const { strategy } = makeForm()
    expect(strategy.activeStrategy.value).toBe('router')
  })

  it('derives model ensemble when ensemble is enabled', () => {
    const { ensemble, strategy } = makeForm()
    ensemble.setEnabled(true)
    expect(strategy.activeStrategy.value).toBe('ensemble')
  })

  it('derives model ensemble over single model when ensemble is enabled', () => {
    const { router, ensemble, strategy } = makeForm()
    router.setRouterMode('disabled')
    ensemble.setEnabled(true)

    expect(strategy.activeStrategy.value).toBe('ensemble')
  })

  it('aggregates router and ensemble dirty state', () => {
    const routerDirtyForm = makeForm()
    expect(routerDirtyForm.strategy.isDirty.value).toBe(false)

    routerDirtyForm.router.setRouterMode('disabled')
    expect(routerDirtyForm.strategy.isDirty.value).toBe(true)

    const ensembleDirtyForm = makeForm()
    expect(ensembleDirtyForm.strategy.isDirty.value).toBe(false)

    ensembleDirtyForm.ensemble.setEnabled(true)
    expect(ensembleDirtyForm.strategy.isDirty.value).toBe(true)
  })

  it('selecting single model disables ensemble and router', () => {
    const { router, ensemble, strategy } = makeForm()
    ensemble.setEnabled(true)

    strategy.setStrategy('single')

    expect(ensemble.enabled.value).toBe(false)
    expect(router.mode.value).toBe('disabled')
    expect(strategy.activeStrategy.value).toBe('single')
  })

  it('selecting model router disables ensemble and enables a custom editable table', () => {
    const { router, ensemble, strategy } = makeForm()
    router.setRouterMode('disabled')
    ensemble.setEnabled(true)

    strategy.setStrategy('router')

    expect(ensemble.enabled.value).toBe(false)
    expect(router.mode.value).toBe('custom')
    expect(strategy.activeStrategy.value).toBe('router')
  })

  it('selecting model router coerces openrouter mix to a custom editable table', () => {
    const router = useSetupRouterForm()
    const ensemble = useSetupEnsembleForm()
    router.initFromConfig({ enabled: true, tier_profile: null }, {}, 'openrouter')
    ensemble.initFromConfig({ enabled: true })
    const strategy = useSetupModelStrategyForm(router, ensemble)

    expect(router.mode.value).toBe('openrouter-mix')

    strategy.setStrategy('router')

    expect(ensemble.enabled.value).toBe(false)
    expect(router.mode.value).toBe('custom')
    expect(strategy.activeStrategy.value).toBe('router')
  })

  it('selecting model ensemble gives non-preset providers an explicit custom lineup', () => {
    const { router, ensemble, strategy } = makeForm()

    strategy.setStrategy('ensemble')

    expect(router.mode.value).toBe('disabled')
    expect(ensemble.enabled.value).toBe(true)
    // Never the hidden legacy dynamic mode — an explicit custom lineup keeps
    // the edited pool effective at runtime.
    expect(ensemble.selectionMode.value).toBe('custom_b5')
    expect(strategy.activeStrategy.value).toBe('ensemble')
  })

  it('selecting model ensemble seeds the custom lineup from the router tiers', () => {
    const router = useSetupRouterForm()
    const ensemble = useSetupEnsembleForm()
    router.initFromConfig({ enabled: true, tier_profile: 'openai' }, {}, 'openai')
    ensemble.initFromConfig({ enabled: false })
    const strategy = useSetupModelStrategyForm(
      router,
      ensemble,
      computed(() => 'openai'),
      computed(() => [
        { provider: 'openai', model: 'gpt-5.5', tier: 'c3' },
        { provider: 'openai', model: 'gpt-5.4-mini', tier: 'c0' },
      ]),
    )

    strategy.setStrategy('ensemble')

    expect(ensemble.selectionMode.value).toBe('custom_b5')
    expect(ensemble.candidates.value.map(c => c.model)).toEqual(['gpt-5.5', 'gpt-5.4-mini'])
  })

  it('selecting model ensemble uses the fixed OpenRouter profile for OpenRouter providers', () => {
    const { router, ensemble, strategy } = makeForm('openrouter')

    strategy.setStrategy('ensemble')

    expect(router.mode.value).toBe('disabled')
    expect(ensemble.enabled.value).toBe(true)
    expect(ensemble.selectionMode.value).toBe('static_openrouter_b5')
  })

  it('selecting model ensemble uses the fixed TokenRhythm profile for TokenRhythm providers', () => {
    const { router, ensemble, strategy } = makeForm('tokenrhythm')

    strategy.setStrategy('ensemble')

    expect(router.mode.value).toBe('disabled')
    expect(ensemble.enabled.value).toBe(true)
    expect(ensemble.selectionMode.value).toBe('static_tokenrhythm_b5')
  })

  it('builds the three strategy rows with model router first and no badge metadata', () => {
    const { router, ensemble, strategy } = makeForm()
    const routerPanel = router.createPanel({
      routerSummary: computed(() => ''),
      ensembleProfileActive: computed(() => false),
      hasSavedProvider: computed(() => true),
      isOpenrouter: computed(() => false),
      textTiers: [],
      tierLabel: tier => tier,
    })
    const ensemblePanel = ensemble.createPanel({
      statusText: computed(() => ''),
      activeProvider: computed(() => 'openai'),
    })
    const panel = strategy.createPanel({
      hasSavedProvider: computed(() => true),
      providerLabel: computed(() => 'OpenAI'),
      routerPanel,
      ensemblePanel,
      routerTemplateState: computed(() => 'recommended'),
    })

    expect(panel.value.cards.map(card => card.id)).toEqual(['router', 'ensemble', 'single'])
    expect(panel.value.cards.some(card => Object.prototype.hasOwnProperty.call(card, 'recommended'))).toBe(false)
  })
})
