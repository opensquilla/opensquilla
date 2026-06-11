import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'

test.describe('Tool rows and activity ribbon', () => {
  test('idle chat renders no activity ribbon, elapsed badges, or result sheet', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.stream-activity')).toHaveCount(0)
    await expect(page.locator('.tool-row__elapsed')).toHaveCount(0)
    await expect(page.locator('.tool-sheet')).toHaveCount(0)
  })

  test('live search run narrates activity, ticks seconds, and collapses read rows', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const textarea = page.locator('.chat-textarea')
    await textarea.fill('Use your web search tool to find one recent headline about space exploration, then answer in one sentence.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    // Activity ribbon appears and carries narration, elapsed seconds, and round count.
    const ribbon = page.locator('.stream-activity')
    await expect(ribbon).toBeVisible({ timeout: 30000 })

    // The elapsed counter ticks: observe at least two distinct second values.
    // Sample fast and from the moment the ribbon appears (seconds start at 0,
    // and reset when the activity label changes) so a quick run cannot finish
    // before two values are seen.
    const secondsSeen = new Set<string>()
    await expect.poll(async () => {
      const text = await page.locator('.stream-activity-text').textContent().catch(() => null)
      const match = /(\d+)s\b/.exec(text || '')
      if (match) secondsSeen.add(match[1])
      return secondsSeen.size
    }, { timeout: 30000, intervals: [200] }).toBeGreaterThanOrEqual(2)

    await expect(ribbon).toContainText(/round \d+/, { timeout: 30000 })

    // The ribbon persists while tool rows render (visibility fix).
    const anyToolRow = page.locator('.tool-row')
    await expect(anyToolRow.first()).toBeVisible({ timeout: 120000 })
    await expect(ribbon).toBeVisible()

    // Run completes: ribbon goes away, transcript keeps the tool rows.
    await expect(ribbon).toHaveCount(0, { timeout: 180000 })
    const searchRow = page.locator('.msg-ai .tool-row[data-op="web.search"]').first()
    await expect(searchRow).toBeVisible()

    // Search rows are collapsed pills after completion.
    await expect(searchRow).toHaveAttribute('aria-expanded', 'false')

    // Replayed rows show no elapsed badges (no fake timings).
    await expect(page.locator('.tool-row__elapsed')).toHaveCount(0)

    // Expanding a row reveals labeled input/result sections.
    await searchRow.click()
    await expect(searchRow).toHaveAttribute('aria-expanded', 'true')
    const sectionLabels = page.locator('.tool-row-section__label')
    await expect(sectionLabels.filter({ hasText: 'input' }).first()).toBeVisible()
    await expect(sectionLabels.filter({ hasText: 'result' }).first()).toBeVisible()
  })

  test('live failed tool call auto-expands its error row', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const textarea = page.locator('.chat-textarea')
    await textarea.fill('Fetch the exact URL http://127.0.0.1:9/missing with your web fetch tool and report what error you get. Do not try any other URL.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    const errorRow = page.locator('.tool-row--error').first()
    await expect(errorRow).toBeVisible({ timeout: 180000 })
    await expect(errorRow).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator('.tool-row-section--error').first()).toBeVisible()
  })
})
