import { test, expect } from '@playwright/test'

const CONTROL_CHAT_URL = '/control/chat'

test.describe('Chat parity controls', () => {
  test('composer exposes restored dev chat actions', async ({ page }) => {
    await page.goto(CONTROL_CHAT_URL)
    await expect(page.locator('.chat-composer')).toBeVisible()

    await expect(page.getByRole('button', { name: 'Composer settings' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Record voice input' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Export as Markdown' })).toBeVisible()

    await page.getByRole('button', { name: 'Composer settings' }).click()
    await expect(page.getByRole('dialog', { name: 'Composer settings' })).toBeVisible()
    await expect(page.getByText('Execution mode')).toBeVisible()
    await expect(page.getByText('Squilla Router')).toBeVisible()
    await expect(page.getByText('Visual effects')).toBeVisible()
    await expect(page.getByRole('switch', { name: 'Squilla Router' })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'Visual effects' })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Off' })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Bypass approvals' })).toBeVisible()
  })
})
