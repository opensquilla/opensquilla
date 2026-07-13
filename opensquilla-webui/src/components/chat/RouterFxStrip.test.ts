// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick, reactive } from 'vue'
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

  it('shows candidate failures and waits for the aggregator before completing', async () => {
    const message = reactive(ensembleStrip({
      ensemble: {
        profile: 'llm_ensemble',
        modelCount: 2,
        totalCandidates: 2,
        requestCount: 3,
        fallbackUsed: false,
        fallbackReason: '',
        costUsd: 0,
        savedUsd: 0,
        savedPct: 0,
        models: [
          {
            role: 'proposer',
            label: 'anchor',
            provider: 'openrouter',
            model: 'qwen/qwen3.7-plus',
            modelShort: 'qwen3.7-plus',
            input: 100,
            output: 20,
            costUsd: 0,
            status: 'done',
            elapsedMs: 105_000,
          },
          {
            role: 'proposer',
            label: 'critic',
            provider: 'openrouter',
            model: 'z-ai/glm-5.2',
            modelShort: 'glm-5.2',
            input: 0,
            output: 0,
            costUsd: 0,
            status: 'failed',
            elapsedMs: 118_000,
            error: 'provider timed out',
          },
          {
            role: 'aggregator',
            label: 'aggregator',
            provider: 'openrouter',
            model: 'anthropic/claude-sonnet',
            modelShort: 'claude-sonnet',
            input: 0,
            output: 0,
            costUsd: 0,
            status: 'running',
          },
        ],
      },
    }))
    const { app, el } = await mountStrip(message)

    el.querySelector<HTMLButtonElement>('[data-testid="router-ensemble-toggle"]')
      ?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(el.querySelectorAll('[data-status="done"]')).toHaveLength(1)
    expect(el.querySelectorAll('[data-status="failed"]')).toHaveLength(1)
    expect(el.querySelectorAll('[data-status="running"]')).toHaveLength(1)
    expect(el.textContent).toContain('120 tok · 105s')
    expect(el.textContent).toContain('failed · 118s')
    expect(el.querySelector('[data-status="failed"] .router-fx-inspector__usage')?.getAttribute('title'))
      .toBe('provider timed out')
    expect(el.querySelector('.router-fx-ensemble__scan')).toBeTruthy()
    expect(el.textContent).toContain('2 candidates synthesizing')

    const aggregator = message.ensemble?.models.find(model => model.role === 'aggregator')
    if (!aggregator) throw new Error('expected aggregator row')
    aggregator.status = 'done'
    aggregator.input = 200
    aggregator.output = 40
    aggregator.elapsedMs = 12_000
    await nextTick()

    expect(el.textContent).toContain('240 tok · 12s')
    expect(el.textContent).toContain('2 candidates synthesized')
    expect(el.querySelector('.router-fx-ensemble__scan')).toBeFalsy()
    expect(el.querySelector('[data-testid="router-ensemble-toggle"]')?.getAttribute('aria-busy')).toBe('false')
    app.unmount()
  })
})
