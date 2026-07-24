import { expect, test, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2e-assistant-activity'

interface ActivityFixture {
  failed?: boolean
}

async function mockActivityHistory(page: Page, fixture: ActivityFixture = {}) {
  await page.routeWebSocket(/\/ws$/, ws => {
    ws.onMessage(message => {
      let frame: Record<string, unknown>
      try {
        frame = JSON.parse(String(message)) as Record<string, unknown>
      } catch {
        return
      }
      if (frame.type !== 'req' || frame.id === undefined) return
      if (frame.method === 'connect') {
        ws.send(JSON.stringify({ protocol: 3, policy: {} }))
        return
      }
      if (frame.method === 'chat.history') {
        ws.send(JSON.stringify({
          type: 'res',
          id: frame.id,
          ok: true,
          payload: {
            messages: [{
              role: 'assistant',
              text: 'The canonical answer is complete.',
              id: `assistant-activity-${fixture.failed ? 'failed' : 'success'}`,
              timestamp: Math.floor(Date.now() / 1000) - 30,
              reasoning_content: 'I compared the available evidence before answering.',
              tool_calls: [{
                tool_use_id: 'activity-search',
                name: 'web_search',
                groupId: 'activity-group',
                input: { query: 'OpenSquilla activity' },
                result: fixture.failed ? 'Search service unavailable' : 'One verified result',
                is_error: fixture.failed === true,
                execution_status: { status: fixture.failed ? 'error' : 'success' },
              }],
              timeline: [
                { type: 'text', raw: 'Non-canonical streamed prefix.' },
                { type: 'tool-group', groupId: 'activity-group' },
                { type: 'text', raw: 'Non-canonical streamed suffix.' },
              ],
            }],
            has_more: false,
          },
        }))
        return
      }
      ws.send(JSON.stringify({ type: 'res', id: frame.id, ok: true, payload: {} }))
    })
    ws.send(JSON.stringify({ type: 'event', event: 'connect.challenge', payload: {} }))
  })
}

test.describe('Completed assistant activity disclosure', () => {
  test('keeps the canonical answer visible and supports keyboard disclosure', async ({ page }) => {
    await mockActivityHistory(page)
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const activity = page.getByTestId('assistant-activity')
    await expect(activity).toBeVisible()
    await expect(activity).not.toHaveAttribute('open', '')
    await expect(activity).toContainText('Activity · 2 steps')

    const answer = page.locator('.msg-ai-text')
    await expect(answer).toBeVisible()
    await expect(answer).toHaveText('The canonical answer is complete.')
    await expect(page.getByText('Non-canonical streamed prefix.')).toHaveCount(0)
    await expect(page.getByText('Non-canonical streamed suffix.')).toHaveCount(0)

    const row = activity.locator('.tool-row[data-op="web.search"]')
    await expect(row).toBeHidden()

    const summary = activity.locator('summary')
    await summary.press('Enter')
    await expect(activity).toHaveAttribute('open', '')
    await expect(row).toBeVisible()
    await expect(activity.locator('.thinking-block__body')).toContainText(
      'I compared the available evidence before answering.',
    )

    await summary.press('Space')
    await expect(activity).not.toHaveAttribute('open', '')
    expect(await summary.evaluate(element => document.activeElement === element)).toBe(true)
    await expect(answer).toBeVisible()
  })

  test('opens failures by default and keeps the full error visible', async ({ page }) => {
    await mockActivityHistory(page, { failed: true })
    await page.setViewportSize({ width: 320, height: 844 })
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(`${SESSION_KEY}-failed`))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const activity = page.getByTestId('assistant-activity')
    await expect(activity).toBeVisible()
    await expect(activity).toHaveAttribute('open', '')
    await expect(activity).toContainText('1 failed')

    const errorRow = activity.locator('.tool-row--error')
    await expect(errorRow).toBeVisible()
    await expect(errorRow).toHaveAttribute('aria-expanded', 'true')
    await expect(activity.locator('.tool-row-section--error')).toContainText(
      'Search service unavailable',
    )
    await expect(page.locator('.msg-ai-text')).toHaveText('The canonical answer is complete.')

    const summary = activity.locator('summary')
    await activity.locator('.assistant-activity__label').evaluate((element) => {
      element.textContent = 'Sehr lange lokalisierte Aktivitätszusammenfassung'
    })
    const summaryOverflow = await summary.evaluate(element =>
      element.scrollWidth - element.clientWidth,
    )
    expect(summaryOverflow).toBeLessThanOrEqual(1)
  })
})
