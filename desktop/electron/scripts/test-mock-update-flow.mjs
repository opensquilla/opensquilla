import { strict as assert } from 'node:assert'
import { dirname, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')
const mockVersion = process.env.OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION || '99.0.0'
const relaunchLabels = ['Relaunch to Update', '重启以更新']

async function waitFor(check, label, timeoutMs = 45_000) {
  const startedAt = Date.now()
  let lastError
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const value = await check()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await delay(250)
  }
  const suffix = lastError ? ` Last error: ${lastError.message || lastError}` : ''
  throw new Error(`Timed out waiting for ${label}.${suffix}`)
}

async function menuLabels(app) {
  return await app.evaluate(({ Menu }) => {
    const menu = Menu.getApplicationMenu()
    const labels = []
    function walk(items) {
      for (const item of items || []) {
        if (item.label) labels.push(item.label)
        if (item.submenu) walk(item.submenu.items)
      }
    }
    if (menu) walk(menu.items)
    return labels
  })
}

async function clickRelaunchToUpdate(app) {
  return await app.evaluate(({ BrowserWindow, Menu }, labels) => {
    const menu = Menu.getApplicationMenu()
    function find(items) {
      for (const item of items || []) {
        if (item.label && labels.includes(item.label)) return item
        const child = item.submenu ? find(item.submenu.items) : null
        if (child) return child
      }
      return null
    }
    const item = menu ? find(menu.items) : null
    if (!item || typeof item.click !== 'function') return false
    item.click(undefined, BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0], undefined)
    return true
  }, relaunchLabels)
}

const app = await electron.launch({
  args: ['--use-mock-keychain', packageRoot],
  env: {
    ...process.env,
    OPENSQUILLA_DESKTOP_REPO_ROOT: repoRoot,
    OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
    OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION: mockVersion,
    // mock install: OK. Availability/download now stay in renderer state.
    OPENSQUILLA_DESKTOP_MOCK_UPDATE_DIALOG_RESPONSES: '0',
  },
})

try {
  const page = await app.firstWindow({ timeout: 60_000 })
  await page.waitForLoadState('domcontentloaded', { timeout: 60_000 }).catch(() => {})
  await waitFor(
    async () => page.url().includes('/control/'),
    'Control UI to load',
    60_000,
  )

  const nativeAutoUpdateEnabled = await page.evaluate(
    () => window.opensquillaDesktop.isAutoUpdateEnabled(),
  )
  assert.equal(nativeAutoUpdateEnabled, true, 'mock update should enable native update bridge')

  const updateBannerCount = await page.locator('[data-testid="update-banner"]').count()
  assert.equal(updateBannerCount, 0, 'desktop native update should suppress the web release banner')

  const availableState = await waitFor(async () => {
    return await page.evaluate(async () => {
      const api = window.opensquillaDesktop
      if (!api.getUpdateState) return null
      const state = await api.getUpdateState()
      return state?.status === 'available' ? state : null
    })
  }, 'mock update available renderer state')
  assert.equal(availableState.latestVersion, mockVersion)

  await page.locator('[data-testid="desktop-update-indicator"]').waitFor({ state: 'visible', timeout: 30_000 })
  await page.locator('[data-testid="desktop-update-indicator"]').click()
  await page.locator('[data-testid="desktop-update-download"]').click()

  const downloadedState = await waitFor(async () => {
    return await page.evaluate(async () => {
      const state = await window.opensquillaDesktop.getUpdateState()
      return state?.status === 'downloaded' ? state : null
    })
  }, 'mock update downloaded renderer state')
  assert.equal(downloadedState.latestVersion, mockVersion)

  const relaunchLabel = await waitFor(async () => {
    const labels = await menuLabels(app)
    return labels.find((label) => relaunchLabels.includes(label))
  }, 'Relaunch to Update menu item')
  assert.ok(relaunchLabel, 'pending mock update should expose relaunch menu item')

  const clicked = await clickRelaunchToUpdate(app)
  assert.equal(clicked, true, 'Relaunch to Update menu item should be clickable')

  await delay(500)
  assert.equal(page.isClosed(), false, 'mock install should not quit the app')
  assert.match(await page.title(), /OpenSquilla/, 'Control UI should remain available after mock install')

  const labelsAfterClick = await menuLabels(app)
  assert.ok(
    labelsAfterClick.some((label) => relaunchLabels.includes(label)),
    'mock install keeps the pending relaunch menu available for repeated inspection',
  )

  console.log(JSON.stringify({
    ok: true,
    version: mockVersion,
    updateState: downloadedState.status,
    relaunchLabel,
    url: page.url(),
    title: await page.title(),
  }, null, 2))
} finally {
  await app.close().catch(() => {})
}
