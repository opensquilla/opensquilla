import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
const SECTIONS = ['Provider', 'Router', 'Channels', 'Capabilities']

const settingsRow = (page: import('@playwright/test').Page) =>
  page.locator('.sidebar-foot button')

const dialog = (page: import('@playwright/test').Page) =>
  page.getByRole('dialog', { name: 'Settings' })

const railTab = (page: import('@playwright/test').Page, name: string) =>
  dialog(page).getByRole('tab', { name: new RegExp(`^${name}:`) })

async function openFromSidebar(page: import('@playwright/test').Page) {
  await page.goto(CONTROL_URL)
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await settingsRow(page).click()
  await expect(dialog(page)).toBeVisible()
}

test.describe('Settings modal', () => {
  test('opens from the sidebar with the curated section rail and readiness banner', async ({ page }) => {
    await openFromSidebar(page)

    // Dialog a11y: focus moves into the modal on open, before any interaction.
    await expect(page.getByRole('button', { name: 'Close' })).toBeFocused()

    // Rail is exactly the four curated sections, each with a readiness state.
    const tabs = dialog(page).getByRole('tab')
    await expect(tabs).toHaveCount(SECTIONS.length)
    for (const name of SECTIONS) {
      await expect(railTab(page, name)).toBeVisible()
    }

    // Readiness banner: quiet ready line or actionable count.
    const banner = dialog(page).locator('.settings-banner')
    await expect(banner).toBeVisible()
    await expect(banner.locator('.settings-banner__row')).toContainText(/Ready to run|Action needed \(\d+\)/)

    // CLI handoff disclosure expands with command groups and the config summary.
    await banner.getByRole('button', { name: 'CLI handoff' }).click()
    await expect(banner.locator('.setup-cli__group', { hasText: 'CLI handoff' })).toBeVisible()
    await expect(banner.locator('.setup-cli__group', { hasText: 'CLI recipes' })).toBeVisible()
    await expect(banner.locator('.setup-summary')).toContainText('Provider')
  })

  test('no YAML editor, raw key search, or guided-setup wording anywhere', async ({ page }) => {
    await openFromSidebar(page)

    await expect(dialog(page).getByRole('button', { name: 'YAML', exact: true })).toHaveCount(0)
    await expect(dialog(page).getByRole('button', { name: 'Form', exact: true })).toHaveCount(0)
    await expect(dialog(page).locator('#cfg-search')).toHaveCount(0)
    await expect(dialog(page).locator('textarea#cfg-yaml-area')).toHaveCount(0)
    await expect(dialog(page).getByText('Guided setup')).toHaveCount(0)

    // Footer keeps the config.toml escape hatch with a copy affordance.
    const foot = dialog(page).locator('.settings-foot')
    await expect(foot).toContainText('More options live in')
    await expect(foot).toContainText('Restart the gateway after manual edits')
    await expect(foot.locator('.settings-foot__path')).toContainText(/config.*\.toml/)
    await foot.getByRole('button', { name: 'Copy config path' }).click()
    await expect(page.locator('.toast', { hasText: /Copied/ }).first()).toBeVisible()
  })

  test('rail switches sections and marks the active tab', async ({ page }) => {
    await openFromSidebar(page)

    await railTab(page, 'Capabilities').click()
    await expect(railTab(page, 'Capabilities')).toHaveAttribute('aria-selected', 'true')
    await expect(dialog(page).getByRole('heading', { name: 'Capabilities' })).toBeVisible()
    await expect(dialog(page).getByText('Web search', { exact: true })).toBeVisible()

    await railTab(page, 'Router').click()
    await expect(railTab(page, 'Router')).toHaveAttribute('aria-selected', 'true')
    await expect(dialog(page).getByRole('heading', { name: 'Router Tiers' })).toBeVisible()
  })

  test('Escape closes the modal and returns focus to the invoker', async ({ page }) => {
    await openFromSidebar(page)

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
    // Default landing section is the first rail entry.
    await expect(railTab(page, 'Provider')).toHaveAttribute('aria-selected', 'true')
  })

  test('/setup deep link opens the modal on the first not-ready section', async ({ page }) => {
    await page.goto(CONTROL_URL + 'setup')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(dialog(page)).toBeVisible()
    await expect(page).toHaveURL(/\/sessions$/)

    // The selected tab matches the readiness state: with everything ready it
    // is Provider, otherwise the first section whose rail dot needs action.
    await expect(dialog(page).getByRole('tab', { selected: true })).toHaveCount(1)
    const banner = dialog(page).locator('.settings-banner')
    const ready = await banner.locator('.settings-banner__row').textContent()
    if (ready && ready.includes('Ready to run')) {
      await expect(railTab(page, 'Provider')).toHaveAttribute('aria-selected', 'true')
    } else {
      const selected = dialog(page).getByRole('tab', { selected: true })
      await expect(selected).toHaveAttribute('aria-label', /Needs action|Provider first|Missing/)
    }
  })

  test('dirty edits raise the bar, guard close, and Discard restores values', async ({ page }) => {
    await openFromSidebar(page)

    await railTab(page, 'Capabilities').click()
    const maxResults = dialog(page).locator('input[name="setup_search_max_results"]')
    await expect(maxResults).toBeVisible()
    const original = await maxResults.inputValue()
    await maxResults.fill(String(Number(original || '5') + 3))

    const dirtybar = dialog(page).locator('.settings-dirtybar')
    await expect(dirtybar).toBeVisible()
    await expect(dirtybar).toContainText('Unsaved changes in Capabilities')

    // Closing with unsaved edits asks for confirmation; declining keeps the modal.
    page.once('dialog', d => d.dismiss())
    await page.keyboard.press('Escape')
    await expect(dialog(page)).toBeVisible()

    await dirtybar.getByRole('button', { name: 'Discard' }).click()
    await expect(dirtybar).toBeHidden()
    await expect(maxResults).toHaveValue(original)
  })

  test('live save round-trip persists a harmless Capabilities toggle', async ({ page }) => {
    test.setTimeout(90000)
    await openFromSidebar(page)

    // memory.auto_capture_enabled is hot-applied via the config.patch path.
    const capture = () => dialog(page).locator('input[name="setup_memory_auto_capture"]')
    const saveMemory = () => dialog(page).getByRole('button', { name: 'Save memory embedding' })

    await railTab(page, 'Capabilities').click()
    await expect(capture()).toBeVisible()
    const initial = await capture().isChecked()

    await capture().setChecked(!initial)
    await saveMemory().click()
    await expect(page.locator('.toast', { hasText: /Memory/ }).first()).toBeVisible()
    await expect(dialog(page).locator('.settings-dirtybar')).toBeHidden({ timeout: 10000 })

    // Reload: the persisted value must survive a fresh modal.
    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await settingsRow(page).click()
    await expect(dialog(page)).toBeVisible()
    await railTab(page, 'Capabilities').click()
    await expect(capture()).toBeVisible()
    expect(await capture().isChecked()).toBe(!initial)

    // Restore the original value.
    await capture().setChecked(initial)
    await saveMemory().click()
    await expect(dialog(page).locator('.settings-dirtybar')).toBeHidden({ timeout: 10000 })
    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await settingsRow(page).click()
    await railTab(page, 'Capabilities').click()
    await expect(capture()).toBeVisible()
    expect(await capture().isChecked()).toBe(initial)
  })

  test('mobile: full-screen dialog with horizontal section chips', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(CONTROL_URL + 'config')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(dialog(page)).toBeVisible()

    const modalBox = await dialog(page).boundingBox()
    expect(modalBox?.width).toBe(390)

    const rail = dialog(page).getByRole('tablist', { name: 'Settings sections' })
    await expect(rail).toHaveAttribute('aria-orientation', 'horizontal')
    await railTab(page, 'Capabilities').click()
    await expect(dialog(page).getByRole('heading', { name: 'Capabilities' })).toBeVisible()

    // No horizontal scroll on the page at 390px.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
