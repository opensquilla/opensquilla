import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'

async function openControl(page: Page, path = '') {
  await page.goto(CONTROL_URL + path)
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
}

const settingsDialog = (page: Page) => page.getByRole('dialog', { name: 'Settings' })

test.describe('Console clarity', () => {
  // The DEV-only parts/fold parity check logs `[live-turn parity]` on any
  // fold/key divergence between message.parts and the rendered timeline. Treat
  // it as a hard failure so a regression is caught in CI, not eyeballed.
  let parityErrors: string[]

  test.beforeEach(({ page }) => {
    parityErrors = []
    page.on('console', msg => {
      if (msg.type() === 'error' && msg.text().includes('[live-turn parity]')) {
        parityErrors.push(msg.text())
      }
    })
  })

  test.afterEach(() => {
    expect(parityErrors, 'live-turn parts/fold parity check reported a divergence').toEqual([])
  })

  test('flat navigation removes the Console fold and keeps Settings distinct', async ({ page }) => {
    await openControl(page)

    const settingsRow = page.locator('.sidebar-foot .sidebar-fn-item')
    await expect(settingsRow).toHaveAttribute('data-icon', 'settings')
    await expect(page.locator('.sidebar-nav-group-toggle')).toHaveCount(0)
    await expect(page.locator('.sidebar-core .sidebar-fn-label')).toHaveText([
      'Sessions', 'Overview', 'Skills', 'Cron',
    ])
  })

  test('/health deep link redirects to /overview with the readiness report inline', async ({ page }) => {
    await openControl(page, 'health')

    await expect(page).toHaveURL(/\/overview$/)
    await expect(page.locator('#overview-health')).toBeVisible()
    await expect(page.locator('section[aria-label="Health findings"]')).toBeVisible()
  })

  test('Health stat card jumps to the inline readiness report', async ({ page }) => {
    await openControl(page, 'overview')

    await page.getByRole('button', { name: 'Health' }).click()
    // Still on Overview — the card scrolls instead of navigating away.
    await expect(page).toHaveURL(/\/overview$/)
    await expect(page.locator('#overview-health')).toBeInViewport()
  })

  test('Agents header link opens the Settings modal', async ({ page }) => {
    await openControl(page, 'agents')

    await page.locator('.ag-stage__actions').getByRole('button', { name: 'open settings' }).click()
    await expect(settingsDialog(page)).toBeVisible()
  })

  test('Channels header link opens the Settings modal', async ({ page }) => {
    await openControl(page, 'channels')

    await page.locator('.ch-stage__actions').getByRole('button', { name: 'open settings' }).click()
    await expect(settingsDialog(page)).toBeVisible()
  })
})
