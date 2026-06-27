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

  test('sidebar core shows fixed rows with the Console fold', async ({ page }) => {
    const core = page.locator('.sidebar-core')

    // The old grouped nav (WORK/OPERATE/OBSERVE) and the Chat row are gone;
    // Approvals only appears while requests are pending (count badge).
    await expect(page.locator('.sidebar-nav-group-label')).toHaveCount(0)
    await expect(core.getByText('Chat', { exact: true })).toHaveCount(0)
    const hasPendingApprovals = (await page.locator('.approval-inline').count()) > 0
    await expect(core.locator('> .sidebar-fn-item .sidebar-fn-label')).toHaveText(
      hasPendingApprovals ? ['Sessions', 'Approvals', 'Console'] : ['Sessions', 'Console'],
    )

    // Console row toggles the fold without navigating.
    const urlBefore = page.url()
    const consoleRow = core.getByRole('button', { name: 'Console' })
    await expect(consoleRow).toHaveAttribute('aria-expanded', 'false')
    await expect(page.locator('#sidebar-console-list')).toHaveCount(0)

    await consoleRow.click()
    await expect(consoleRow).toHaveAttribute('aria-expanded', 'true')
    // Health folded into Overview, so the console fold holds seven pages.
    await expect(page.locator('#sidebar-console-list .sidebar-fn-label')).toHaveText([
      'Agents', 'Channels', 'Cron', 'Skills',
      'Overview', 'Usage', 'Logs',
    ])
    expect(page.url()).toBe(urlBefore)

    await consoleRow.click()
    await expect(consoleRow).toHaveAttribute('aria-expanded', 'false')
    await expect(page.locator('#sidebar-console-list')).toHaveCount(0)
  })

  test('can navigate between views', async ({ page }) => {
    const core = page.locator('.sidebar-core')

    await core.getByRole('button', { name: 'Console' }).click()
    await core.getByText('Overview', { exact: true }).click()
    await expect(page).toHaveURL(/\/overview/)

    // The fold stays open while moving between console pages.
    await core.getByText('Logs', { exact: true }).click()
    await expect(page).toHaveURL(/\/logs/)

    await core.getByText('Sessions', { exact: true }).click()
    await expect(page).toHaveURL(/\/sessions/)

    // New chat is instant (no modal): the primary button drops straight to a
    // draft. `exact` matches the New-chat button precisely.
    await page.getByRole('button', { name: 'New chat', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'New chat' })).toHaveCount(0)
    await expect(page).toHaveURL(/\/chat\/new\?agent=[a-z0-9_-]+$/i)
  })

  test('sidebar conversation list is free of raw identifiers', async ({ page }) => {
    // The family filter chips were retired with the Recents-only sidebar.
    await expect(page.locator('.sidebar-filter-chip')).toHaveCount(0)

    // Let the session list settle before inspecting sidebar text.
    await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(800)
    await expect(page.locator('.sidebar-history-list, .sidebar-onboarding, .sidebar-history-empty').first()).toBeVisible()

    const sidebarText = await page.locator('.sidebar').innerText()
    expect(sidebarText).not.toMatch(/agent:[a-z0-9_-]+:[a-z0-9_-]+:/i)
    expect(sidebarText).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)

    // Contract-gap chips stay hidden unless the debug feature flag is on.
    await expect(page.locator('.sidebar-history-gap')).toHaveCount(0)
  })

  test('theme menu picks a mode directly', async ({ page }) => {
    const html = page.locator('html')

    await page.evaluate(() => localStorage.setItem('opensquilla-theme', 'light'))
    await page.reload()
    await page.waitForSelector('.topbar .conn-pill', { timeout: 10000 })
    await expect(html).toHaveAttribute('data-theme', 'light')

    const themeButton = page.getByRole('button', { name: 'Theme', exact: true })
    await themeButton.click()
    const menu = page.getByRole('menu', { name: 'Theme' })
    await expect(menu).toBeVisible()
    await expect(menu.getByRole('menuitemradio', { name: 'Light' })).toHaveAttribute('aria-checked', 'true')

    await menu.getByRole('menuitemradio', { name: 'Dark' }).click()
    await expect(html).toHaveAttribute('data-theme', 'dark')
    await expect(menu).toHaveCount(0)

    // Escape closes without changing the mode.
    await themeButton.click()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu', { name: 'Theme' })).toHaveCount(0)
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

  // Live data and wall-clock content are masked so the baseline pins the
  // chrome: sidebar core/footer, composer, and chat surface.
  const dynamicRegions = (page: import('@playwright/test').Page) => [
    page.locator('.sidebar-history'),
    page.locator('.empty-state__greeting'),
  ]

  test('chat page screenshot matches baseline', async ({ page }) => {
    await page.goto(CONTROL_URL + 'chat')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await page.waitForTimeout(500) // Let animations settle

    await expect(page).toHaveScreenshot('chat-page.png', {
      maxDiffPixels: 100,
      mask: dynamicRegions(page),
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
      mask: dynamicRegions(page),
    })
  })
})
