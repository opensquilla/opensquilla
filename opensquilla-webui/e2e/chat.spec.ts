import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(CONTROL_URL)
    // Wait for WebSocket connection
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
  })

  test('page loads with correct title', async ({ page }) => {
    await expect(page).toHaveTitle(/OpenSquilla/)
  })

  test('sidebar navigation has all menu items', async ({ page }) => {
    const navItems = page.locator('.sidebar-fn-item')
    await expect(navItems).toHaveCount(10)

    const expectedLabels = [
      'Overview', 'Agents', 'Skills', 'Channels', 'Cron', 'Sessions', 'Usage',
      'Config', 'Logs', 'Approvals',
    ]
    for (const label of expectedLabels) {
      await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
  })

  test('can navigate between views', async ({ page }) => {
    await page.click('text=Overview')
    await expect(page).toHaveURL(/\/overview/)

    await page.click('text=Sessions')
    await expect(page).toHaveURL(/\/sessions/)

    await page.click('text=Logs')
    await expect(page).toHaveURL(/\/logs/)

    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(page.getByRole('dialog', { name: 'New chat' })).toBeVisible()
    await page.getByRole('button', { name: 'Start chat' }).click()
    await expect(page).toHaveURL(/\/chat\?session=agent%3Amain%3Awebchat%3A/)
  })

  test('theme toggle works', async ({ page }) => {
    const html = page.locator('html')

    // Check initial theme
    const initialTheme = await html.getAttribute('data-theme')
    expect(['light', 'dark']).toContain(initialTheme)

    // Click theme toggle
    await page.click('[title^="Theme:"]')

    // Theme should change
    const newTheme = await html.getAttribute('data-theme')
    expect(newTheme).not.toBe(initialTheme)
  })

  test('chat input area is visible', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')

    await expect(page.locator('.chat-textarea')).toBeVisible()
    await expect(page.locator('.chat-composer')).toBeVisible()
  })

  test('connection status shows connected', async ({ page }) => {
    const connPill = page.locator('.conn-pill')
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

    const sidebar = page.locator('.sidebar')
    await expect(sidebar).toHaveClass(/docked/)

    await page.click('.sidebar-brand .sidebar-dock-toggle')
    await expect(sidebar).not.toHaveClass(/docked/)

    await page.click('.topbar-toggle')
    await expect(sidebar).toHaveClass(/docked/)
  })
})

test.describe('Visual Regression', () => {
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
