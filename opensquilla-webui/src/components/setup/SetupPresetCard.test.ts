// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupPresetCard from './SetupPresetCard.vue'

function panel(overrides: Record<string, unknown> = {}) {
  return {
    presetLabel: 'DeepSeek balanced tiers',
    presetDescription: 'A curated tier split for DeepSeek models.',
    synthesized: false,
    tierRows: [
      {
        name: 'c0',
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        thinkingLevel: '',
        supportsImage: false,
      },
    ],
    tierLabel: (tier: string) => tier,
    routerMode: 'recommended',
    routerCustomized: false,
    ...overrides,
  }
}

async function mountCard(props: Record<string, unknown> = {}, listeners: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupPresetCard, { panel: panel(props), ...listeners })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

function toggle(el: HTMLElement): HTMLButtonElement | null {
  return el.querySelector<HTMLButtonElement>('[data-testid="setup-preset-toggle"]')
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SetupPresetCard — routing template summary', () => {
  it('shows a routing template summary with direct apply, while keeping tier details collapsed', async () => {
    const { app, el } = await mountCard()

    expect(el.textContent).toContain('Routing template: DeepSeek balanced tiers')
    expect(el.textContent).toContain('Apply once to fill Model Routing; edit the active tiers there.')
    expect(toggle(el)?.textContent).toContain('View template details')
    expect(toggle(el)?.getAttribute('aria-expanded')).toBe('false')
    expect(el.querySelector('[role="table"]')).toBeNull()
    expect(el.querySelector('[data-testid="setup-preset-apply"]')?.textContent).toContain('Apply to Model Routing')

    app.unmount()
  })

  it('labels synthesized presets without default decoration', async () => {
    const { app, el } = await mountCard({ synthesized: true, presetLabel: 'Groq default' })

    expect(el.textContent).toContain('Routing template: Generated routing template')
    expect(el.textContent).not.toContain('Groq default')

    app.unmount()
  })
})

describe('SetupPresetCard — expanded', () => {
  it('reveals the description, the read-only tier preview, and one primary action', async () => {
    const { app, el } = await mountCard()

    toggle(el)?.click()
    await nextTick()

    expect(toggle(el)?.getAttribute('aria-expanded')).toBe('true')
    expect(el.textContent).toContain('A curated tier split for DeepSeek models.')
    expect(el.querySelector('[role="table"]')).toBeTruthy()
    // Read-only preview: the model cell is text, not an input.
    expect(el.querySelector('[aria-label="c0 model"]')?.tagName).toBe('SPAN')
    expect(el.querySelector('[data-testid="setup-preset-apply"]')?.textContent).toContain('Apply to Model Routing')

    app.unmount()
  })

  it('shows the synthesized badge only for synthesized presets', async () => {
    const synthesized = await mountCard({ synthesized: true })
    toggle(synthesized.el)?.click()
    await nextTick()
    expect(synthesized.el.querySelector('[data-testid="setup-preset-synthesized-badge"]')).toBeTruthy()
    synthesized.app.unmount()

    const curated = await mountCard()
    toggle(curated.el)?.click()
    await nextTick()
    expect(curated.el.querySelector('[data-testid="setup-preset-synthesized-badge"]')).toBeNull()
    curated.app.unmount()
  })

  it('emits apply when "Apply to Model Routing" is clicked', async () => {
    const onApply = vi.fn()
    const { app, el } = await mountCard({}, { onApply })

    el.querySelector<HTMLButtonElement>('[data-testid="setup-preset-apply"]')?.click()

    expect(onApply).toHaveBeenCalledTimes(1)
    app.unmount()
  })
})

describe('SetupPresetCard — router configured beyond defaults', () => {
  it('reflects the actual mode, links to the Router section, and never offers apply', async () => {
    const onGoToSection = vi.fn()
    const { app, el } = await mountCard(
      { routerCustomized: true, routerMode: 'custom' },
      { onGoToSection },
    )

    expect(el.textContent).toContain('Model Routing already uses custom tiers.')
    expect(el.textContent).toContain('Active tiers are edited in Model Routing.')
    expect(toggle(el)).toBeNull()
    expect(el.querySelector('[data-testid="setup-preset-apply"]')).toBeNull()

    const link = el.querySelector<HTMLButtonElement>('[data-testid="setup-preset-router-link"]')
    expect(link?.textContent).toContain('Open Model Routing')
    link?.click()
    expect(onGoToSection).toHaveBeenCalledWith('modelStrategy')

    app.unmount()
  })

  it('labels legacy openrouter-mix as custom tiers', async () => {
    const mix = await mountCard({ routerCustomized: true, routerMode: 'openrouter-mix' })
    expect(mix.el.textContent).toContain('custom')
    expect(mix.el.textContent).not.toContain('OpenRouter aggregated')
    mix.app.unmount()
  })

  it('labels disabled routing as off', async () => {
    const disabled = await mountCard({ routerCustomized: true, routerMode: 'disabled' })
    expect(disabled.el.textContent).toContain('Model Routing already uses off.')
    disabled.app.unmount()
  })
})
