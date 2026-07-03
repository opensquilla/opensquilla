import { expect, test, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2e-ensemble-router'
const STREAM_SESSION_KEY = 'agent:main:webchat:e2e-ensemble-router-streaming'

type Complexity = 'simple' | 'medium' | 'complex'

function wsResponse(id: string, payload: unknown) {
  return JSON.stringify({ type: 'res', id, ok: true, payload })
}

function wsEvent(event: string, payload: unknown) {
  return JSON.stringify({ type: 'event', event, payload })
}

function messagesFor(complexity: Complexity): Array<Record<string, unknown>> {
  const prompts: Record<Complexity, string> = {
    simple: 'Summarize why model routing matters in one sentence.',
    medium: 'Search today’s AI news and summarize the two most important updates.',
    complex: 'Compare recent AI policy, product, and research changes, then give an action plan.',
  }
  const answers: Record<Complexity, string> = {
    simple: 'Model routing chooses the right model path for a turn.',
    medium: 'The latest AI updates point to faster model releases and more safety scrutiny.',
    complex: 'Across policy, product, and research, the strongest action is to monitor regulation while testing model quality with staged rollout gates.',
  }
  return [
    {
      role: 'user',
      text: prompts[complexity],
      id: `${complexity}-user`,
      message_id: `${complexity}-user`,
      timestamp: Math.floor(Date.now() / 1000) - 90,
    },
    {
      role: 'assistant',
      text: answers[complexity],
      id: `${complexity}-assistant`,
      message_id: `${complexity}-assistant`,
      timestamp: Math.floor(Date.now() / 1000) - 30,
      tool_calls: complexity === 'simple'
        ? []
        : [
            {
              type: 'tool_use',
              tool_use_id: `${complexity}-search`,
              name: 'web_search',
              input: { query: prompts[complexity] },
            },
            {
              type: 'tool_result',
              tool_use_id: `${complexity}-search`,
              name: 'web_search',
              result: JSON.stringify({ results: [{ title: 'AI update', url: 'https://example.com/ai' }] }),
            },
          ],
      usage: {
        model: 'z-ai/glm-5.2',
        cost_usd: complexity === 'complex' ? 0.42 : 0.12,
        model_usage_breakdown: [
          {
            role: 'anchor',
            label: 'Anchor',
            provider: 'openrouter',
            model: 'qwen/qwen3.7-plus',
            input_tokens: 120,
            output_tokens: 30,
          },
          {
            role: 'research',
            label: 'Research',
            provider: 'openrouter',
            model: 'moonshotai/kimi-k2.6',
            input_tokens: 140,
            output_tokens: 42,
          },
          {
            role: 'critic',
            label: 'Critic',
            provider: 'openrouter',
            model: 'z-ai/glm-5.2',
            input_tokens: 90,
            output_tokens: 28,
          },
        ],
        ensemble_trace: {
          profile: 'default',
          mode: 'router_dynamic',
          llm_request_count: 3,
          total_candidates: 8,
          fallback_used: false,
        },
      },
    },
  ]
}

async function mockEnsembleHistory(page: Page, complexity: Complexity) {
  await page.addInitScript(() => {
    window.localStorage.setItem('opensquilla-locale', 'en')
    window.localStorage.setItem('opensquilla.routerVisualEffects', '1')
  })
  await page.route('**/api/approvals', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ pending: [] }),
  }))
  await page.routeWebSocket(/\/ws$/, ws => {
    ws.send(JSON.stringify({ type: 'event', event: 'connect.challenge', payload: {} }))
    ws.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type !== 'req') return
        const method = String(frame.method || '')
        if (method === 'connect') {
          ws.send(JSON.stringify({ protocol: 3, policy: { tick_interval_ms: 30000 } }))
          return
        }
        const payloads: Record<string, unknown> = {
          'agents.list': { agents: [] },
          'chat.history': { messages: messagesFor(complexity), has_more: false },
          'commands.list_for_surface': { commands: [] },
          'config.get': {
            squilla_router: { enabled: true, rollout_phase: 'full', tiers: {} },
            llm_ensemble: { enabled: true },
            permissions: {},
            skills: {},
          },
          'sessions.list': { sessions: [], has_more: false },
          'sessions.messages.subscribe': {
            subscribed: true,
            replay_complete: true,
            current_stream_seq: 0,
            run_status: 'idle',
          },
          'usage.status': { sessions: [] },
        }

        ws.send(wsResponse(String(frame.id), payloads[method] ?? {}))
      } catch {}
    })
  })
}

async function mockStreamingEnsembleRun(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('opensquilla-locale', 'en')
    window.localStorage.setItem('opensquilla.routerVisualEffects', '1')
  })
  await page.route('**/api/approvals', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ pending: [] }),
  }))
  await page.routeWebSocket(/\/ws$/, ws => {
    ws.send(JSON.stringify({ type: 'event', event: 'connect.challenge', payload: {} }))
    ws.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type !== 'req') return
        const method = String(frame.method || '')
        if (method === 'connect') {
          ws.send(JSON.stringify({ protocol: 3, policy: { tick_interval_ms: 30000 } }))
          return
        }
        if (method === 'chat.send') {
          ws.send(wsResponse(String(frame.id), {
            accepted: true,
            session: STREAM_SESSION_KEY,
            task_id: 'ensemble-stream-task',
            stream_seq: 1,
          }))
          ws.send(wsEvent('task.running', {
            key: STREAM_SESSION_KEY,
            task_id: 'ensemble-stream-task',
            stream_seq: 1,
          }))
          ws.send(wsEvent('session.event.state_change', {
            key: STREAM_SESSION_KEY,
            task_id: 'ensemble-stream-task',
            stream_seq: 2,
            to_state: 'thinking',
          }))
          return
        }
        const payloads: Record<string, unknown> = {
          'agents.list': { agents: [] },
          'chat.history': { messages: [], has_more: false },
          'commands.list_for_surface': { commands: [] },
          'config.get': {
            squilla_router: { enabled: true, rollout_phase: 'full', tiers: {} },
            llm_ensemble: { enabled: true },
            permissions: {},
            skills: {},
          },
          'sessions.list': { sessions: [], has_more: false },
          'sessions.messages.subscribe': {
            subscribed: true,
            replay_complete: true,
            current_stream_seq: 0,
            run_status: 'idle',
          },
          'usage.status': { sessions: [] },
        }

        ws.send(wsResponse(String(frame.id), payloads[method] ?? {}))
      } catch {}
    })
  })
}

for (const complexity of ['simple', 'medium', 'complex'] as const) {
  test(`completed ensemble trace stays in assistant meta for ${complexity} prompts`, async ({ page }) => {
    await mockEnsembleHistory(page, complexity)
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(`${SESSION_KEY}-${complexity}`))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.router-fx[data-panel="llm-ensemble"]')).toHaveCount(0)

    const assistant = page.locator('.msg-ai').first()
    await expect(assistant.locator('.msg-meta__ensemble')).toContainText('Ensemble · 3 models')
    await expect(assistant).not.toContainText('qwen3.7-plus')
    await expect(assistant).not.toContainText('kimi-k2.6')

    await assistant.locator('.msg-meta__more-btn').click()

    const details = assistant.locator('.msg-meta-popover')
    await expect(details).toBeVisible()
    await expect(details).toContainText('qwen3.7-plus')
    await expect(details).toContainText('kimi-k2.6')
    await expect(details).toContainText('glm-5.2')
  })
}

test('pending ensemble routing moves into the live work card once it is visible', async ({ page }) => {
  await mockStreamingEnsembleRun(page)
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(STREAM_SESSION_KEY))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })

  await page.locator('.chat-textarea').fill('Build a tiny team collaboration app.')
  await page.locator('.chat-send-btn[aria-label="Send"]').click()

  const workCard = page.locator('.work-card')
  await expect(workCard).toBeVisible({ timeout: 10000 })
  await expect(workCard.locator('.work-card__phase')).toContainText('AI model ensemble router')
  await expect(workCard.locator('.work-card__step')).toHaveText('ensemble')

  await expect(page.locator('.router-fx.router-fx-reserve')).toHaveCount(0)
  await expect(page.locator('.router-fx[data-panel="llm-ensemble"]:not([data-settled="true"])')).toHaveCount(0)
})
