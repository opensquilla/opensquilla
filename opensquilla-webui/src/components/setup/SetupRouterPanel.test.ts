// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupRouterPanel from './SetupRouterPanel.vue'

function panel(overrides: Record<string, unknown> = {}) {
  const routerMode = String(overrides.routerMode ?? 'openrouter-mix')
  return {
    routerSummary: 'Follow current provider tiers',
    routerMode,
    routerModeChoice: routerMode === 'disabled' ? 'disabled' : 'recommended',
    routerConfigDisabled: routerMode === 'disabled',
    routerDefaultTier: 'c1',
    routerVisualMode: 'real_candidates',
    routerVisualModeDirty: false,
    routerVisualModeOptions: [{ value: 'real_candidates', label: 'Real routing candidates' }],
    hasSavedProvider: true,
    ensembleProfileActive: false,
    canUseOpenrouterMix: true,
    textTiers: ['c0', 'c1'],
    tierRows: [
      {
        name: 'c0',
        provider: 'openrouter',
        model: 'deepseek/deepseek-v4-flash',
        thinkingLevel: 'high',
        supportsImage: false,
      },
    ],
    tierLabel: (tier: string) => tier,
    ...overrides,
  }
}

async function mountRouterPanel(props = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupRouterPanel, { panel: panel(props) })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SetupRouterPanel', () => {
  it('renders only the two setup-level router mode choices', async () => {
    const { app, el } = await mountRouterPanel({
      routerMode: 'openrouter-mix',
      routerModeChoice: 'recommended',
      canUseOpenrouterMix: true,
    })
    const options = Array.from(el.querySelectorAll('select[name="setup_router_mode"] option'))
      .map((option) => option.textContent || '')

    expect(options).toEqual(['Model routing', 'Single model'])
    expect(options).not.toContain('OpenRouter aggregated model tiers')
    app.unmount()
  })

  it('shows the tier request entry as read-only while leaving model editable', async () => {
    const { app, el } = await mountRouterPanel()

    const requestEntry = el.querySelector('[aria-label="c0 request entry"]')
    expect(requestEntry?.tagName).toBe('SPAN')
    expect(requestEntry?.textContent).toBe('openrouter')
    expect(el.querySelector('input[aria-label="c0 request entry"]')).toBeNull()
    expect(el.querySelector('input[aria-label="c0 model"]')).toBeTruthy()

    app.unmount()
  })

  it('shows the LLM ensemble routing profile note when that mode is active', async () => {
    const { app, el } = await mountRouterPanel({ ensembleProfileActive: true })

    expect(el.textContent).toContain('LLM ensemble routing profile')
    expect(el.textContent).toContain('The tier table supplies candidate models for the ensemble router.')

    app.unmount()
  })

  it('disables router configuration controls in single-model mode', async () => {
    const { app, el } = await mountRouterPanel({
      routerMode: 'disabled',
      routerModeChoice: 'disabled',
      routerConfigDisabled: true,
    })

    expect(el.textContent).toContain('Enable model routing to edit tier configuration.')
    expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_default_tier"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_visual_mode"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.disabled).toBe(true)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(true)
    expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBe('true')

    app.unmount()
  })

  it('keeps router configuration controls editable in model-routing mode', async () => {
    const { app, el } = await mountRouterPanel({
      routerMode: 'recommended',
      routerModeChoice: 'recommended',
      routerConfigDisabled: false,
    })

    expect(el.textContent).not.toContain('Enable model routing to edit tier configuration.')
    expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_default_tier"]')?.disabled).toBe(false)
    expect(el.querySelector<HTMLSelectElement>('select[name="setup_router_visual_mode"]')?.disabled).toBe(false)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 model"]')?.disabled).toBe(false)
    expect(el.querySelector<HTMLSelectElement>('select[aria-label="c0 thinking level"]')?.disabled).toBe(false)
    expect(el.querySelector<HTMLInputElement>('input[aria-label="c0 supports image"]')?.disabled).toBe(false)
    expect(el.querySelector('[role="table"]')?.getAttribute('aria-disabled')).toBeNull()

    app.unmount()
  })
})
