// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupRouterPanel from './SetupRouterPanel.vue'

function panel(overrides = {}) {
  return {
    routerSummary: 'Follow current provider tiers',
    routerMode: 'openrouter-mix',
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
  it('renders clearer router mode labels', async () => {
    const { app, el } = await mountRouterPanel()
    const options = Array.from(el.querySelectorAll('select[name="setup_router_mode"] option'))
      .map((option) => option.textContent || '')

    expect(options).toEqual([
      'Follow current provider tiers',
      'OpenRouter aggregated model tiers',
      'Direct single model',
    ])
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
})
