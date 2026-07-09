// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupModelStrategyPanel from './SetupModelStrategyPanel.vue'

function panel(overrides: Record<string, unknown> = {}) {
  const base = {
    activeStrategy: 'router',
    hasSavedProvider: true,
    providerLabel: 'OpenRouter',
    routerTemplateState: 'recommended',
    cards: [
      { id: 'router', enabled: true, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
      { id: 'ensemble', enabled: false, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
      { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
    ],
    router: {
      routerDefaultTier: 'c1',
      routerVisualMode: 'real_candidates',
      routerVisualModeOptions: [{ value: 'real_candidates', label: 'Real routing candidates' }],
      routerConfigDisabled: false,
      hasSavedProvider: true,
      textTiers: ['c0', 'c1'],
      tierRows: [
        { name: 'c0', provider: 'openrouter', model: 'deepseek/deepseek-v4-flash', thinkingLevel: 'high', supportsImage: false },
        { name: 'c1', provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', thinkingLevel: 'high', supportsImage: false },
      ],
      tierLabel: (tier: string) => tier,
      discoveredModels: [],
      discoveredModelsProvider: '',
      discoveredModelSource: 'none',
      hasMixedTierProviders: false,
    },
    ensemble: {
      enabled: false,
      selectionMode: 'router_dynamic',
      modelOptions: [],
      candidates: [],
      tierCandidates: [
        {
          key: 'tier:openrouter:deepseek/deepseek-v4-flash',
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-flash',
          source: 'tier',
          enabled: true,
          credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
        },
        {
          key: 'tier:openrouter:deepseek/deepseek-v4-pro',
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-pro',
          source: 'tier',
          enabled: true,
          credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
        },
      ],
      customCandidates: [],
      fixedOpenRouterProfile: null,
      minSuccessfulProposers: 1,
      allFailedPolicy: 'fallback_single',
      showModelOptions: true,
      showCandidateEditor: true,
      showOpenRouterFixedSwitch: false,
      openRouterCustomEnsemble: false,
      showOpenrouterHint: false,
      advancedOpen: false,
      statusText: 'Ensemble is on.',
    },
  }
  return {
    ...base,
    ...overrides,
    router: {
      ...base.router,
      ...((overrides.router as Record<string, unknown> | undefined) || {}),
    },
    ensemble: {
      ...base.ensemble,
      ...((overrides.ensemble as Record<string, unknown> | undefined) || {}),
    },
  }
}

async function mountPanel(props = {}, listeners: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupModelStrategyPanel, { panel: panel(props), ...listeners })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SetupModelStrategyPanel', () => {
  it('renders router-first strategy rows without recommendation badges or legacy wording', async () => {
    const { app, el } = await mountPanel()

    expect(el.textContent).toContain('Model routing')
    expect(el.textContent).toContain('AI single-model routing')
    expect(el.textContent).toContain('AI ensemble routing')
    expect(el.textContent).toContain('Off')
    expect(el.querySelector('[role="radiogroup"]')).toBeTruthy()
    expect(el.querySelectorAll('[role="radio"]')).toHaveLength(3)
    expect(el.querySelector('[data-strategy-id="router"]')?.getAttribute('aria-checked')).toBe('true')
    const strategyRowsText = el.querySelector('[role="radiogroup"]')?.textContent || ''
    expect(strategyRowsText).not.toContain('Recommended')
    expect(strategyRowsText).not.toContain('Default')
    expect(strategyRowsText).not.toContain('Model ensemble')
    expect(el.textContent).not.toContain('Preset and credentials')
    expect(el.textContent).not.toContain('OpenRouter aggregated')
    expect(el.textContent).not.toContain('OpenRouter mix')
    expect(el.textContent).not.toContain('openrouter-mix')
    expect(el.textContent).not.toContain('router_dynamic')
    expect(el.textContent).not.toContain('static_openrouter_b5')

    app.unmount()
  })

  it('emits the selected strategy from a strategy card', async () => {
    const onUpdateStrategy = vi.fn()
    const { app, el } = await mountPanel({}, { onUpdateStrategy })

    el.querySelector<HTMLButtonElement>('[data-strategy-id="ensemble"]')?.click()
    await nextTick()

    expect(onUpdateStrategy).toHaveBeenCalledWith('ensemble')
    app.unmount()
  })

  it('shows router details when model router is active', async () => {
    const { app, el } = await mountPanel({ activeStrategy: 'router' })

    expect(el.textContent).toContain('Default model tier')
    expect(el.textContent).toContain('Uses OpenRouter credentials; default model is deepseek/deepseek-v4-pro.')
    expect(el.textContent).not.toContain('Preset and credentials from OpenRouter')
    expect(el.querySelector('[role="table"]')).toBeTruthy()
    // The chat-panel visualization picker rides with the router details; losing
    // it strands a saved legacy_grid choice with no UI path back.
    const visualMode = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_router_visual_mode"]')
    expect(visualMode?.value).toBe('real_candidates')
    expect(el.textContent).toContain('Routing panel style')

    app.unmount()
  })

  it('emits the routing panel style from the visual-mode select', async () => {
    const onUpdateRouterVisualMode = vi.fn()
    const { app, el } = await mountPanel(
      {
        router: {
          routerVisualModeOptions: [
            { value: 'real_candidates', label: 'Real routing candidates' },
            { value: 'legacy_grid', label: 'Three-tier visual panel' },
          ],
        },
      },
      { onUpdateRouterVisualMode },
    )

    const select = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_router_visual_mode"]')
    expect(select).toBeTruthy()
    select!.value = 'legacy_grid'
    select!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()

    expect(onUpdateRouterVisualMode).toHaveBeenCalledWith('legacy_grid')
    app.unmount()
  })

  it('uses the active provider and model without OpenRouter-specific copy', async () => {
    const { app, el } = await mountPanel({
      providerLabel: 'Groq',
      router: {
        ...panel().router,
        routerDefaultTier: 'c1',
        textTiers: ['c1'],
        tierRows: [
          { name: 'c1', provider: 'groq', model: 'llama-3.3-70b-versatile', thinkingLevel: '', supportsImage: false },
        ],
      },
    })

    expect(el.textContent).toContain('Uses Groq credentials; default model is llama-3.3-70b-versatile.')
    expect(el.textContent).not.toContain('OpenRouter credentials')

    app.unmount()
  })

  it('keeps router tier editing enabled after leaving an enabled ensemble strategy', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'router',
      router: {
        ...panel().router,
        routerConfigDisabled: true,
      },
    })

    expect(el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_router_default_tier"]')?.disabled).toBe(false)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(false)
    expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBeNull()

    app.unmount()
  })

  it('shows ensemble candidates derived from model tiers without an enable switch', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      cards: [
        { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
        { id: 'ensemble', enabled: true, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
        { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
      ],
      ensemble: {
        enabled: true,
        selectionMode: 'router_dynamic',
        modelOptions: [],
        minSuccessfulProposers: 1,
        allFailedPolicy: 'fallback_single',
        showModelOptions: true,
        showOpenrouterHint: false,
        advancedOpen: false,
        statusText: 'Ensemble is on.',
      },
    })

    expect(el.textContent).toContain('AI ensemble routing')
    expect(el.textContent).toContain('Uses OpenRouter credentials; default model is deepseek/deepseek-v4-pro.')
    expect(el.textContent).toContain('Candidate models')
    expect(el.textContent).toContain('OpenRouter · deepseek/deepseek-v4-flash')
    expect(el.textContent).toContain('OpenRouter · deepseek/deepseek-v4-pro')
    expect(el.textContent).toContain('From model tiers')
    expect(el.textContent).toContain('Reset to current tier candidates')
    expect(el.textContent).toContain('Add candidate')
    expect(el.textContent).toContain('If every candidate fails, fall back to the current model: OpenRouter · deepseek/deepseek-v4-pro.')
    expect(el.textContent).not.toContain('Use a model ensemble')
    expect(el.querySelector('[role="table"]')).toBeNull()

    app.unmount()
  })

  it('edits custom ensemble candidates and the failure policy', async () => {
    const onAddEnsembleCandidate = vi.fn()
    const onRemoveEnsembleCandidate = vi.fn()
    const onResetEnsembleCandidates = vi.fn()
    const onUpdateEnsembleAllFailedPolicy = vi.fn()
    const customCandidate = {
      key: 'custom:deepseek:deepseek-v4-pro',
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      credential: { provider: 'deepseek', available: true, source: 'explicit', envKey: 'DEEPSEEK_API_KEY' },
    }
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        cards: [
          { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
          { id: 'ensemble', enabled: true, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
          { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
        ],
        ensemble: {
          enabled: true,
          selectionMode: 'router_dynamic',
          modelOptions: [],
          customCandidates: [customCandidate],
          minSuccessfulProposers: 1,
          allFailedPolicy: 'fallback_single',
          showModelOptions: true,
          showCandidateEditor: true,
          showOpenrouterHint: false,
          advancedOpen: false,
          statusText: 'Ensemble is on.',
        },
      },
      {
        onAddEnsembleCandidate,
        onRemoveEnsembleCandidate,
        onResetEnsembleCandidates,
        onUpdateEnsembleAllFailedPolicy,
      },
    )

    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.textContent).toContain('Custom')
    expect(el.textContent).toContain('Connected')

    el.querySelector<HTMLButtonElement>('[aria-label="Remove deepseek-v4-pro"]')?.click()
    await nextTick()
    expect(onRemoveEnsembleCandidate.mock.calls[0]?.[0]).toMatchObject(customCandidate)

    const provider = el.querySelector<HTMLInputElement>('input[name="setup_model_strategy_add_candidate_provider"]')
    provider!.value = 'anthropic'
    provider!.dispatchEvent(new Event('input', { bubbles: true }))
    const model = el.querySelector<HTMLInputElement>('input[name="setup_model_strategy_add_candidate_model"]')
    model!.value = 'claude-opus'
    model!.dispatchEvent(new Event('input', { bubbles: true }))
    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate"]')?.click()
    await nextTick()
    expect(onAddEnsembleCandidate).toHaveBeenCalledWith('anthropic', 'claude-opus')

    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-reset-candidates"]')?.click()
    await nextTick()
    expect(onResetEnsembleCandidates).toHaveBeenCalledOnce()

    const failure = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_all_failed_policy"]')
    failure!.value = 'error'
    failure!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onUpdateEnsembleAllFailedPolicy).toHaveBeenCalledWith('error')

    app.unmount()
  })

  it('explains that one ensemble candidate is only a baseline state', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      cards: [
        { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
        { id: 'ensemble', enabled: true, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
        { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
      ],
      router: {
        ...panel().router,
        textTiers: ['c1'],
        tierRows: [
          { name: 'c1', provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', thinkingLevel: 'high', supportsImage: false },
        ],
      },
      ensemble: {
        enabled: true,
        selectionMode: 'router_dynamic',
        tierCandidates: [
          {
            key: 'tier:openrouter:deepseek/deepseek-v4-pro',
            provider: 'openrouter',
            model: 'deepseek/deepseek-v4-pro',
            source: 'tier',
            enabled: true,
            credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
          },
        ],
        customCandidates: [],
        modelOptions: [],
        minSuccessfulProposers: 1,
        allFailedPolicy: 'fallback_single',
        showModelOptions: true,
        showOpenrouterHint: false,
        advancedOpen: false,
        statusText: 'Ensemble is on.',
      },
    })

    expect(el.textContent).toContain('Add at least one more candidate to benefit from ensemble routing.')

    app.unmount()
  })

  it('shows the fixed OpenRouter ensemble profile without the custom candidate editor', async () => {
    const onUpdateOpenrouterCustomEnsemble = vi.fn()
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      cards: [
        { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
        { id: 'ensemble', enabled: true, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
        { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
      ],
      ensemble: {
        enabled: true,
        selectionMode: 'static_openrouter_b5',
        fixedOpenRouterProfile: {
          providerLabel: 'OpenRouter',
          proposers: [
            { key: 'openrouter-fixed:openrouter:deepseek/deepseek-v4-pro', provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', source: 'openrouter_fixed', enabled: true },
            { key: 'openrouter-fixed:openrouter:z-ai/glm-5.2', provider: 'openrouter', model: 'z-ai/glm-5.2', source: 'openrouter_fixed', enabled: true },
            { key: 'openrouter-fixed:openrouter:moonshotai/kimi-k2.7-code', provider: 'openrouter', model: 'moonshotai/kimi-k2.7-code', source: 'openrouter_fixed', enabled: true },
            { key: 'openrouter-fixed:openrouter:qwen/qwen3.7-max', provider: 'openrouter', model: 'qwen/qwen3.7-max', source: 'openrouter_fixed', enabled: true },
          ],
          aggregator: { key: 'openrouter-fixed:openrouter:z-ai/glm-5.2:aggregator', provider: 'openrouter', model: 'z-ai/glm-5.2', source: 'openrouter_fixed', enabled: true },
        },
        showCandidateEditor: false,
        showOpenRouterFixedSwitch: true,
        openRouterCustomEnsemble: false,
      },
    }, { onUpdateOpenrouterCustomEnsemble })

    expect(el.textContent).toContain('OpenRouter fixed ensemble')
    expect(el.textContent).toContain('Customize ensemble')
    expect(el.textContent).toContain('deepseek/deepseek-v4-pro')
    expect(el.textContent).toContain('moonshotai/kimi-k2.7-code')
    expect(el.textContent).toContain('qwen/qwen3.7-max')
    expect(el.textContent).toContain('Aggregator')
    const customize = el.querySelector<HTMLInputElement>('input[name="setup_model_strategy_openrouter_custom"]')
    expect(customize?.checked).toBe(false)
    customize!.checked = true
    customize!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onUpdateOpenrouterCustomEnsemble).toHaveBeenCalledWith(true)
    expect(el.querySelector('input[name="setup_model_strategy_add_candidate_provider"]')).toBeNull()
    expect(el.querySelector('[data-testid="setup-model-strategy-reset-candidates"]')).toBeNull()

    app.unmount()
  })

  it('shows custom candidates rather than the fixed OpenRouter block for non-OpenRouter providers', async () => {
    const { app, el } = await mountPanel({
      providerLabel: 'DeepSeek',
      activeStrategy: 'ensemble',
      cards: [
        { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
        { id: 'ensemble', enabled: true, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
        { id: 'single', enabled: false, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
      ],
      router: {
        ...panel().router,
        routerDefaultTier: 'c1',
        textTiers: ['c1'],
        tierRows: [
          { name: 'c1', provider: 'deepseek', model: 'deepseek-v4-pro', thinkingLevel: 'high', supportsImage: false },
        ],
      },
      ensemble: {
        enabled: true,
        selectionMode: 'static_openrouter_b5',
        fixedOpenRouterProfile: null,
        tierCandidates: [
          {
            key: 'tier:deepseek:deepseek-v4-pro',
            provider: 'deepseek',
            model: 'deepseek-v4-pro',
            source: 'tier',
            enabled: true,
            credential: { provider: 'deepseek', available: true, source: 'explicit', envKey: 'DEEPSEEK_API_KEY' },
          },
        ],
        customCandidates: [],
        showCandidateEditor: true,
        showOpenRouterFixedSwitch: false,
      },
    })

    expect(el.textContent).not.toContain('OpenRouter fixed ensemble')
    expect(el.textContent).not.toContain('Customize ensemble')
    expect(el.textContent).toContain('Candidate models')
    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.querySelector('input[name="setup_model_strategy_add_candidate_provider"]')).toBeTruthy()

    app.unmount()
  })

  it('shows non-empty single model details', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'single',
      cards: [
        { id: 'router', enabled: false, titleKey: 'setup.modelStrategy.cards.router.title', descKey: 'setup.modelStrategy.cards.router.desc' },
        { id: 'ensemble', enabled: false, titleKey: 'setup.modelStrategy.cards.ensemble.title', descKey: 'setup.modelStrategy.cards.ensemble.desc' },
        { id: 'single', enabled: true, titleKey: 'setup.modelStrategy.cards.single.title', descKey: 'setup.modelStrategy.cards.single.desc' },
      ],
      ensemble: {
        enabled: false,
        selectionMode: 'router_dynamic',
        modelOptions: [],
        minSuccessfulProposers: 1,
        allFailedPolicy: 'fallback_single',
        showModelOptions: true,
        showOpenrouterHint: false,
        advancedOpen: false,
        statusText: 'Ensemble is off.',
      },
    })

    expect(el.textContent).toContain('Off')
    expect(el.textContent).toContain('Every turn goes to the current model: OpenRouter · deepseek/deepseek-v4-pro.')
    expect(el.textContent).toContain('AI routing and ensemble routing are off')
    expect(el.textContent).not.toContain('Default model tier')
    expect(el.querySelector('[role="table"]')).toBeNull()

    app.unmount()
  })

  it('forwards default tier changes from router controls', async () => {
    const onUpdateRouterDefaultTier = vi.fn()
    const { app, el } = await mountPanel(
      { activeStrategy: 'router' },
      { onUpdateRouterDefaultTier },
    )

    const select = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_router_default_tier"]')
    expect(select).toBeTruthy()
    select!.value = 'c0'
    select!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()

    expect(onUpdateRouterDefaultTier).toHaveBeenCalledWith('c0')
    app.unmount()
  })

  it('does not expose banned technical terms in title attributes', async () => {
    const { app, el } = await mountPanel()

    const titles = Array.from(el.querySelectorAll('[title]')).map(node => node.getAttribute('title') || '').join('\n')
    expect(titles).not.toMatch(/openrouter-mix|router_dynamic|static_openrouter_b5|tier_profile|Recommended|Default/)

    app.unmount()
  })

  it('shows provider-first guidance and emits provider navigation when no provider is saved', async () => {
    const onGoToSection = vi.fn()
    const { app, el } = await mountPanel({ hasSavedProvider: false }, { onGoToSection })

    const guidance = el.querySelector('[data-testid="model-strategy-provider-first"]')
    expect(guidance?.textContent).toContain('Choose a Chat Model first')
    guidance?.querySelector('button')?.click()
    await nextTick()

    expect(onGoToSection).toHaveBeenCalledWith('provider')
    app.unmount()
  })

  it('shows cross-provider notice when model tiers use mixed providers', async () => {
    const { app, el } = await mountPanel({
      router: {
        ...panel().router,
        hasMixedTierProviders: true,
      },
    })

    expect(el.textContent).toContain('Cross-provider routing')

    app.unmount()
  })
})
