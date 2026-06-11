import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'

async function openDraft(page: Page) {
  await page.goto(CONTROL_URL + 'chat/new')
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
}

test.describe('Empty draft state', () => {
  test('draft greets with the identity line and at least 3 chips, no brand mark', async ({ page }) => {
    await openDraft(page)

    await expect(page.locator('.empty-state__greeting')).toHaveText(/Good (morning|afternoon|evening)\./)
    await expect(page.locator('.empty-state__identity')).toContainText('· ready')

    // Brand lives in the sidebar chrome only: no wordmark, no mark in the content area.
    await expect(page.locator('.chat-landing-lockup')).toHaveCount(0)
    await expect(page.locator('.empty-state__mark')).toHaveCount(0)
    await expect(page.locator('.msg-ai-avatar')).toHaveCount(0)

    expect(await page.locator('.empty-state__chip').count()).toBeGreaterThanOrEqual(3)
  })

  test('chip click fills the composer without sending', async ({ page }) => {
    await openDraft(page)

    const chip = page.locator('.empty-state__chip').first()
    const text = (await chip.innerText()).trim()
    await chip.click()

    await expect(page.locator('.chat-textarea')).toHaveValue(text)
    await expect(page.locator('.chat-textarea')).toBeFocused()

    // Draft only: nothing was sent and no session materialized.
    await expect(page.locator('.msg-user, .msg-ai')).toHaveCount(0)
    await expect(page).toHaveURL(/\/chat\/new/)
    expect(page.url()).not.toContain('session=')
  })

  test('renders and fills at 390px', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openDraft(page)

    await expect(page.locator('.empty-state__greeting')).toBeVisible()
    expect(await page.locator('.empty-state__chip').count()).toBeGreaterThanOrEqual(3)

    const chip = page.locator('.empty-state__chip').first()
    const text = (await chip.innerText()).trim()
    await chip.click()

    await expect(page.locator('.chat-textarea')).toHaveValue(text)
    await expect(page.locator('.msg-user, .msg-ai')).toHaveCount(0)
  })

  test('prefilled draft keeps chips out of the way', async ({ page }) => {
    // The Sessions Hub task input opens the draft with prefilled text.
    await page.goto(CONTROL_URL + 'sessions')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const taskText = 'Summarize the latest gateway logs'
    await page.locator('.hub-task__input').fill(taskText)
    await page.getByRole('button', { name: 'Start task' }).click()

    await expect(page).toHaveURL(/\/chat\/new/)
    await expect(page.locator('.chat-textarea')).toHaveValue(taskText)
    await expect(page.locator('.empty-state__greeting')).toBeVisible()
    await expect(page.locator('.empty-state__chips')).toHaveCount(0)
  })
})
