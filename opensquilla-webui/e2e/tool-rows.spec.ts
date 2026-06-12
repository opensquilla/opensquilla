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

    // Observe the ribbon until the run completes. Fast runs finish every
    // activity phase in under a second — the counter never leaves 0s — so
    // the tick assertion only applies when some phase lasted long enough
    // to tick; structure and lifecycle are asserted unconditionally.
    const observed = await page.evaluate(async () => {
      const t0 = Date.now()
      const samples: Array<{ txt: string | null; rows: number }> = []
      while (Date.now() - t0 < 180000) {
        const el = document.querySelector('.stream-activity-text')
        const txt = el ? el.textContent : null
        const rows = document.querySelectorAll('.tool-row').length
        samples.push({ txt, rows })
        if (txt === null && rows > 0 && samples.length > 3) break
        await new Promise((resolve) => setTimeout(resolve, 150))
      }
      return samples
    })

    const ribbonTexts = observed.map((s) => s.txt).filter((t): t is string => t !== null)
    expect(ribbonTexts.length).toBeGreaterThan(0)
    // Narration carries elapsed seconds and the round counter.
    expect(ribbonTexts.some((t) => /· \d+s · round \d+/.test(t))).toBe(true)
    // The ribbon persists while tool rows render (visibility fix).
    expect(observed.some((s) => s.txt !== null && s.rows > 0)).toBe(true)
    // Tick proof: ~2.4s of one continuous phase (16 samples at 150ms) must
    // show at least two distinct second values.
    const secondsSeen = new Set<string>()
    let phaseLen = 0
    let prevLabel = ''
    let longestPhase = 0
    for (const t of ribbonTexts) {
      const m = /^(.*?) · (\d+)s\b/.exec(t)
      if (!m) continue
      secondsSeen.add(m[2])
      phaseLen = m[1] === prevLabel ? phaseLen + 1 : 1
      prevLabel = m[1]
      longestPhase = Math.max(longestPhase, phaseLen)
    }
    if (longestPhase >= 16) {
      expect(secondsSeen.size).toBeGreaterThanOrEqual(2)
    }

    // Run completes: ribbon goes away, transcript keeps the tool rows.
    await expect(ribbon).toHaveCount(0, { timeout: 180000 })
    let searchRow = page.locator('.msg-ai .tool-row[data-op="web.search"]').first()
    await expect(searchRow).toBeVisible()

    // Search rows are collapsed pills after completion.
    await expect(searchRow).toHaveAttribute('aria-expanded', 'false')

    // Multiple search calls collapse under a group header; expand it and
    // assert against a member row, which follows the same pill contract.
    if (await searchRow.evaluate((el) => el.classList.contains('tool-row--group'))) {
      await searchRow.click()
      await expect(searchRow).toHaveAttribute('aria-expanded', 'true')
      searchRow = page.locator('.msg-ai .tool-row--member[data-op="web.search"]').first()
      await expect(searchRow).toBeVisible()
      await expect(searchRow).toHaveAttribute('aria-expanded', 'false')
    }

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
