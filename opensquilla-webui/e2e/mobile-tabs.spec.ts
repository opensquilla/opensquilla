import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const MOBILE_VIEWPORT = { width: 390, height: 844 }

async function openMobileChat(page: Page) {
  await page.setViewportSize(MOBILE_VIEWPORT)
  await page.goto(CONTROL_URL + 'chat')
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
}

test.describe('Mobile bottom tab bar', () => {
  test('tabs are visible and navigate between Chat, Sessions, and Approvals', async ({ page }) => {
    await openMobileChat(page)

    const tabbar = page.locator('.mobile-tabbar')
    await expect(tabbar).toBeVisible()
    await expect(tabbar.locator('.mobile-tab')).toHaveCount(4)

    // Chat is the active tab on the chat route.
    const chatTab = tabbar.getByRole('link', { name: 'Chat' })
    await expect(chatTab).toHaveClass(/is-active/)

    await tabbar.getByRole('link', { name: 'Sessions' }).click()
    await expect(page).toHaveURL(/\/sessions$/)
    await expect(tabbar.getByRole('link', { name: 'Sessions' })).toHaveClass(/is-active/)
    await expect(chatTab).not.toHaveClass(/is-active/)

    await tabbar.getByRole('link', { name: 'Approvals' }).click()
    await expect(page).toHaveURL(/\/approvals$/)
    await expect(tabbar.getByRole('link', { name: 'Approvals' })).toHaveClass(/is-active/)

    await chatTab.click()
    await expect(page).toHaveURL(/\/chat/)
    await expect(chatTab).toHaveClass(/is-active/)
  })

  test('every tab target meets the 44px minimum', async ({ page }) => {
    await openMobileChat(page)

    for (const tab of await page.locator('.mobile-tabbar .mobile-tab').all()) {
      const box = await tab.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.height).toBeGreaterThanOrEqual(44)
      expect(box!.width).toBeGreaterThanOrEqual(44)
    }
  })

  test('More opens the sidebar drawer; the scrim closes it', async ({ page }) => {
    await openMobileChat(page)

    await page.locator('.mobile-tabbar').getByRole('button', { name: 'More' }).click()
    await expect(page.locator('.sidebar.docked')).toBeVisible()
    await expect(page.locator('.sidebar-scrim')).toBeVisible()

    // Tap outside the drawer to dismiss it.
    await page.locator('.sidebar-scrim').click({ position: { x: 350, y: 400 } })
    await expect(page.locator('.sidebar-scrim')).toHaveCount(0)
  })

  test('the chat composer sits above the tab bar, not behind it', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const composer = page.locator('.chat-composer')
    await expect(composer).toBeVisible()

    const composerBox = await composer.boundingBox()
    const tabbarBox = await page.locator('.mobile-tabbar').boundingBox()
    expect(composerBox).not.toBeNull()
    expect(tabbarBox).not.toBeNull()
    expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(tabbarBox!.y + 1)
  })

  test('desktop shows no tab bar', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(CONTROL_URL + 'chat')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(page.locator('.mobile-tabbar')).toBeHidden()
  })
})
