import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const MODE_KEY = 'opensquilla-sidebar-conversation-mode'
const COLLAPSE_KEY = 'opensquilla-sidebar-collapsed-groups'
const RAW_KEY_PATTERN = /agent:[a-z0-9_-]+:[a-z0-9_-]+:/i
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

async function openControl(page: Page) {
  await page.goto(CONTROL_URL)
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  // Let the session list settle before inspecting the sidebar.
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(800)
  await expect(page.locator('.sidebar-history-list, .sidebar-history-empty').first()).toBeVisible()
}

test.describe('Sidebar conversation organization', () => {
  test('mode toggle switches to grouped and persists across reload', async ({ page }) => {
    await openControl(page)

    const history = page.locator('.sidebar-history')
    await expect(history).toHaveAttribute('data-conversation-mode', 'recent')

    await page.getByRole('button', { name: 'Grouped', exact: true }).click()
    await expect(history).toHaveAttribute('data-conversation-mode', 'grouped')
    expect(await page.evaluate(key => localStorage.getItem(key), MODE_KEY)).toBe('grouped')

    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(page.locator('.sidebar-history')).toHaveAttribute('data-conversation-mode', 'grouped')

    await page.getByRole('button', { name: 'Recent', exact: true }).click()
    await expect(page.locator('.sidebar-history')).toHaveAttribute('data-conversation-mode', 'recent')
    expect(await page.evaluate(key => localStorage.getItem(key), MODE_KEY)).toBe('recent')
  })

  test('grouped headers are agent or cron job names, never raw ids', async ({ page }) => {
    await openControl(page)
    await page.getByRole('button', { name: 'Grouped', exact: true }).click()

    const sidebarText = await page.locator('.sidebar').innerText()
    expect(sidebarText).not.toMatch(RAW_KEY_PATTERN)
    expect(sidebarText).not.toMatch(UUID_PATTERN)

    const names = page.locator('.sidebar-group-header .sidebar-group-name')
    const count = await names.count()
    test.skip(count === 0, 'No conversations on this gateway; seed sessions to exercise grouping')

    for (const name of await names.allInnerTexts()) {
      expect(name.trim().length).toBeGreaterThan(0)
      expect(name).not.toMatch(RAW_KEY_PATTERN)
      expect(name).not.toMatch(UUID_PATTERN)
    }

    // Family eyebrows stay within the known vocabularies (innerText reflects
    // the CSS uppercase transform, so compare case-insensitively).
    for (const label of await page.locator('.sidebar-family-label').allInnerTexts()) {
      expect(['chats', 'automations', 'channels']).toContain(label.trim().toLowerCase())
    }

    // Each group header carries a count badge.
    const headers = page.locator('.sidebar-group-header')
    for (const text of await headers.locator('.sidebar-group-count').allInnerTexts()) {
      expect(Number(text)).toBeGreaterThan(0)
    }
  })

  test('groups collapse and expand, and collapse state persists across reload', async ({ page }) => {
    await openControl(page)
    await page.getByRole('button', { name: 'Grouped', exact: true }).click()

    const groups = page.locator('.sidebar-group')
    test.skip((await groups.count()) === 0, 'No conversations on this gateway; seed sessions to exercise grouping')

    const firstGroup = groups.first()
    const header = firstGroup.locator('.sidebar-group-header')
    const groupName = (await firstGroup.locator('.sidebar-group-name').innerText()).trim()

    await expect(header).toHaveAttribute('aria-expanded', 'true')
    await expect(firstGroup.locator('.sidebar-history-item').first()).toBeVisible()

    await header.click()
    await expect(header).toHaveAttribute('aria-expanded', 'false')
    await expect(firstGroup.locator('.sidebar-history-item').first()).toBeHidden()
    const stored = await page.evaluate(key => localStorage.getItem(key), COLLAPSE_KEY)
    expect(JSON.parse(stored || '[]').length).toBeGreaterThan(0)

    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await page.waitForTimeout(800)
    const reloadedGroup = page
      .locator('.sidebar-group')
      .filter({ has: page.locator('.sidebar-group-name', { hasText: groupName }) })
      .first()
    await expect(reloadedGroup.locator('.sidebar-group-header')).toHaveAttribute('aria-expanded', 'false')

    await reloadedGroup.locator('.sidebar-group-header').click()
    await expect(reloadedGroup.locator('.sidebar-group-header')).toHaveAttribute('aria-expanded', 'true')
    await expect(reloadedGroup.locator('.sidebar-history-item').first()).toBeVisible()
  })

  test('agent badge filters the flat list and clears via the agent chip', async ({ page }) => {
    await openControl(page)

    const badges = page.locator('.sidebar-agent-badge')
    test.skip((await badges.count()) === 0, 'No conversations on this gateway; seed sessions to exercise badge filtering')

    const label = await badges.first().getAttribute('aria-label')
    expect(label).toMatch(/^Filter by /)

    await badges.first().click()
    await expect(page.locator('.sidebar-agent-chip')).toBeVisible()
    await expect(badges.first()).toHaveAttribute('aria-pressed', 'true')

    // Every remaining row belongs to the filtered agent.
    for (const rowLabel of await page.locator('.sidebar-agent-badge').evaluateAll(
      nodes => nodes.map(node => node.getAttribute('aria-label')),
    )) {
      expect(rowLabel).toBe(label)
    }

    await page.locator('.sidebar-agent-chip').click()
    await expect(page.locator('.sidebar-agent-chip')).toHaveCount(0)
  })

  test('mobile drawer shows a scrim and tapping it closes the drawer', async ({ page }) => {
    await openControl(page)
    await page.setViewportSize({ width: 375, height: 667 })

    const sidebar = page.locator('.sidebar')
    await expect(sidebar).not.toHaveClass(/docked/)
    await expect(page.locator('.sidebar-scrim')).toBeHidden()

    await page.click('.topbar-toggle')
    await expect(sidebar).toHaveClass(/docked/)
    await expect(page.locator('.sidebar-scrim')).toBeVisible()

    // Tap outside the 280px drawer.
    await page.locator('.sidebar-scrim').click({ position: { x: 340, y: 400 } })
    await expect(sidebar).not.toHaveClass(/docked/)
    await expect(page.locator('.sidebar-scrim')).toBeHidden()
  })
})
