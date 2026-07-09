import { test, expect, type Page } from '@playwright/test'

// Desktop-shell emulation: the SPA detects the platform from the injected
// bridge object, and the CLI invocation prefix comes from the same bridge.
// The prefix mirrors the shape the Electron main process reports (env pair +
// quoted bundled binary path).
const PREFIX =
  "OPENSQUILLA_STATE_DIR='/tmp/e2e desk/state' "
  + "OPENSQUILLA_GATEWAY_CONFIG_PATH='/tmp/e2e desk/config.toml' "
  + "'/Applications/OpenSquilla.app/Contents/Resources/runtime/gateway/opensquilla-gateway/opensquilla-gateway'"

async function installDesktopBridge(page: Page) {
  await page.addInitScript((prefix: string) => {
    const w = window as unknown as Record<string, unknown>
    w.opensquillaDesktop = {
      getOsLocale: async () => 'en-US',
      isAutoUpdateEnabled: async () => false,
      getGatewayStatus: async () => ({ url: '', port: 0, owned: true, status: 'ready', logPath: '' }),
      getCliInvocation: async () => ({ mode: 'bundled', prefix }),
      revealGatewayLog: async () => true,
      getDesktopSettings: async () => ({}),
      saveDesktopSettings: async () => ({}),
      resetDesktopSettings: async () => ({ ok: true }),
      setNativeTheme: async () => undefined,
      openArtifact: async () => ({ ok: true }),
      getOnboardingDefaults: async () => ({}),
      saveOnboarding: async () => ({}),
      cancelOnboarding: async () => ({}),
      getBootState: async () => ({}),
      retryStartup: async () => ({}),
      quitApp: async () => ({}),
      onBootStatus: () => () => {},
      onBootError: () => () => {},
    }
  }, PREFIX)
}

test.describe('desktop shell CLI invocation', () => {
  test('folds health-card commands and rewrites them to the bundled CLI', async ({ page }) => {
    await installDesktopBridge(page)
    await page.goto('/control/overview')
    // The first doctor pass on a cold gateway can take a while, hence the
    // generous wait for the first rendered finding card.
    await page.waitForSelector('.health-finding', { timeout: 45000 })

    // Findings with CLI fix steps fold behind the advanced disclosure on
    // desktop. A fully configured gateway may surface none — skip then
    // rather than asserting against an uncontrolled doctor state.
    const folds = page.locator('details.cli-fold')
    test.skip(await folds.count() === 0, 'gateway reports no findings with CLI fix steps')

    const firstFold = folds.first()
    await firstFold.locator('summary').click()
    await expect(firstFold.locator('.cli-fold__hint')).toBeVisible()

    // Every opensquilla command inside the fold carries the paste-ready prefix.
    const firstCommand = firstFold.locator('code').first()
    await expect(firstCommand).toContainText("OPENSQUILLA_STATE_DIR='/tmp/e2e desk/state'")
    await expect(firstCommand).toContainText('opensquilla-gateway')
  })

  test('hides the CLI handoff disclosure in settings', async ({ page }) => {
    await installDesktopBridge(page)
    await page.goto('/control/settings/connection')
    const dialog = page.getByRole('dialog', { name: 'Settings' })
    await expect(dialog).toBeVisible({ timeout: 15000 })
    await expect(dialog.locator('.settings-banner')).toBeVisible({ timeout: 15000 })
    await expect(dialog.getByRole('button', { name: 'CLI handoff' })).toHaveCount(0)
  })

  test('web keeps flat, unprefixed commands', async ({ page }) => {
    await page.goto('/control/overview')
    await page.waitForSelector('.health-finding', { timeout: 45000 })
    await expect(page.locator('details.cli-fold')).toHaveCount(0)
    const commands = page.locator('.health-step__command code').filter({ hasText: 'opensquilla' })
    test.skip(await commands.count() === 0, 'gateway reports no findings with CLI fix steps')
    const command = commands.first()
    await expect(command).toContainText(/^opensquilla /)
    await expect(command).not.toContainText('OPENSQUILLA_STATE_DIR=')
  })
})
