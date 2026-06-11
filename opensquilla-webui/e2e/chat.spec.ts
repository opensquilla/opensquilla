import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(CONTROL_URL)
    // Wait for WebSocket connection
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
  })

  test('page loads with correct title', async ({ page }) => {
    await expect(page).toHaveTitle(/OpenSquilla/)
  })

  test('sidebar navigation is grouped with labeled items', async ({ page }) => {
    const nav = page.locator('.sidebar-primary-nav')
    await expect(nav.locator('.sidebar-nav-group-label')).toHaveText([
      'Work', 'Operate', 'Observe', 'Configure',
    ])

    await expect(nav.locator('.sidebar-fn-item .sidebar-fn-label')).toHaveText([
      'Chat', 'Sessions', 'Approvals',
      'Agents', 'Channels', 'Cron', 'Skills',
      'Overview', 'Usage', 'Logs', 'Health',
      'Config',
    ])
  })

  test('can navigate between views', async ({ page }) => {
    const nav = page.locator('.sidebar-primary-nav')

    await nav.getByText('Overview', { exact: true }).click()
    await expect(page).toHaveURL(/\/overview/)

    await nav.getByText('Sessions', { exact: true }).click()
    await expect(page).toHaveURL(/\/sessions/)

    await nav.getByText('Logs', { exact: true }).click()
    await expect(page).toHaveURL(/\/logs/)

    // Bare /chat opens the new-chat draft state (see new-chat.spec.ts).
    await nav.getByText('Chat', { exact: true }).click()
    await expect(page).toHaveURL(/\/chat\/new$/)

    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(page.getByRole('dialog', { name: 'New chat' })).toBeVisible()
    await page.getByRole('button', { name: 'Start chat' }).click()
    await expect(page).toHaveURL(/\/chat\/new\?agent=main$/)
  })

  test('sidebar conversation list is filtered and free of raw identifiers', async ({ page }) => {
    await expect(page.locator('.sidebar-filter-chip')).toHaveText(['All', 'Chats', 'Automations'])

    // Let the session list settle before inspecting sidebar text.
    await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(800)
    await expect(page.locator('.sidebar-history-list, .sidebar-history-empty').first()).toBeVisible()

    const sidebarText = await page.locator('.sidebar').innerText()
    expect(sidebarText).not.toMatch(/agent:[a-z0-9_-]+:[a-z0-9_-]+:/i)
    expect(sidebarText).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)

    // Contract-gap chips stay hidden unless the debug feature flag is on.
    await expect(page.locator('.sidebar-history-gap')).toHaveCount(0)
  })

  test('theme toggle works', async ({ page }) => {
    const html = page.locator('html')

    // Pin the starting mode so the first cycle step (light → dark) is observable.
    await page.evaluate(() => localStorage.setItem('opensquilla-theme', 'light'))
    await page.reload()
    await page.waitForSelector('.topbar .conn-pill', { timeout: 10000 })
    await expect(html).toHaveAttribute('data-theme', 'light')

    await page.click('[title^="Theme:"]')
    await expect(html).toHaveAttribute('data-theme', 'dark')
  })

  test('chat input area is visible', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')

    await expect(page.locator('.chat-textarea')).toBeVisible()
    await expect(page.locator('.chat-composer')).toBeVisible()
  })

  test('connection status shows connected', async ({ page }) => {
    const connPill = page.locator('.topbar .conn-pill')
    await expect(connPill).toBeVisible()

    const text = await connPill.textContent()
    expect(text?.toLowerCase()).toMatch(/connected|connecting/)
  })

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text())
      }
    })

    await page.goto(CONTROL_URL)
    await page.waitForLoadState('networkidle')

    // Filter out non-critical errors
    const criticalErrors = errors.filter(e =>
      !e.includes('Source map') &&
      !e.includes('favicon') &&
      !e.includes('net::ERR_BLOCKED_BY_CLIENT')
    )

    expect(criticalErrors).toHaveLength(0)
  })
})

test.describe('Chat Interaction', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
  })

  test('can type in chat input', async ({ page }) => {
    const textarea = page.locator('.chat-textarea')
    await textarea.fill('Hello, this is a test message')
    await expect(textarea).toHaveValue('Hello, this is a test message')
  })

  test('sidebar toggle works on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })

    // Mobile collapses the sidebar to an overlay; the topbar toggle reopens it.
    const sidebar = page.locator('.sidebar')
    await expect(sidebar).not.toHaveClass(/docked/)

    await page.click('.topbar-toggle')
    await expect(sidebar).toHaveClass(/docked/)

    await page.click('.sidebar-brand .sidebar-dock-toggle')
    await expect(sidebar).not.toHaveClass(/docked/)
  })
})

test.describe('Visual Regression', () => {
  // Live runs seed real sessions into the sidebar, so the pixel baselines
  // only hold against a clean instance (the default, non-live suite).
  test.skip(LIVE, 'Visual baselines assume a clean sidebar; skipped in live runs.')

  test('chat page screenshot matches baseline', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await page.waitForTimeout(500) // Let animations settle

    await expect(page).toHaveScreenshot('chat-page.png', {
      maxDiffPixels: 100,
    })
  })

  test('dark mode screenshot', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    // Force dark theme
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark')
      localStorage.setItem('opensquilla-theme', 'dark')
    })
    await page.waitForTimeout(300)

    await expect(page).toHaveScreenshot('chat-page-dark.png', {
      maxDiffPixels: 100,
    })
  })
})
