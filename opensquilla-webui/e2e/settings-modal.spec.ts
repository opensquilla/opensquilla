import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'

const settingsRow = (page: import('@playwright/test').Page) =>
  page.locator('.sidebar-foot button')

const dialog = (page: import('@playwright/test').Page) =>
  page.getByRole('dialog', { name: 'Settings' })

test.describe('Settings modal', () => {
  test('opens from the sidebar Settings row with focus on Close', async ({ page }) => {
    await page.goto(CONTROL_URL)
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await settingsRow(page).click()
    await expect(dialog(page)).toBeVisible()

    // Full config surface is present: section rail, mode toggle, search, actions.
    await expect(page.getByRole('tab', { name: 'Core' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('button', { name: 'Guided setup' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reload' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible()
    await expect(page.locator('#cfg-search')).toBeVisible()

    // Dialog a11y: focus moves into the modal on open.
    await expect(page.getByRole('button', { name: 'Close' })).toBeFocused()
  })

  test('Escape closes the modal and returns focus to the invoker', async ({ page }) => {
    await page.goto(CONTROL_URL)
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await settingsRow(page).click()
    await expect(dialog(page)).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(dialog(page)).toBeHidden()
    await expect(settingsRow(page)).toBeFocused()

    // Escape inside the modal must not collapse the docked sidebar.
    await expect(page.locator('.sidebar.docked')).toBeVisible()
  })

  test('/config deep link opens the modal over the default view', async ({ page }) => {
    await page.goto(CONTROL_URL + 'config')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(dialog(page)).toBeVisible()
    // Desktop default view is Sessions; the /config shell renders no page.
    await expect(page).toHaveURL(/\/sessions$/)
  })

  test('section tabs switch and key search renders', async ({ page }) => {
    await page.goto(CONTROL_URL + 'config')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(dialog(page)).toBeVisible()

    await page.getByRole('tab', { name: 'Memory' }).click()
    await expect(page.getByRole('tab', { name: 'Memory' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('#cfg-tab-memory')).toBeVisible()
    await expect(page.locator('#cfg-tab-core')).toBeHidden()

    await page.getByRole('tab', { name: 'Core' }).click()
    await page.locator('#cfg-search').fill('port')
    // Filtered form still renders: a matching field or the explicit empty state.
    const portField = page.locator('#cfg-tab-core .form-label').filter({ hasText: /port/ }).first()
    const emptyState = page.locator('#cfg-tab-core .cfg-empty-state')
    await expect(portField.or(emptyState)).toBeVisible()
  })

  test('Form/YAML toggle swaps editors', async ({ page }) => {
    await page.goto(CONTROL_URL + 'config')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(dialog(page)).toBeVisible()

    await page.getByRole('button', { name: 'YAML', exact: true }).click()
    await expect(page.locator('#cfg-yaml-area')).toBeVisible()
    // The section rail only drives the form view.
    await expect(page.getByRole('tablist', { name: 'Config sections' })).toBeHidden()

    await page.getByRole('button', { name: 'Form', exact: true }).click()
    await expect(page.locator('#cfg-yaml-area')).toBeHidden()
    await expect(page.locator('#cfg-form-view')).toBeVisible()
    await expect(page.getByRole('tablist', { name: 'Config sections' })).toBeVisible()
  })
})
