import { expect, test, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2e-user-newlines'

async function seedMultilineUserHistory(page: Page) {
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
        if (frame.method === 'connect') {
          ws.send(JSON.stringify({
            protocol: 3,
            policy: { tick_interval_ms: 30000 },
          }))
          return
        }

        const payloads: Record<string, unknown> = {
          'agents.list': { agents: [] },
          'chat.history': {
            messages: [
              {
                role: 'user',
                text: '你好~\n我测试一下换行功能~\n你好~\n我测试一下换行功能~',
                id: 'msg-user-newlines',
                timestamp: Math.floor(Date.now() / 1000) - 60,
              },
            ],
            has_more: false,
          },
          'commands.list_for_surface': { commands: [] },
          'config.get': {
            squilla_router: { enabled: false, rollout_phase: 'observe', tiers: {} },
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

        ws.send(JSON.stringify({
          type: 'res',
          id: frame.id,
          ok: true,
          payload: payloads[String(frame.method)] ?? {},
        }))
      } catch {}
    })
  })
}

test('user message bubbles preserve authored line breaks', async ({ page }) => {
  await seedMultilineUserHistory(page)
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })

  const bubble = page.locator('.msg-user-bubble').first()
  await expect(bubble).toContainText('你好~\n我测试一下换行功能~\n你好~')
  await expect(bubble).toHaveCSS('white-space', 'pre-wrap')
})
