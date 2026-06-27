import { test, expect } from '@playwright/test'

const CONTROL_URL = '/control/'
// Backend-config sections carry a readiness/status dot; Connection is the new
// first entry (live socket state). Appearance + Advanced are the client-only pair.
const SECTIONS = ['Connection', 'Provider', 'Router', 'Channels', 'Capabilities']

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

    // Rail has the backend-config sections (each with a readiness/status dot)
    // plus the client-only Appearance + Advanced sections.
    const tabs = dialog(page).getByRole('tab')
    await expect(tabs).toHaveCount(SECTIONS.length + 2)
    for (const name of SECTIONS) {
      await expect(railTab(page, name)).toBeVisible()
    }
    await expect(dialog(page).getByRole('tab', { name: 'Appearance' })).toBeVisible()
    await expect(dialog(page).getByRole('tab', { name: 'Advanced' })).toBeVisible()

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
    // Honest restart copy: most edits apply live, only some need a restart.
    await expect(foot).toContainText('Most changes apply live; some need a gateway restart')
    // The old blanket "always restart" leak is gone.
    await expect(foot).not.toContainText('Restart the gateway after manual edits')
    await expect(foot.locator('.settings-foot__path')).toContainText(/config.*\.toml/)
    await foot.getByRole('button', { name: 'Copy config path' }).click()
    await expect(page.locator('.toast', { hasText: /Copied/ }).first()).toBeVisible()
  })

  test('rail switches sections, marks the active tab, and syncs the URL with replace', async ({ page }) => {
    await openFromSidebar(page)
    await expect(page).toHaveURL(/\/settings$/)

    await railTab(page, 'Capabilities').click()
    await expect(railTab(page, 'Capabilities')).toHaveAttribute('aria-selected', 'true')
    // Switching a section reflects in the URL so it stays deep-linkable.
    await expect(page).toHaveURL(/\/settings\/capabilities$/)
    // The Capabilities panel renders its tools as stacked sections (Web search,
    // Memory, Image, Audio) rather than a redundant "Capabilities" card heading.
    await expect(dialog(page).getByRole('heading', { name: 'Web search' })).toBeVisible()

    await railTab(page, 'Router').click()
    await expect(railTab(page, 'Router')).toHaveAttribute('aria-selected', 'true')
    await expect(page).toHaveURL(/\/settings\/router$/)
    await expect(dialog(page).getByRole('heading', { name: 'Router Tiers' })).toBeVisible()

    // Section navigation uses replace, so a single Back exits Settings rather
    // than walking section history.
    await page.goBack()
    await expect(dialog(page)).toBeHidden()
    await expect(page).not.toHaveURL(/\/settings/)
  })

  test('Router section saves the router panel visualization mode', async ({ page }) => {
    test.setTimeout(90000)
    await openFromSidebar(page)

    const visualMode = () => dialog(page).locator('select[name="setup_router_visual_mode"]')
    const dirtybar = dialog(page).locator('.settings-dirtybar')

    await railTab(page, 'Router').click()
    await expect(visualMode()).toBeVisible()
    const initial = await visualMode().inputValue()
    const next = initial === 'legacy_grid' ? 'real_candidates' : 'legacy_grid'

    await visualMode().selectOption(next)
    await expect(dirtybar).toBeVisible()
    await expect(dirtybar).toContainText('Unsaved changes in Router')
    await dialog(page).getByRole('button', { name: 'Save Router' }).click()
    await expect(page.locator('.toast', { hasText: /Router saved/ }).first()).toBeVisible()
    await expect(dirtybar).toBeHidden({ timeout: 10000 })

    await page.reload()
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await settingsRow(page).click()
    await railTab(page, 'Router').click()
    await expect(visualMode()).toHaveValue(next)

    await visualMode().selectOption(initial)
    await dialog(page).getByRole('button', { name: 'Save Router' }).click()
    await expect(dirtybar).toBeHidden({ timeout: 10000 })
  })

  test('Escape closes the overlay, leaves /settings, and returns focus to the invoker', async ({ page }) => {
    await openFromSidebar(page)
    await expect(page).toHaveURL(/\/settings$/)

    await page.keyboard.press('Escape')
    await expect(dialog(page)).toBeHidden()
    // The overlay is route-mounted: closing navigates back off /settings.
    await expect(page).not.toHaveURL(/\/settings/)
    await expect(settingsRow(page)).toBeFocused()

    // Escape inside the overlay must not collapse the docked sidebar.
    await expect(page.locator('.sidebar.docked')).toBeVisible()
  })

  test('cold deep link to /settings/connection closes home and moves focus to the sidebar', async ({ page }) => {
    // Land directly on a section with no in-app invoker.
    await page.goto(CONTROL_URL + 'settings/connection')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(dialog(page)).toBeVisible()
    await expect(railTab(page, 'Connection')).toHaveAttribute('aria-selected', 'true')
    // Connection renders even before/without a loaded config gate.
    await expect(dialog(page).getByRole('heading', { name: 'Connection' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(dialog(page)).toBeHidden()
    await expect(page).not.toHaveURL(/\/settings/)
    // No detached focus: it lands on the sidebar Settings button.
    await expect(settingsRow(page)).toBeFocused()
  })

  test('/config deep link redirects into the settings overlay', async ({ page }) => {
    await page.goto(CONTROL_URL + 'config')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(dialog(page)).toBeVisible()
    // /config now redirects to /settings (default section).
    await expect(page).toHaveURL(/\/settings$/)
    await expect(railTab(page, 'Provider')).toHaveAttribute('aria-selected', 'true')
  })

  test('/setup deep link redirects into the overlay on the first not-ready section', async ({ page }) => {
    await page.goto(CONTROL_URL + 'setup')
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    await expect(dialog(page)).toBeVisible()
    // /setup redirects to /settings/auto (first not-ready section).
    await expect(page).toHaveURL(/\/settings\/auto$/)

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

    // Closing with unsaved edits raises the themed confirm; declining keeps the modal.
    await page.keyboard.press('Escape')
    const confirm = page.getByRole('dialog', { name: 'Discard unsaved changes?' })
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Cancel' }).click()
    await expect(confirm).toBeHidden()
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
    await expect(dialog(page).getByRole('heading', { name: 'Web search' })).toBeVisible()

    // No horizontal scroll on the page at 390px.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })

  test('boolean settings render as the canonical control-switch and keep checkbox semantics', async ({ page }) => {
    await openFromSidebar(page)
    await railTab(page, 'Capabilities').click()

    const capture = dialog(page).locator('input[name="setup_memory_auto_capture"]')
    await expect(capture).toBeVisible()

    // It carries the shared switch primitive, not a raw browser checkbox, and
    // is exposed to assistive tech as a switch.
    await expect(capture).toHaveClass(/control-switch/)
    await expect(capture).toHaveAttribute('role', 'switch')

    // The primitive CSS actually loaded and applied end-to-end (built bundle →
    // gateway → page): the checkbox is restyled (appearance:none) and sized as
    // a 36px switch track.
    const appearance = await capture.evaluate((el) => getComputedStyle(el).appearance)
    expect(appearance).toBe('none')
    const box = await capture.boundingBox()
    expect(box?.width).toBeGreaterThanOrEqual(34)
    expect(box?.width).toBeLessThanOrEqual(40)

    // Native checkbox semantics are preserved: it stays a real, keyboard-
    // operable input (Space toggles, :checked round-trips).
    const before = await capture.isChecked()
    await capture.focus()
    await page.keyboard.press('Space')
    expect(await capture.isChecked()).toBe(!before)
    await page.keyboard.press('Space')
    expect(await capture.isChecked()).toBe(before)
  })

  test('every boolean control in Capabilities uses the switch primitive (no raw checkboxes)', async ({ page }) => {
    await openFromSidebar(page)
    await railTab(page, 'Capabilities').click()

    // Open the advanced search disclosure so its toggles render.
    const advanced = dialog(page).getByText('Advanced search options')
    if (await advanced.count()) await advanced.click()

    const checkboxes = dialog(page).locator('input[type="checkbox"]')
    const total = await checkboxes.count()
    expect(total).toBeGreaterThan(0)
    const switches = dialog(page).locator('input[type="checkbox"].control-switch')
    expect(await switches.count()).toBe(total)
  })

  test('Appearance section applies theme instantly without a dirty bar', async ({ page }) => {
    await openFromSidebar(page)

    const appearanceTab = dialog(page).getByRole('tab', { name: 'Appearance' })
    await expect(appearanceTab).toBeVisible()
    await appearanceTab.click()
    await expect(appearanceTab).toHaveAttribute('aria-selected', 'true')
    await expect(dialog(page).getByRole('heading', { name: 'Appearance' })).toBeVisible()

    // Theme radios flip the live document theme with no save step, and persist
    // to the same store the sidebar shortcut reads.
    const dark = dialog(page).getByRole('radio', { name: 'Dark' })
    const light = dialog(page).getByRole('radio', { name: 'Light' })
    await dark.click()
    await expect(dark).toBeChecked()
    await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark')
    await light.click()
    await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('light')
    expect(await page.evaluate(() => localStorage.getItem('opensquilla-theme'))).toBe('light')

    // The router visual-effects toggle is NOT duplicated here — it stays in the
    // chat composer where its live state belongs.
    await expect(dialog(page).locator('input[name="appearance_visual_effects"]')).toHaveCount(0)

    // Client-only: theme changes never raise the settings dirty bar.
    await expect(dialog(page).locator('.settings-dirtybar')).toBeHidden()
  })

  test('Advanced section surfaces homeless flags, applies instantly without a dirty bar', async ({ page }) => {
    await openFromSidebar(page)
    const advTab = dialog(page).getByRole('tab', { name: 'Advanced' })
    await expect(advTab).toBeVisible()
    await advTab.click()
    await expect(advTab).toHaveAttribute('aria-selected', 'true')
    await expect(dialog(page).getByRole('heading', { name: 'Advanced' })).toBeVisible()

    // A boolean Labs flag is the shared switch and writes its raw '1'/'0' key.
    const poll = dialog(page).locator('input[name="labs_approval_poll"]')
    await expect(poll).toHaveAttribute('role', 'switch')
    const before = await poll.isChecked()
    await poll.click()
    expect(await page.evaluate(() => localStorage.getItem('opensquilla.chat.approvalPoll'))).toBe(before ? '0' : '1')

    // The answer-reveal window persists as a validated "min,max" string.
    const min = dialog(page).locator('input[name="labs_reveal_min"]')
    const max = dialog(page).locator('input[name="labs_reveal_max"]')
    await min.fill('1000')
    await max.fill('3000')
    await max.blur()
    expect(await page.evaluate(() => localStorage.getItem('opensquilla.chat.answerReveal'))).toBe('1000,3000')

    // Client-only: none of this raises the settings dirty bar.
    await expect(dialog(page).locator('.settings-dirtybar')).toBeHidden()
  })
})
