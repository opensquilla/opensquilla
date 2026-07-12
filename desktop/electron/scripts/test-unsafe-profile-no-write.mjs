import { strict as assert } from 'node:assert'
import { mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')
const recoveryId = '11234567-89ab-4cde-8fab-0123456789ab'

async function waitFor(check, label, timeoutMs = 60_000) {
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
  throw new Error(`Timed out waiting for ${label}: ${lastError?.message || lastError || ''}`)
}

const root = await realpath(await mkdtemp(join(tmpdir(), 'opensquilla-unsafe-profile-test-')))
const userData = join(root, 'user-data')
const isolatedHome = join(root, 'home')
const outside = join(root, 'outside')
const recoveryRoot = join(userData, 'recovery-profiles')
const selectedRoot = join(recoveryRoot, recoveryId)

await mkdir(recoveryRoot, { recursive: true })
await mkdir(isolatedHome, { recursive: true })
await mkdir(outside, { recursive: true })
const unsafeUpdateState = join(outside, 'opensquilla', 'state', 'desktop-update.json')
const unsafeUpdateBytes = JSON.stringify({
  snoozedVersion: '0.0.1',
  snoozedUntil: '2099-01-01T00:00:00.000Z',
}, null, 2)
await mkdir(dirname(unsafeUpdateState), { recursive: true })
await writeFile(unsafeUpdateState, unsafeUpdateBytes, 'utf8')
await symlink(outside, selectedRoot, process.platform === 'win32' ? 'junction' : 'dir')
await writeFile(
  join(userData, 'desktop-profile-context.json'),
  JSON.stringify({
    schema_version: 1,
    active_profile_kind: 'recovery',
    active_recovery_id: recoveryId,
    attention_acknowledgement: null,
    updated_at: '2026-07-11T00:00:00.000Z',
  }, null, 2),
  'utf8',
)

let app
try {
  app = await electron.launch({
    args: ['--use-mock-keychain', `--user-data-dir=${userData}`, packageRoot],
    env: {
      ...process.env,
      HOME: isolatedHome,
      USERPROFILE: isolatedHome,
      OPENSQUILLA_DESKTOP_REPO_ROOT: repoRoot,
      OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
      OPENSQUILLA_USER_STATE_DIR: join(isolatedHome, 'user-state'),
      OPENSQUILLA_TEST_PROFILE_LOCK_ROOT: '1',
      OPENSQUILLA_DESKTOP_GATEWAY_PORT: '18896',
      OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
      OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION: '9.9.9',
      LANG: 'en_US.UTF-8',
      LC_ALL: 'en_US.UTF-8',
    },
  })

  const page = await waitFor(async () => {
    for (const candidate of app.windows()) {
      if (candidate.isClosed()) continue
      await candidate.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      if (await candidate.locator('#recoveryPanel.visible').count().catch(() => 0)) return candidate
    }
    return null
  }, 'unsafe recovery selection page')

  assert.equal(
    await page.locator('#recoveryCode').innerText(),
    'desktop_selected_recovery_profile_unsafe',
  )
  await delay(1_000)
  assert.deepEqual(await readdir(outside), ['opensquilla'])
  assert.equal(
    await readFile(unsafeUpdateState, 'utf8'),
    unsafeUpdateBytes,
    'updater persistence must not read or rewrite an unsafe selected recovery profile',
  )
  console.log(JSON.stringify({ ok: true, stableCode: 'desktop_selected_recovery_profile_unsafe' }))
} finally {
  await app?.close().catch(() => {})
  await rm(root, { recursive: true, force: true }).catch(() => {})
}
