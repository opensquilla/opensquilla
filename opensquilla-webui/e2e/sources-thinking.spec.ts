import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'

test.describe('Sources row and thinking disclosure', () => {
  test('idle chat renders no sources row or thinking disclosure', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.sources-row')).toHaveCount(0)
    await expect(page.locator('.thinking-fold')).toHaveCount(0)
  })

  test('live search turn renders a sources row with real links', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const textarea = page.locator('.chat-textarea')
    await textarea.fill('Use your web search tool to find one recent headline about renewable energy, then answer in one sentence.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    // The turn runs and completes.
    const ribbon = page.locator('.stream-activity')
    await expect(ribbon).toBeVisible({ timeout: 30000 })
    await expect(ribbon).toHaveCount(0, { timeout: 180000 })

    // Sources row appears on the finished assistant turn, collapsed.
    const sourcesRow = page.locator('.msg-ai .sources-row').first()
    await expect(sourcesRow).toBeVisible({ timeout: 30000 })
    const toggle = sourcesRow.locator('.sources-row__toggle')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(toggle.locator('.sources-row__count')).toHaveText(/^[1-9]\d*$/)

    // Expanding reveals real external links.
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const links = sourcesRow.locator('.sources-row__link')
    expect(await links.count()).toBeGreaterThan(0)
    for (const href of await links.evaluateAll(nodes => nodes.map(node => node.getAttribute('href') || ''))) {
      expect(href).toMatch(/^https?:\/\//)
      // Compacted tool results truncate long strings with a '…' suffix; such
      // URLs are dead links and must never be rendered as hrefs.
      expect(href).not.toMatch(/…|%E2%80%A6/i)
    }
    const resolvedHrefs = await links.evaluateAll(nodes =>
      nodes.map(node => (node as HTMLAnchorElement).href),
    )
    for (const href of resolvedHrefs) {
      expect(href).not.toMatch(/…|%E2%80%A6/i)
    }
    const rels = await links.evaluateAll(nodes => nodes.map(node => node.getAttribute('rel') || ''))
    for (const rel of rels) {
      expect(rel).toContain('noopener')
      expect(rel).toContain('noreferrer')
    }

    // Thinking disclosure only renders when the routed model emitted
    // reasoning; when present it must default to collapsed.
    const folds = page.locator('.thinking-fold')
    if (await folds.count() > 0) {
      for (const isOpen of await folds.evaluateAll(nodes => nodes.map(node => node.hasAttribute('open')))) {
        expect(isOpen).toBe(false)
      }
    }

    // The row survives a reload: tool results replay through chat.history.
    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    const replayedRow = page.locator('.msg-ai .sources-row').first()
    await expect(replayedRow).toBeVisible({ timeout: 30000 })
    await expect(replayedRow.locator('.sources-row__toggle')).toHaveAttribute('aria-expanded', 'false')
  })
})
