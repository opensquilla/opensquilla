import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'

test.describe('Tool rows and activity ribbon', () => {
  test('idle chat renders no work card, activity ribbon, elapsed badges, or result sheet', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.work-card')).toHaveCount(0)
    await expect(page.locator('.stream-activity')).toHaveCount(0)
    await expect(page.locator('.tool-row__elapsed')).toHaveCount(0)
    await expect(page.locator('.tool-sheet')).toHaveCount(0)
  })

  test('live search run shows the work card, step chip, and checklist rows, then collapses', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const textarea = page.locator('.chat-textarea')
    await textarea.fill('Use your web search tool to find one recent headline about space exploration, then answer in one sentence.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    // The run is promoted into a centered work card with a phase narration
    // and a right-aligned step chip.
    const workCard = page.locator('.work-card')
    await expect(workCard).toBeVisible({ timeout: 30000 })
    await expect(workCard.locator('.work-card__step')).toHaveText(/^Step \d+$/)

    // Observe the card head until the run completes. Fast runs finish every
    // phase in under a second — the elapsed chip never leaves 0s — so the
    // tick assertion only applies when a phase lasted long enough to tick.
    // Structure and lifecycle are asserted unconditionally.
    const observed = await page.evaluate(async () => {
      const t0 = Date.now()
      const samples: Array<{ phase: string | null; step: string | null; elapsed: string | null; checklistRows: number }> = []
      while (Date.now() - t0 < 180000) {
        const card = document.querySelector('.work-card')
        const phaseEl = document.querySelector('.work-card__phase')
        const stepEl = document.querySelector('.work-card__step')
        const elapsedEl = document.querySelector('.work-card__elapsed')
        // Rows rendered inside the checklist variant of the timeline.
        const checklistRows = document.querySelectorAll('.work-card .tool-timeline--checklist .tool-row').length
        samples.push({
          phase: phaseEl ? phaseEl.textContent : null,
          step: stepEl ? stepEl.textContent : null,
          elapsed: elapsedEl ? elapsedEl.textContent : null,
          checklistRows,
        })
        if (card === null && samples.length > 3) break
        await new Promise((resolve) => setTimeout(resolve, 150))
      }
      return samples
    })

    const phaseTexts = observed.map((s) => s.phase).filter((t): t is string => t !== null)
    expect(phaseTexts.length).toBeGreaterThan(0)
    // The step chip is read as a step in progress, never a bare round counter.
    expect(observed.some((s) => s.step !== null && /^Step \d+$/.test(s.step))).toBe(true)
    // The checklist rows render inside the work card while it owns the focus.
    expect(observed.some((s) => s.checklistRows > 0)).toBe(true)
    // Tick proof: ~2.4s of one continuous phase (16 samples at 150ms) must
    // show at least two distinct elapsed second values.
    const elapsedSeen = new Set<string>()
    let phaseLen = 0
    let prevPhase = ''
    let longestPhase = 0
    for (const s of observed) {
      if (s.phase === null || s.elapsed === null) continue
      elapsedSeen.add(s.elapsed)
      phaseLen = s.phase === prevPhase ? phaseLen + 1 : 1
      prevPhase = s.phase
      longestPhase = Math.max(longestPhase, phaseLen)
    }
    if (longestPhase >= 16) {
      expect(elapsedSeen.size).toBeGreaterThanOrEqual(2)
    }

    // Run completes: the work card collapses away, transcript keeps the rows.
    await expect(workCard).toHaveCount(0, { timeout: 180000 })
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
