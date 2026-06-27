import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'
const SESSION_KEY = 'agent:main:webchat:e2efork'
const FORK_BUTTON = '[data-testid="fork-conversation"]'

function sessionFromUrl(url: string): string {
  try {
    return new URL(url).searchParams.get('session') || ''
  } catch {
    return ''
  }
}

// Seed a settled two-turn thread through the real WS pipeline: chat.history
// responses are rewritten in flight so two assistant messages render without
// a live agent run.
async function seedHistoryWithTwoTurns(page: Page) {
  await page.routeWebSocket(/\/ws$/, ws => {
    const server = ws.connectToServer()
    const historyIds = new Set<string>()
    ws.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type === 'req' && frame.method === 'chat.history') {
          historyIds.add(String(frame.id))
        }
      } catch {}
      server.send(message)
    })
    server.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type === 'res' && frame.id !== undefined && historyIds.has(String(frame.id))) {
          historyIds.delete(String(frame.id))
          frame.ok = true
          delete frame.error
          frame.payload = {
            messages: [
              {
                role: 'user',
                text: 'First question.',
                id: 'msg-e2e-fork-user-1',
                timestamp: Math.floor(Date.now() / 1000) - 120,
              },
              {
                role: 'assistant',
                text: 'First answer.',
                id: 'msg-e2e-fork-ai-1',
                timestamp: Math.floor(Date.now() / 1000) - 110,
                usage: { model: 'openai/gpt-test', input_tokens: 20, output_tokens: 8, cost_usd: 0.0002 },
              },
              {
                role: 'user',
                text: 'Second question.',
                id: 'msg-e2e-fork-user-2',
                timestamp: Math.floor(Date.now() / 1000) - 60,
              },
              {
                role: 'assistant',
                text: 'Second answer.',
                id: 'msg-e2e-fork-ai-2',
                timestamp: Math.floor(Date.now() / 1000) - 50,
                usage: { model: 'openai/gpt-test', input_tokens: 30, output_tokens: 10, cost_usd: 0.0003 },
              },
            ],
            has_more: false,
          }
          ws.send(JSON.stringify(frame))
          return
        }
      } catch {}
      ws.send(message)
    })
  })
}

test.describe('Conversation fork', () => {
  test('empty draft offers no fork action', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.chat-textarea')).toBeVisible()
    await expect(page.locator(FORK_BUTTON)).toHaveCount(0)
  })

  test('fork renders only on the last assistant message of the thread', async ({ page }) => {
    await seedHistoryWithTwoTurns(page)
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.msg-ai')).toHaveCount(2, { timeout: 10000 })
    // Whole-conversation fork: one button on the tip, none on earlier turns.
    await expect(page.locator(FORK_BUTTON)).toHaveCount(1)
    await expect(page.locator('.msg-ai').last().locator(FORK_BUTTON)).toHaveCount(1)
    await expect(page.locator('.msg-ai').first().locator(FORK_BUTTON)).toHaveCount(0)
    await expect(page.locator(FORK_BUTTON)).toHaveAttribute('aria-label', 'Fork conversation')
    // The retired follow-up row stays gone.
    await expect(page.locator('.done-card')).toHaveCount(0)
  })

  test('live fork copies the thread into a new session with hub lineage', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(300000)

    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    // One real turn so the session exists with a transcript.
    const prompt = 'Reply with the single word: ok'
    await page.locator('.chat-textarea').fill(prompt)
    await page.locator('.chat-send-btn[aria-label="Send"]').click()
    await expect(page.locator('.msg-ai').first()).toBeVisible({ timeout: 120000 })
    await expect(page.locator('.work-card')).toHaveCount(0, { timeout: 120000 })

    const parentKey = sessionFromUrl(page.url())
    expect(parentKey).toMatch(/^agent:.+:webchat:/)

    // No done card after completion; the fork action sits in the meta cluster
    // of the tip message.
    await expect(page.locator('.done-card')).toHaveCount(0)
    const tip = page.locator('.msg-ai').last()
    await tip.hover()
    await expect(tip.locator(FORK_BUTTON)).toHaveCount(1)
    await tip.locator(FORK_BUTTON).click()

    // Navigation lands on a NEW session key.
    await page.waitForURL(url => {
      const key = sessionFromUrl(url.toString())
      return !!key && key !== parentKey
    }, { timeout: 30000 })
    const childKey = sessionFromUrl(page.url())
    expect(childKey).toMatch(/^agent:.+:webchat:/)
    expect(childKey).not.toBe(parentKey)

    // The child thread shows the copied messages.
    await expect(page.locator('.msg-user').filter({ hasText: prompt })).toBeVisible({ timeout: 30000 })
    await expect(page.locator('.msg-ai').first()).toBeVisible()

    // Hub: the fork lists under its parent with the FORK badge and indent,
    // and the parent still lists independently as a root row.
    await page.goto(CONTROL_URL + 'sessions')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await page.waitForTimeout(800)
    await expect(page.locator('.hub-ledger')).toBeVisible()

    const titleFragment = 'Reply with the single word'
    const forkRow = page.locator('.hub-row--child')
      .filter({ has: page.locator('.hub-row__fork-badge') })
      .filter({ hasText: titleFragment })
      .first()
    await expect(forkRow).toBeVisible({ timeout: 15000 })
    await expect(forkRow.locator('.hub-row__fork-badge')).toHaveText(/fork/i)
    expect((await forkRow.locator('.hub-row__title').innerText()).trim().startsWith('↳ ')).toBe(true)

    // Indented under the parent like the rest of the lineage language.
    const childPad = await forkRow.locator('.hub-row__main').evaluate(
      el => parseFloat(getComputedStyle(el as HTMLElement).paddingLeft))
    const rootPad = await page.locator('.hub-row:not(.hub-row--child) .hub-row__main').first().evaluate(
      el => parseFloat(getComputedStyle(el as HTMLElement).paddingLeft))
    expect(childPad).toBeGreaterThan(rootPad)

    // Parent row remains an independent root entry.
    const parentRow = page.locator('.hub-row:not(.hub-row--child)').filter({ hasText: titleFragment })
    await expect(parentRow.first()).toBeVisible()
  })
})
