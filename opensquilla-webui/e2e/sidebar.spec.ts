import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const RAW_KEY_PATTERN = /agent:[a-z0-9_-]+:[a-z0-9_-]+:/i
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

async function openControl(page: Page, path = '') {
  await page.goto(CONTROL_URL + path)
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  // Let the session list settle before inspecting the sidebar.
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(800)
  await expect(page.locator('.sidebar-history-list, .sidebar-history-empty').first()).toBeVisible()
}

test.describe('Sidebar', () => {
  test('Recents is a flat list with human titles and no grouped-mode chrome', async ({ page }) => {
    await openControl(page)

    // The Recent|Grouped toggle, family filter chips, and grouped rendering
    // were removed with the fixed-core sidebar restructure.
    await expect(page.getByRole('button', { name: 'Grouped', exact: true })).toHaveCount(0)
    await expect(page.locator('.sidebar-filter-chip')).toHaveCount(0)
    await expect(page.locator('.sidebar-group')).toHaveCount(0)
    await expect(page.locator('.sidebar-family-label')).toHaveCount(0)
    await expect(page.locator('.sidebar-recents-eyebrow')).toHaveText('Recents')

    const sidebarText = await page.locator('.sidebar').innerText()
    expect(sidebarText).not.toMatch(RAW_KEY_PATTERN)
    expect(sidebarText).not.toMatch(UUID_PATTERN)

    const titles = page.locator('.sidebar-history-title')
    test.skip((await titles.count()) === 0, 'No conversations on this gateway; seed sessions to exercise the list')

    for (const title of await titles.allInnerTexts()) {
      expect(title.trim().length).toBeGreaterThan(0)
      expect(title).not.toMatch(RAW_KEY_PATTERN)
      expect(title).not.toMatch(UUID_PATTERN)
    }
  })

  test('cron runs stay mixed into Recents', async ({ page }) => {
    // The Sessions Hub ledger is ground truth for which kinds exist.
    await openControl(page, 'sessions')
    const cronInHub = await page.locator('.hub-row[data-kind="cron"]').count()
    test.skip(cronInHub === 0, 'No cron sessions on this gateway; seed a cron run to exercise the mix')

    // Recents keeps automations interleaved with chats — no kind filtering.
    const cronRows = page.locator('.sidebar-history-row[data-family="automations"]')
    expect(await cronRows.count()).toBeGreaterThan(0)
    for (const title of await cronRows.locator('.sidebar-history-title').allInnerTexts()) {
      expect(title.trim().length).toBeGreaterThan(0)
      expect(title).not.toMatch(UUID_PATTERN)
    }
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

  test('Console auto-expands on console routes and collapses on leaving', async ({ page }) => {
    // Deep-loading a console page opens the fold with the active trail.
    await openControl(page, 'agents')
    const consoleRow = page.locator('.sidebar-core').getByRole('button', { name: 'Console' })
    await expect(consoleRow).toHaveAttribute('aria-expanded', 'true')
    await expect(
      page.locator('#sidebar-console-list .sidebar-fn-item.is-active .sidebar-fn-label'),
    ).toHaveText('Agents')

    // Leaving the console area folds it back down.
    await page.locator('.sidebar-core').getByText('Sessions', { exact: true }).click()
    await expect(page).toHaveURL(/\/sessions/)
    await expect(consoleRow).toHaveAttribute('aria-expanded', 'false')
    await expect(page.locator('#sidebar-console-list')).toHaveCount(0)
  })

  test('only the Recents list scrolls at a 900px viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openControl(page)

    // Expand the Console fold to put the core under maximum height pressure.
    await page.locator('.sidebar-core').getByRole('button', { name: 'Console' }).click()
    await expect(page.locator('#sidebar-console-list')).toBeVisible()

    const metrics = await page.evaluate(() => {
      const pick = (selector: string) => {
        const el = document.querySelector(selector)
        if (!(el instanceof HTMLElement)) return null
        return {
          scrollHeight: el.scrollHeight,
          clientHeight: el.clientHeight,
          overflowY: getComputedStyle(el).overflowY,
        }
      }
      return {
        sidebar: pick('.sidebar'),
        core: pick('.sidebar-core'),
        list: pick('.sidebar-history-list'),
      }
    })

    // Nav chrome never overflows (1px slack for subpixel rounding).
    expect(metrics.sidebar).not.toBeNull()
    expect(metrics.sidebar!.scrollHeight).toBeLessThanOrEqual(metrics.sidebar!.clientHeight + 1)
    expect(metrics.core).not.toBeNull()
    expect(metrics.core!.scrollHeight).toBeLessThanOrEqual(metrics.core!.clientHeight + 1)

    // The Recents list is the single scroll region.
    if (metrics.list) {
      expect(metrics.list.overflowY).toBe('auto')
    }
  })

  test('Ctrl+K opens the new-chat picker into the draft state', async ({ page }) => {
    await openControl(page)

    await page.keyboard.press('Control+k')
    const dialog = page.getByRole('dialog', { name: 'New chat' })
    await expect(dialog).toBeVisible()

    await page.getByRole('button', { name: 'Start chat' }).click()
    await expect(page).toHaveURL(/\/chat\/new\?agent=[a-z0-9_-]+$/i)
  })

  test('footer pins Settings; connection state shows in the topbar', async ({ page }) => {
    await openControl(page)

    const foot = page.locator('.sidebar-foot')
    await expect(foot.getByText('Settings', { exact: true })).toBeVisible()
    // Connection state is shown once, in the global topbar pill — not duplicated
    // in the sidebar footer.
    await expect(foot.locator('.sidebar-conn')).toHaveCount(0)
    const conn = (await page.locator('.topbar .conn-pill').innerText()).toLowerCase()
    expect(conn).toMatch(/connected|connecting/)
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
