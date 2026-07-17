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
  quorumGraceSeconds: 5,
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
        quorumGraceSeconds: 5,
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

    expect(el.querySelector('[role="radiogroup"]')?.getAttribute('aria-label')).toBe('Model routing')
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

  it('lets a router tier choose a discovered model from the model input', async () => {
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
    expect(input.getAttribute('aria-expanded')).toBe('false')
    input.dispatchEvent(new Event('focus'))
    await nextTick()
    expect(input.getAttribute('aria-expanded')).toBe('true')

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

  it('shows a proposer-first custom lineup without legacy advisory roles', async () => {
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

    const lineup = el.querySelector<HTMLElement>('[data-testid="ensemble-custom-lineup"]')!
    const steps = lineup.querySelectorAll<HTMLElement>('.setup-model-strategy__step')
    expect(steps).toHaveLength(2)
    expect(steps[0]?.textContent).toContain('Proposer')
    expect(steps[1]?.textContent).toContain('Aggregator')
    expect(lineup.querySelector('.setup-model-strategy__handoff')).toBeNull()
    expect(lineup.textContent!.indexOf('Proposer')).toBeLessThan(lineup.textContent!.indexOf('Aggregator'))
    expect(el.querySelector('[data-testid="ensemble-custom-aggregator-inherited"]')?.textContent)
      .toContain('deepseek/deepseek-v4-pro')
    expect(steps[0]?.textContent).toContain('Proposers')
    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.textContent).not.toContain('Primary')
    expect(el.textContent).not.toContain('Contrast')
    expect(el.textContent).not.toContain('Fast check')
    expect(el.textContent).not.toContain('Critic')
    expect(el.textContent).not.toContain('No role')
    expect(el.querySelector('select[aria-label^="Role for"]')).toBeNull()
    expect(el.querySelector('option[value="primary"], option[value="contrast"], option[value="fast_check"], option[value="critic"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-below-minimum"]')).toBeTruthy()
    expect(el.querySelector('[data-testid="ensemble-effective-summary"]')?.textContent)
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

      const detail = el.querySelector('.setup-model-strategy__detail')?.textContent || ''
      expect(detail).toContain('deepseek/deepseek-v4-flash')
      if (activeStrategy !== 'ensemble') {
        expect(detail).not.toContain('deepseek/deepseek-v4-pro')
      }

      app.unmount()
    },
  )

  it('adds and imports proposers without assigning an advisory role', async () => {
    const onAddEnsembleCandidate = vi.fn()
    const onImportEnsembleTierCandidates = vi.fn()
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
        onImportEnsembleTierCandidates,
      },
    )

    expect(el.textContent).toContain('DeepSeek · deepseek-v4-pro')
    expect(el.textContent).toContain('Connected')

    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate-trigger"]')?.click()
    await nextTick()

    const provider = el.querySelector<HTMLElement>('[aria-label="Candidate provider"]')
    expect(provider?.getAttribute('aria-readonly')).toBe('true')
    expect(provider?.textContent).toContain('OpenRouter')
    const add = el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate"]')
    expect(add?.disabled).toBe(true)

    const model = el.querySelector<HTMLInputElement>('input[name="setup_provider_ensemble_candidate_model"]')
    model!.value = 'claude-opus'
    model!.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    expect(add?.disabled).toBe(false)
    add?.click()
    await nextTick()
    expect(onAddEnsembleCandidate).toHaveBeenCalledWith('openrouter', 'claude-opus', '')

    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-import-tiers"]')?.click()
    await nextTick()
    expect(onImportEnsembleTierCandidates).toHaveBeenCalledOnce()

    app.unmount()
  })

  it('copies a proposer into the aggregator slot and replaces a proposer atomically', async () => {
    const onAddEnsembleCandidate = vi.fn()
    const onRemoveEnsembleCandidate = vi.fn()
    const onReplaceEnsembleCandidate = vi.fn()
    const onSetEnsembleAggregator = vi.fn()
    const customCandidate = {
      key: 'custom:proposer:deepseek:deepseek-v4-pro',
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      role: 'critic',
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
        onReplaceEnsembleCandidate,
        onSetEnsembleAggregator,
      },
    )

    const actions = el.querySelector<HTMLDetailsElement>('.setup-model-strategy__candidate-actions')!
    actions.open = true
    await nextTick()
    actions.querySelector<HTMLButtonElement>('[data-testid="ensemble-promote-aggregator"]')?.click()
    await nextTick()
    expect(onSetEnsembleAggregator).toHaveBeenCalledWith(
      customCandidate.provider,
      customCandidate.model,
    )
    expect(actions.open).toBe(false)

    actions.open = true
    actions.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-proposer"]')?.click()
    await nextTick()
    expect(el.querySelector('[data-testid="ensemble-replace-proposer-editor"]')).toBeTruthy()
    const replacement = el.querySelector<HTMLInputElement>(
      'input[name="setup_provider_ensemble_candidate_replacement"]',
    )!
    replacement.value = 'deepseek-v4-next'
    replacement.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-proposer-confirm"]')?.click()
    await nextTick()

    expect(onReplaceEnsembleCandidate).toHaveBeenCalledWith(
      customCandidate,
      'deepseek-v4-next',
    )
    expect(onRemoveEnsembleCandidate).not.toHaveBeenCalled()
    expect(onAddEnsembleCandidate).not.toHaveBeenCalled()

    app.unmount()
  })

  it('blocks replacing a proposer with a duplicate from the same provider', async () => {
    const onReplaceEnsembleCandidate = vi.fn()
    const first = {
      key: 'custom:proposer:deepseek:deepseek-v4-pro',
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      role: 'primary',
    }
    const duplicate = {
      key: 'custom:proposer:deepseek:deepseek-v4-flash',
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      source: 'custom',
      enabled: true,
      role: '',
    }
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: {
          enabled: true,
          scheme: 'custom',
          custom: customLineup({
            proposers: [first, duplicate],
            proposerCount: 2,
            belowMinimum: false,
          }),
        },
      },
      { onReplaceEnsembleCandidate },
    )

    const actions = el.querySelector<HTMLDetailsElement>('.setup-model-strategy__candidate-actions')!
    actions.open = true
    actions.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-proposer"]')?.click()
    await nextTick()

    const replacement = el.querySelector<HTMLInputElement>(
      'input[name="setup_provider_ensemble_candidate_replacement"]',
    )!
    replacement.value = duplicate.model
    replacement.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    expect(el.querySelector('[data-testid="ensemble-replacement-duplicate"]')?.textContent)
      .toContain('already in the proposer list')
    const confirm = el.querySelector<HTMLButtonElement>(
      '[data-testid="ensemble-replace-proposer-confirm"]',
    )!
    expect(confirm.disabled).toBe(true)
    confirm.click()
    await nextTick()
    expect(onReplaceEnsembleCandidate).not.toHaveBeenCalled()

    app.unmount()
  })

  it('keeps add, replace, and aggregator editors mutually exclusive', async () => {
    const proposer = {
      key: 'custom:proposer:openrouter:anthropic/claude-sonnet',
      provider: 'openrouter',
      model: 'anthropic/claude-sonnet',
      source: 'custom',
      enabled: true,
      role: '',
    }
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        scheme: 'custom',
        custom: customLineup({ proposers: [proposer], proposerCount: 1 }),
      },
    })

    el.querySelector<HTMLButtonElement>(
      '[data-testid="setup-model-strategy-add-candidate-trigger"]',
    )?.click()
    await nextTick()
    expect(el.querySelector('[data-testid="ensemble-add-proposer-editor"]')).toBeTruthy()

    const actions = el.querySelector<HTMLDetailsElement>('.setup-model-strategy__candidate-actions')!
    actions.open = true
    actions.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-proposer"]')?.click()
    await nextTick()
    expect(el.querySelector('[data-testid="ensemble-add-proposer-editor"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-replace-proposer-editor"]')).toBeTruthy()

    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-aggregator"]')?.click()
    await nextTick()
    expect(el.querySelector('[data-testid="ensemble-replace-proposer-editor"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-aggregator-picker"]')).toBeTruthy()

    el.querySelector<HTMLButtonElement>(
      '[data-testid="setup-model-strategy-add-candidate-trigger"]',
    )?.click()
    await nextTick()
    expect(el.querySelector('[data-testid="ensemble-aggregator-picker"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-add-proposer-editor"]')).toBeTruthy()

    app.unmount()
  })

  it('replaces the aggregator from a proposer or another model', async () => {
    const onSetEnsembleAggregator = vi.fn()
    const proposer = {
      key: 'custom:proposer:openrouter:anthropic/claude-sonnet',
      provider: 'openrouter',
      model: 'anthropic/claude-sonnet',
      source: 'custom',
      enabled: true,
      role: '',
      credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
    }
    const aggregator = {
      key: 'custom:aggregator:openrouter:deepseek/deepseek-v4-pro',
      provider: 'openrouter',
      model: 'deepseek/deepseek-v4-pro',
      source: 'custom',
      enabled: true,
      role: 'aggregator',
      credential: { provider: 'openrouter', available: true, source: 'env', envKey: 'OPENROUTER_API_KEY' },
    }
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: {
          enabled: true,
          scheme: 'custom',
          custom: customLineup({
            aggregator,
            aggregatorInherited: false,
            proposers: [proposer],
            proposerCount: 1,
          }),
        },
      },
      { onSetEnsembleAggregator },
    )

    const replace = el.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-aggregator"]')!
    replace.click()
    await nextTick()
    const picker = el.querySelector<HTMLElement>('[data-testid="ensemble-aggregator-picker"]')!
    expect(picker).toBeTruthy()
    picker.querySelector<HTMLButtonElement>('[data-testid="ensemble-aggregator-option"]')?.click()
    await nextTick()
    expect(onSetEnsembleAggregator).toHaveBeenCalledWith(proposer.provider, proposer.model)

    replace.click()
    await nextTick()
    const model = el.querySelector<HTMLInputElement>(
      'input[name="setup_provider_ensemble_aggregator_model"]',
    )!
    model.value = 'google/gemini-next'
    model.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-set-aggregator"]')?.click()
    await nextTick()
    expect(onSetEnsembleAggregator).toHaveBeenLastCalledWith(
      'openrouter',
      'google/gemini-next',
    )

    app.unmount()
  })

  it('allows the same model id to become aggregator when the provider changes', async () => {
    const onSetEnsembleAggregator = vi.fn()
    const aggregator = {
      key: 'custom:aggregator:openrouter:shared-model',
      provider: 'openrouter',
      model: 'shared-model',
      source: 'custom',
      enabled: true,
      role: 'aggregator',
    }
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: {
          enabled: true,
          activeProvider: 'tokenrhythm',
          scheme: 'custom',
          custom: customLineup({
            aggregator,
            aggregatorInherited: false,
            inheritedAggregatorProvider: 'tokenrhythm',
          }),
        },
      },
      { onSetEnsembleAggregator },
    )

    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-replace-aggregator"]')?.click()
    await nextTick()
    const model = el.querySelector<HTMLInputElement>(
      'input[name="setup_provider_ensemble_aggregator_model"]',
    )!
    model.value = 'shared-model'
    model.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    const submit = el.querySelector<HTMLButtonElement>(
      '[data-testid="setup-model-strategy-set-aggregator"]',
    )!
    expect(submit.disabled).toBe(false)
    submit.click()
    await nextTick()
    expect(onSetEnsembleAggregator).toHaveBeenCalledWith('tokenrhythm', 'shared-model')

    app.unmount()
  })

  it('updates the success threshold and failure policy from runtime strategy', async () => {
    const onUpdateEnsembleMinSuccessful = vi.fn()
    const onUpdateEnsembleAllFailedPolicy = vi.fn()
    const { app, el } = await mountPanel(
      {
        activeStrategy: 'ensemble',
        ensemble: { enabled: true, scheme: 'custom' },
      },
      { onUpdateEnsembleMinSuccessful, onUpdateEnsembleAllFailedPolicy },
    )

    const runtime = el.querySelector<HTMLDetailsElement>('[data-testid="ensemble-runtime-strategy"]')!
    expect(runtime.open).toBe(false)
    runtime.querySelector('summary')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(runtime.open).toBe(true)

    const threshold = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_min_successful"]')!
    threshold.value = '2'
    threshold.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onUpdateEnsembleMinSuccessful).toHaveBeenCalledWith(2)

    const failure = el.querySelector<HTMLSelectElement>('select[name="setup_model_strategy_all_failed_policy"]')
    failure!.value = 'error'
    failure!.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(onUpdateEnsembleAllFailedPolicy).toHaveBeenCalledWith('error')

    app.unmount()
  })

  it('clamps an oversized stored threshold to the displayed proposer count', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      ensemble: {
        enabled: true,
        scheme: 'custom',
        minSuccessfulProposers: 5,
        custom: customLineup({
          proposerCount: 2,
          facts: { ...FACTS, proposerCount: 2, quorum: 2 },
        }),
      },
    })

    const threshold = el.querySelector<HTMLSelectElement>(
      'select[name="setup_model_strategy_min_successful"]',
    )!
    expect(threshold.value).toBe('2')
    expect(threshold.selectedOptions[0]?.textContent).toContain('2 of 2')

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
    expect(el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate-trigger"]')?.disabled).toBe(true)
    expect(el.querySelector('[data-testid="ensemble-add-proposer-editor"]')).toBeNull()

    app.unmount()
  })

  it('keeps the preset lineup read-only while allowing a switch to custom', async () => {
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

    expect(el.textContent).toContain('deepseek/deepseek-v4-pro')
    expect(el.textContent).toContain('moonshotai/kimi-k2.7-code')
    expect(el.textContent).toContain('Aggregator')
    const preset = el.querySelector<HTMLElement>('[data-testid="ensemble-preset-lineup"]')!
    const steps = preset.querySelectorAll<HTMLElement>('.setup-model-strategy__step')
    expect(steps).toHaveLength(2)
    expect(steps[0]?.textContent).toContain('Proposer')
    expect(steps[1]?.textContent).toContain('Aggregator')
    expect(preset.querySelector('.setup-model-strategy__handoff')).toBeNull()
    expect(preset.querySelector('.setup-model-strategy__candidate-actions')).toBeNull()
    expect(preset.querySelector('[data-testid="setup-model-strategy-add-candidate-trigger"]')).toBeNull()
    expect(preset.querySelector('[data-testid="ensemble-replace-aggregator"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-effective-summary"]')?.textContent).toContain('5 model calls')
    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')?.getAttribute('aria-checked')).toBe('true')
    el.querySelector<HTMLButtonElement>('[data-testid="ensemble-scheme-custom"]')?.click()
    await nextTick()
    expect(onUpdateEnsembleScheme).toHaveBeenCalledWith('custom')
    expect(el.textContent).not.toContain('legacy OpenRouter candidate template')
    expect(el.querySelector('.setup-model-strategy__candidate-provider-lock')).toBeNull()

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
    // Legacy dynamic selection has different runtime semantics, so it stays
    // read-only until the user explicitly migrates to a custom lineup.
    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-custom-lineup"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-effective-summary"]')).toBeNull()
    expect(el.querySelector('[data-testid="ensemble-runtime-strategy"]')).toBeNull()
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
        activeProvider: 'deepseek',
        scheme: 'custom',
        schemeCardsAvailable: false,
        custom: customLineup({ inheritedAggregatorProvider: 'deepseek', inheritedAggregatorModel: 'deepseek-v4-pro' }),
      },
    })

    expect(el.querySelector('[data-testid="ensemble-scheme-preset"]')).toBeNull()
    expect(el.textContent).not.toContain('OpenRouter fixed ensemble')
    expect(el.textContent).toContain('Proposers')
    expect(el.querySelector('.setup-model-strategy__candidate-provider-lock')).toBeNull()
    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate-trigger"]')?.click()
    await nextTick()
    const provider = el.querySelector<HTMLElement>('.setup-model-strategy__candidate-provider-lock')
    expect(provider?.textContent).toContain('DeepSeek')
    expect(el.querySelector('input[name="setup_model_strategy_add_candidate_provider"]')).toBeNull()

    app.unmount()
  })

  it('uses the active provider live catalog for new ensemble candidates', async () => {
    const { app, el } = await mountPanel({
      activeStrategy: 'ensemble',
      router: {
        discoveredModelsByProvider: {
          openrouter: {
            source: 'live',
            models: [{
              id: 'anthropic/claude-sonnet',
              name: 'Claude Sonnet',
              contextWindow: 200000,
              maxOutputTokens: 8192,
              capabilities: ['chat', 'tools'],
              pricing: null,
              capabilitySource: 'provider',
            }],
          },
        },
      },
      ensemble: {
        enabled: true,
        scheme: 'custom',
      },
    })

    expect(el.querySelector('input[name="setup_provider_ensemble_candidate_model"]')).toBeNull()
    el.querySelector<HTMLButtonElement>('[data-testid="setup-model-strategy-add-candidate-trigger"]')?.click()
    await nextTick()
    const model = el.querySelector<HTMLInputElement>('input[name="setup_provider_ensemble_candidate_model"]')
    expect(model?.getAttribute('role')).toBe('combobox')
    expect(model?.classList.contains('control-input')).toBe(true)
    model?.dispatchEvent(new Event('focus'))
    await nextTick()
    expect(document.body.textContent).toContain('anthropic/claude-sonnet')

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
        hasMixedTierProviders: true,
      },
    })

    expect(el.textContent).toContain('Cross-provider routing')

    app.unmount()
  })
})
