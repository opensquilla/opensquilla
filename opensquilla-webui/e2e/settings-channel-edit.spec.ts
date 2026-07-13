import { expect, test, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const NAME = 'e2e-edit-telegram'

// End-to-end: channel edit via the #channel-<name> deep link. Covers edit
// seeding, the no-'***' invariant, stored-secret probe without retyping, and
// the blank-secret keep-current save merge.

async function openSettingsChannels(page: Page): Promise<void> {
  await page.goto(`${CONTROL_URL}settings/channels`)
  await expect(page.locator('.conn-pill')).toBeVisible({ timeout: 15000 })
}

function dialog(page: Page) {
  return page.getByRole('dialog', { name: 'Settings' })
}

test.describe.serial('channel edit deep link', () => {
  test('compose a channel, edit it via deep link, save without retyping secrets', async ({ page }) => {
    // Compose a telegram channel with a dummy token.
    await openSettingsChannels(page)
    const dlg = dialog(page)
    await dlg.locator('button[data-channel-type="telegram"]').click()
    await dlg.locator('input[name="setup_channel_name"]').fill(NAME)
    await dlg.locator('input[name="setup_channel_token"]').fill('0000:e2e-dummy-token')
    await dlg.getByRole('button', { name: 'Save Channel' }).click()
    await expect(dlg.locator('.setup-runtime').getByText(NAME)).toBeVisible({ timeout: 10000 })

    // Deep-link into edit mode.
    await page.goto(`${CONTROL_URL}settings/channels#channel-${NAME}`)
    await expect(page.locator('.conn-pill')).toBeVisible({ timeout: 15000 })
    await expect(dialog(page).getByText(`Edit channel: ${NAME}`)).toBeVisible({ timeout: 10000 })

    // Name is read-only, secret is masked, and no input anywhere holds '***'.
    const nameInput = dialog(page).locator('input[name="setup_channel_name"]')
    await expect(nameInput).toHaveAttribute('readonly', '')
    await expect(nameInput).toHaveValue(NAME)
    await expect(dialog(page).locator('input[name="setup_channel_token"]')).toHaveValue(/Stored/)
    for (const value of await dialog(page).locator('input').evaluateAll(
      els => els.map(el => (el as HTMLInputElement).value),
    )) {
      expect(value).not.toBe('***')
    }

    // Test connection without touching the secret: a verdict line must render
    // (failure is fine — it proves the stored-secret probe actually ran).
    await dialog(page).getByRole('button', { name: 'Test connection' }).click()
    await expect(dialog(page).locator('.setup-channels__test')).toBeVisible({ timeout: 20000 })

    // Change a non-secret field and save; edit mode persists, secret stays masked.
    await dialog(page).locator('input[name="setup_channel_default_chat_id"]').fill('4242')
    await dialog(page).getByRole('button', { name: 'Save changes' }).click()
    await expect(dialog(page).getByText(`Edit channel: ${NAME}`)).toBeVisible({ timeout: 10000 })
    await expect(dialog(page).locator('input[name="setup_channel_token"]')).toHaveValue(/Stored/, { timeout: 10000 })
    await expect(dialog(page).locator('input[name="setup_channel_default_chat_id"]')).toHaveValue('4242')
  })

  test('cleanup: remove the e2e channel', async ({ page }) => {
    await openSettingsChannels(page)
    const dlg = dialog(page)
    const row = dlg.locator('.setup-runtime__row', { hasText: NAME })
    if (await row.count()) {
      await row.getByRole('button', { name: 'Remove' }).click()
      await page.getByRole('button', { name: 'Remove channel' }).click().catch(async () => {
        // Confirm modal primary label fallback.
        await page.locator('.confirm-modal button.btn--primary, [role="alertdialog"] button.btn--primary').first().click()
      })
      await expect(dlg.locator('.setup-runtime__row', { hasText: NAME })).toHaveCount(0, { timeout: 10000 })
    }
  })
})
