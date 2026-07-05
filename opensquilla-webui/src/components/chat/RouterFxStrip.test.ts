// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import type { ChatRenderedMessage } from '@/types/chat'
import RouterFxStrip from './RouterFxStrip.vue'

function ensembleStrip(overrides: Partial<ChatRenderedMessage> = {}): ChatRenderedMessage {
  return {
    id: 'router-turn-1',
    role: 'router',
    displayRole: 'router',
    roleLabel: 'Router',
    text: '',
    timeStr: '',
    ts: null,
    showHeader: false,
    isRouterStrip: true,
    routerPanel: 'llm-ensemble',
    routerMode: 'llm_ensemble',
    routerSource: 'llm_ensemble',
    routerSettled: false,
    gridCells: [],
    winnerIdx: -1,
    messageId: 'router-empty-ensemble',
    ...overrides,
  }
}

async function mountStrip(message: ChatRenderedMessage) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(RouterFxStrip, { message })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('RouterFxStrip ensemble panel', () => {
  it('keeps an empty pending ensemble panel openable', async () => {
    const { app, el } = await mountStrip(ensembleStrip())

    const button = el.querySelector<HTMLButtonElement>('[data-testid="router-ensemble-toggle"]')
    expect(button).toBeTruthy()
    expect(button?.disabled).toBe(false)

    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(el.querySelector('[data-testid="router-ensemble-inspector"]')).toBeTruthy()
    expect(el.querySelector('[data-testid="router-ensemble-detail-unavailable"]')).toBeTruthy()
    expect(el.textContent).toContain('trace pending')
    expect(el.textContent).toContain('telemetry pending')
    expect(el.textContent).not.toContain('pool 0')
    expect(el.textContent).not.toContain('0 candidates')
    app.unmount()
  })

  it('shows handoff copy instead of selecting copy once the agent phase has started', async () => {
    const { app, el } = await mountStrip(ensembleStrip({ routerState: 'handoff' }))

    const button = el.querySelector<HTMLButtonElement>('[data-testid="router-ensemble-toggle"]')
    expect(button).toBeTruthy()
    expect(el.textContent).toContain('handed off to agent')
    expect(el.textContent).not.toContain('selecting candidates')

    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(el.querySelector('[data-testid="router-ensemble-inspector"]')).toBeTruthy()
    expect(el.textContent).toContain('trace unavailable')
    expect(el.textContent).not.toContain('trace pending')
    app.unmount()
  })
})
