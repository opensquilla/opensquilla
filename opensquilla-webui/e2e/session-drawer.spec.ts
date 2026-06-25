import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const RAW_KEY_PATTERN = /agent:[a-z0-9_-]+:[a-z0-9_-]+:/i

async function openHub(page: Page) {
  await page.goto(CONTROL_URL + 'sessions')
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
  // Let the session ledger settle before inspecting it.
  await page.waitForTimeout(800)
  await expect(page.locator('.hub-ledger, .hub-state').first()).toBeVisible()
}

async function openDrawerOnFirstRow(page: Page) {
  const rows = page.locator('.hub-row')
  test.skip((await rows.count()) === 0, 'No sessions on this gateway; seed sessions to exercise the drawer')
  await rows.first().locator('.hub-row__main').click()
  await expect(page.locator('.inspect-drawer')).toBeVisible()
}

test.describe('Session inspect drawer', () => {
  test('row click opens the drawer with a transcript preview', async ({ page }) => {
    await openHub(page)
    await openDrawerOnFirstRow(page)

    const drawer = page.locator('.inspect-drawer')
    await expect(drawer).toHaveAttribute('role', 'dialog')
    await expect(drawer).toHaveAttribute('aria-modal', 'true')
    // Row click no longer navigates; inspection happens in place.
    await expect(page).toHaveURL(/\/sessions$/)

    // Transcript settles into messages, an honest empty state, or an
    // ErrorState — never a blank region.
    await expect(drawer.locator('.inspect-msg, .inspect-empty, .error-state').first())
      .toBeVisible({ timeout: 10000 })
    const messageCount = await drawer.locator('.inspect-msg').count()
    if (messageCount > 0) {
      const text = (await drawer.locator('.inspect-msg').first().innerText()).trim()
      expect(text.length).toBeGreaterThan(0)
    }

    // The raw session key is copyable but never displayed.
    await expect(drawer.getByRole('button', { name: 'Copy session key' })).toBeVisible()
    const headerText = await drawer.locator('.inspect-head').innerText()
    const metaText = await drawer.locator('.inspect-meta').innerText()
    expect(headerText + metaText).not.toMatch(RAW_KEY_PATTERN)
  })

  test('Escape closes the drawer', async ({ page }) => {
    await openHub(page)
    await openDrawerOnFirstRow(page)

    await page.keyboard.press('Escape')
    await expect(page.locator('.inspect-drawer')).toHaveCount(0)
    await expect(page).toHaveURL(/\/sessions$/)
  })

  test('Open in chat navigates with the session param', async ({ page }) => {
    await openHub(page)
    await openDrawerOnFirstRow(page)

    await page.locator('.inspect-drawer').getByRole('button', { name: 'Open in chat', exact: true }).click()
    await expect(page).toHaveURL(/\/chat\?session=/)
  })

  test('abort action is absent on idle sessions', async ({ page }) => {
    await openHub(page)

    const idleRows = page.locator('.hub-row').filter({
      hasNot: page.locator('.hub-row__status--running, .hub-row__status--queued'),
    })
    test.skip((await idleRows.count()) === 0, 'No idle sessions on this gateway')

    await idleRows.first().locator('.hub-row__main').click()
    const drawer = page.locator('.inspect-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole('button', { name: /Abort/ })).toHaveCount(0)
    await expect(drawer.getByRole('button', { name: 'Open in chat' })).toBeVisible()
  })

  test('Load earlier extends the transcript when more history exists', async ({ page }) => {
    await openHub(page)
    await openDrawerOnFirstRow(page)

    const drawer = page.locator('.inspect-drawer')
    await expect(drawer.locator('.inspect-msg, .inspect-empty, .error-state').first())
      .toBeVisible({ timeout: 10000 })

    const earlier = drawer.getByRole('button', { name: 'Load earlier' })
    test.skip((await earlier.count()) === 0, 'Transcript fits one page on this gateway')

    const before = await drawer.locator('.inspect-msg').count()
    await earlier.click()
    await expect
      .poll(async () => drawer.locator('.inspect-msg').count(), { timeout: 10000 })
      .toBeGreaterThan(before)
  })
})
