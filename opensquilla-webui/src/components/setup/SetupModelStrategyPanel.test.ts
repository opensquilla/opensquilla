// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupModelStrategyPanel from './SetupModelStrategyPanel.vue'

const FACTS = {
  perTurnCalls: 3,
  quorum: 1,
  proposerCount: 2,
  proposerTimeoutSeconds: 300,
  aggregatorTimeoutSeconds: 480,
  quorumGraceSeconds: 30,
}

function customLineup(overrides: Record<string, unknown> = {}) {
  return {
    aggregator: null,
    aggregatorInherited: true,
    inheritedAggregatorProvider: 'openrouter',
    inheritedAggregatorModel: 'deepseek/deepseek-v4-pro',
    proposers: [],
    proposerCount: 0,
    minProposers: 2,
    maxProposers: 6,
    recommendedMin: 3,
    recommendedMax: 4,
    capacity: 'ok',
    canAddProposer: true,
    belowMinimum: true,
    diversityWarning: false,
    facts: FACTS,
    ...overrides,
  }
}

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
      discoveredModelsByProvider: {},
      hasMixedTierProviders: false,
    },
    ensemble: {
      enabled: false,
      activeProvider: 'openrouter',
      activeModel: 'deepseek/deepseek-v4-pro',
      selectionMode: 'custom_b5',
      scheme: 'custom',
      schemeCardsAvailable: true,
      modelOptions: [],
      candidates: [],
      tierCandidates: [
        {
          key: 'tier:openrouter:deepseek/deepseek-v4-flash',
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-flash',
          source: 'tier',
          enabled: true,
          role: '',
          credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
        },
        {
          key: 'tier:openrouter:deepseek/deepseek-v4-pro',
          provider: 'openrouter',
          model: 'deepseek/deepseek-v4-pro',
          source: 'tier',
          enabled: true,
          role: '',
          credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
        },
      ],
      customCandidates: [],
      custom: customLineup(),
      fixedProfile: null,
      presetFacts: {
        perTurnCalls: 5,
        quorum: 3,
        proposerCount: 4,
        proposerTimeoutSeconds: 300,
        aggregatorTimeoutSeconds: 480,
        quorumGraceSeconds: 30,
      },
      minSuccessfulProposers: 1,
      allFailedPolicy: 'fallback_single',
      showCandidateEditor: true,
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
    expect(el.textContent).toContain('Uses OpenRouter credentials; provider default model is deepseek/deepseek-v4-pro.')
    expect(el.textContent).not.toContain('Preset and credentials from OpenRouter')
    expect(el.querySelector('[role="table"]')).toBeTruthy()
    // The chat-panel visualization picker rides with the router details; losing
    // it strands a saved legacy_grid choice with no UI path back.
    const visualMode = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_router_visual_mode"]')
    expect(visualMode?.value).toBe('real_candidates')
    expect(el.textContent).toContain('Routing panel style')

    app.unmount()
  })

  it('lets a router tier choose a discovered model from the options trigger', async () => {
    const onUpdateTierField = vi.fn()
    const discoveredModels = [
      {
        id: 'test-vendor/alpha',
        name: 'Alpha',
        contextWindow: 262144,
        maxOutputTokens: 16384,
        capabilities: ['chat', 'tools'],
        pricing: null,
        capabilitySource: 'provider',
      },
    ]
    const { app, el } = await mountPanel(
      {
        router: {
          discoveredModelsByProvider: {
            openrouter: { models: discoveredModels, source: 'live' },
          },
        },
      },
      { onUpdateTierField },
    )

    const input = el.querySelector<HTMLInputElement>(
      'input[role="combobox"][aria-label="c0 model"]',
    )!
    const trigger = input.parentElement?.querySelector<HTMLButtonElement>(
      '[data-testid="setup-model-options-toggle"]',
    )

    expect(trigger).toBeTruthy()
    trigger!.click()
    await nextTick()

    const option = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[role="option"]'),
    ).find(row => row.textContent?.includes('test-vendor/alpha'))

    expect(option).toBeTruthy()
    option!.click()
    await nextTick()

    expect(onUpdateTierField).toHaveBeenCalledWith('c0', 'model', 'test-vendor/alpha')
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
      ensemble: {
        activeProvider: 'groq',
        activeModel: 'llama-3.3-70b-versatile',
      },
      router: {
        ...panel().router,
        routerDefaultTier: 'c1',
        textTiers: ['c1'],
        tierRows: [
          { name: 'c1', provider: 'groq', model: 'llama-3.3-70b-versatile', thinkingLevel: '', supportsImage: false },
        ],
      },
    })

    expect(el.textContent).toContain('Uses Groq credentials; provider default model is llama-3.3-70b-versatile.')
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

  it('shows the custom lineup with aggregator-first sections and the pipeline explainer', async () => {
    const proposer = {
      key: 'custom:proposer:deepseek:deepseek-v4-pro',
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      role: 'primary',
      credential: { provider: 'deepseek', available: true, source: 'explicit', envKey: 'DEEPSEEK_API_KEY' },
    }
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        scheme: 'custom',
        custom: customLineup({
          proposers: [proposer],
          proposerCount: 1,
          belowMinimum: true,
        }),
      },
    })

    expect(el.querySelector('[data-testid="ensemble-pipeline"]')?.textContent)
      .toContain('Only the aggregator can call tools')
    expect(el.textContent).toContain('Aggregator')
    expect(el.querySelector('[data-testid="ensemble-custom-aggregator-inherited"]')?.textContent)
      .toContain('deepseek/deepseek-v4-pro')
    expect(el.textContent).toContain('Proposer models')
    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.textContent).toContain('Primary')
    expect(el.querySelector('[data-testid="ensemble-below-minimum"]')).toBeTruthy()
    expect(el.querySelector('[data-testid="ensemble-custom-facts"]')?.textContent)
      .toContain('3 model calls')
    expect(el.querySelector('[role="table"]')).toBeNull()

    app.unmount()
  })

  it.each(['router', 'ensemble', 'single'] as const)(
    'shows the provider model instead of the router default tier in %s mode',
    async (activeStrategy) => {
      const { app, el } = await mountPanel({
        activeStrategy,
        ensemble: {
          activeModel: 'deepseek/deepseek-v4-flash',
        },
      })

      const heading = el.querySelector('.setup-model-strategy__detail .control-section__head')?.textContent || ''
      expect(heading).toContain('deepseek/deepseek-v4-flash')
      expect(heading).not.toContain('deepseek/deepseek-v4-pro')

      app.unmount()
    },
  )

  it('edits custom lineup candidates, roles, and the failure policy', async () => {
    const onAddEnsembleCandidate = vi.fn()
    const onRemoveEnsembleCandidate = vi.fn()
    const onSetEnsembleCandidateRole = vi.fn()
    const onImportEnsembleTierCandidates = vi.fn()
    const onUpdateEnsembleAllFailedPolicy = vi.fn()
    const customCandidate = {
      key: 'custom:proposer:deepseek:deepseek-v4-pro',
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      role: '',
      credential: { provider: 'deepseek', available: true, source: 'explicit', envKey: 'DEEPSEEK_API_KEY' },
    }
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: {
          enabled: true,
          scheme: 'custom',
          custom: customLineup({ proposers: [customCandidate], proposerCount: 1 }),
        },
      },
      {
        onAddEnsembleCandidate,
        onRemoveEnsembleCandidate,
        onSetEnsembleCandidateRole,
        onImportEnsembleTierCandidates,
        onUpdateEnsembleAllFailedPolicy,
      },
    )

    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.textContent).toContain('Connected')

    el.querySelector<HTMLButtonElement>('[aria-label="Remove deepseek-v4-pro"]')?.click()
    await nextTick()
    expect(onRemoveEnsembleCandidate.mock.calls[0]?.[0]).toMatchObject(customCandidate)

    const roleSelect = el.querySelector<HTMLSelectElement>('select[aria-label="Role for deepseek-v4-pro"]')
    expect(roleSelect).toBeTruthy()
    roleSelect!.value = 'critic'
    roleSelect!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onSetEnsembleCandidateRole.mock.calls[0]?.[1]).toBe('critic')

    const provider = el.querySelector<HTMLInputElement>('input[name="setup_model_strategy_add_candidate_provider"]')
    provider!.value = 'anthropic'
    provider!.dispatchEvent(new Event('input', { bubbles: true }))
    const model = el.querySelector<HTMLInputElement>('input[name="setup_model_strategy_add_candidate_model"]')
    model!.value = 'claude-opus'
    model!.dispatchEvent(new Event('input', { bubbles: true }))
    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate"]')?.click()
    await nextTick()
    expect(onAddEnsembleCandidate).toHaveBeenCalledWith('anthropic', 'claude-opus', '')

    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-import-tiers"]')?.click()
    await nextTick()
    expect(onImportEnsembleTierCandidates).toHaveBeenCalledOnce()

    const failure = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_all_failed_policy"]')
    failure!.value = 'error'
    failure!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onUpdateEnsembleAllFailedPolicy).toHaveBeenCalledWith('error')

    app.unmount()
  })

  it('surfaces capacity warnings and disables adding at the proposer cap', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        scheme: 'custom',
        custom: customLineup({
          proposerCount: 6,
          capacity: 'full',
          canAddProposer: false,
          belowMinimum: false,
          diversityWarning: true,
          facts: { ...FACTS, perTurnCalls: 7, proposerCount: 6, quorum: 5 },
        }),
      },
    })

    expect(el.querySelector('[data-testid="ensemble-capacity-full"]')?.textContent).toContain('6')
    expect(el.querySelector('[data-testid="ensemble-diversity-warn"]')).toBeTruthy()
    expect(el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate"]')?.disabled).toBe(true)

    app.unmount()
  })

  it('shows the preset lineup with member notes, effective facts, and scheme cards', async () => {
    const onUpdateEnsembleScheme = vi.fn()
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        selectionMode: 'static_openrouter_b5',
        scheme: 'preset',
        schemeCardsAvailable: true,
        fixedProfile: {
          providerLabel: 'OpenRouter',
          proposers: [
            { key: 'openrouter-fixed:proposer:openrouter:deepseek/deepseek-v4-pro', provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', source: 'openrouter_fixed', enabled: true, role: '' },
            { key: 'openrouter-fixed:proposer:openrouter:z-ai/glm-5.2', provider: 'openrouter', model: 'z-ai/glm-5.2', source: 'openrouter_fixed', enabled: true, role: '' },
            { key: 'openrouter-fixed:proposer:openrouter:moonshotai/kimi-k2.7-code', provider: 'openrouter', model: 'moonshotai/kimi-k2.7-code', source: 'openrouter_fixed', enabled: true, role: '' },
            { key: 'openrouter-fixed:proposer:openrouter:qwen/qwen3.7-max', provider: 'openrouter', model: 'qwen/qwen3.7-max', source: 'openrouter_fixed', enabled: true, role: '' },
          ],
          aggregator: { key: 'openrouter-fixed:aggregator:openrouter:z-ai/glm-5.2', provider: 'openrouter', model: 'z-ai/glm-5.2', source: 'openrouter_fixed', enabled: true, role: 'aggregator' },
        },
        showCandidateEditor: false,
      },
    }, { onUpdateEnsembleScheme })

    expect(el.textContent).toContain('OpenRouter fixed ensemble')
    expect(el.textContent).toContain('deepseek/deepseek-v4-pro')
    expect(el.textContent).toContain('moonshotai/kimi-k2.7-code')
    expect(el.textContent).toContain('Aggregator')
    // Member notes + effective runtime facts are the new identity layer.
    expect(el.textContent).toContain('Reasoning anchor')
    expect(el.textContent).toContain('the only member that can call tools')
    expect(el.querySelector('[data-testid="ensemble-preset-facts"]')?.textContent).toContain('3/4')
    // Scheme cards replace the old customize toggle.
    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')?.getAttribute('aria-checked')).toBe('true')
    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-scheme-custom"]')?.click()
    await nextTick()
    expect(onUpdateEnsembleScheme).toHaveBeenCalledWith('custom')
    expect(el.textContent).not.toContain('legacy OpenRouter candidate template')
    expect(el.querySelector('input[name="setup_model_strategy_add_candidate_provider"]')).toBeNull()

    app.unmount()
  })

  it('shows a migration banner for a stored legacy dynamic config', async () => {
    const onMigrateEnsembleLegacy = vi.fn()
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: {
          enabled: true,
          selectionMode: 'router_dynamic',
          scheme: 'legacy',
          schemeCardsAvailable: true,
        },
      },
      { onMigrateEnsembleLegacy },
    )

    const banner = el.querySelector('[data-testid="ensemble-legacy-banner"]')
    expect(banner).toBeTruthy()
    // Legacy configs keep editing affordances but no scheme cards until migrated.
    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')).toBeNull()
    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-migrate-legacy"]')?.click()
    await nextTick()
    expect(onMigrateEnsembleLegacy).toHaveBeenCalledOnce()

    app.unmount()
  })

  it('hides scheme cards for providers without a preset', async () => {
    const { app, el } = await mountPanel({
      providerLabel: 'DeepSeek',
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        scheme: 'custom',
        schemeCardsAvailable: false,
        custom: customLineup({ inheritedAggregatorProvider: 'deepseek', inheritedAggregatorModel: 'deepseek-v4-pro' }),
      },
    })

    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')).toBeNull()
    expect(el.textContent).not.toContain('OpenRouter fixed ensemble')
    expect(el.textContent).toContain('Proposer models')
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
    expect(guidance?.textContent).toContain('Choose a Model Service first')
    expect(guidance?.querySelector('button')?.textContent).toContain('Go to Model Service')
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
