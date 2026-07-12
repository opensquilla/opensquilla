import assert from 'node:assert/strict'
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  allProfileContexts,
  contextForProfile,
  desktopProfileContextPath,
  loadDesktopProfileContext,
  persistDesktopProfileContextFile,
  primaryProfilePaths,
  profileKindEnvironment,
  serializeDesktopProfileContext,
  updateDesktopProfileContextFile,
} from '../dist/desktop-profile-context.js'

const root = mkdtempSync(join(tmpdir(), 'opensquilla-profile-context-'))
try {
  const primary = primaryProfilePaths(root)
  assert.equal(primary.home, join(root, 'opensquilla'))
  assert.equal(primary.credentialPath, join(root, 'desktop-credential.json'))
  assert.equal(primary.logsDir, join(root, 'logs'))
  assert.equal(profileKindEnvironment('primary'), 'desktop-primary')
  assert.equal(profileKindEnvironment('recovery'), 'desktop-recovery')
  assert.equal(loadDesktopProfileContext(root).issue, null, 'a genuinely missing context is a fresh primary')

  const recoveryId = '01234567-89ab-4cde-8fab-0123456789ab'
  const recovery = contextForProfile(root, 'recovery', recoveryId)
  mkdirSync(recovery.active.home, { recursive: true })
  await persistDesktopProfileContextFile(root, recovery)
  if (process.platform !== 'win32') {
    assert.equal(
      statSync(desktopProfileContextPath(root)).mode & 0o077,
      0,
      'context permissions must not grant group/other access',
    )
  }
  assert.equal(
    readdirSync(root).some((entry) => entry.includes('desktop-profile-context.json.') && entry.endsWith('.tmp')),
    false,
    'durable writes must not leave a temp file behind',
  )

  const loaded = loadDesktopProfileContext(root)
  assert.equal(loaded.issue, null)
  assert.equal(loaded.active.kind, 'recovery')
  assert.equal(loaded.active.recoveryId, recoveryId)
  assert.equal(loaded.active.home, join(root, 'recovery-profiles', recoveryId, 'opensquilla'))
  assert.equal(loaded.active.credentialPath, join(root, 'recovery-profiles', recoveryId, 'desktop-credential.json'))
  assert.equal(loaded.active.logsDir, join(root, 'recovery-profiles', recoveryId, 'logs'))

  const profiles = allProfileContexts(root)
  assert.deepEqual(profiles.map((profile) => profile.kind), ['primary', 'recovery'])

  const concurrentRecoveryId = '31234567-89ab-4cde-8fab-0123456789ab'
  mkdirSync(contextForProfile(root, 'recovery', concurrentRecoveryId).active.home, {
    recursive: true,
  })
  const acknowledgement = {
    stable_code: 'workspace_conflict',
    candidates: [{
      path: join(root, 'opensquilla', 'workspace'),
      identity: '1:2',
      modified_at_ns: 123,
    }],
  }
  await Promise.all([
    updateDesktopProfileContextFile(root, async (current) => {
      await new Promise((resolve) => setTimeout(resolve, 20))
      return contextForProfile(
        root,
        'recovery',
        concurrentRecoveryId,
        new Date().toISOString(),
        current.persisted.attention_acknowledgement,
      )
    }),
    updateDesktopProfileContextFile(root, (current) => contextForProfile(
      root,
      current.active.kind,
      current.active.recoveryId,
      new Date().toISOString(),
      acknowledgement,
    )),
  ])
  const concurrentlyUpdated = loadDesktopProfileContext(root)
  assert.equal(concurrentlyUpdated.active.recoveryId, concurrentRecoveryId)
  assert.deepEqual(
    concurrentlyUpdated.persisted.attention_acknowledgement,
    acknowledgement,
    'serialized read-modify-write must preserve both concurrent decisions',
  )

  let releaseLockedUpdate = () => {}
  let markLockedUpdateStarted = () => {}
  const lockedUpdateMayFinish = new Promise((resolve) => {
    releaseLockedUpdate = resolve
  })
  const lockedUpdateStarted = new Promise((resolve) => {
    markLockedUpdateStarted = resolve
  })
  const lockedUpdate = updateDesktopProfileContextFile(root, async (current) => {
    markLockedUpdateStarted()
    await lockedUpdateMayFinish
    return contextForProfile(
      root,
      current.active.kind,
      current.active.recoveryId,
      new Date().toISOString(),
      current.persisted.attention_acknowledgement,
    )
  })
  await lockedUpdateStarted
  let directPersistSettled = false
  const directPersist = persistDesktopProfileContextFile(
    root,
    contextForProfile(root, 'primary'),
  ).then(() => {
    directPersistSettled = true
  })
  await new Promise((resolve) => setTimeout(resolve, 50))
  assert.equal(
    directPersistSettled,
    false,
    'direct persistence must join the updater lock instead of publishing mid-transaction',
  )
  assert.equal(
    loadDesktopProfileContext(root).active.recoveryId,
    concurrentRecoveryId,
    'a queued direct persistence must leave the updater snapshot untouched',
  )
  releaseLockedUpdate()
  await lockedUpdate
  await directPersist
  assert.equal(loadDesktopProfileContext(root).active.kind, 'primary')

  const externalChoice = contextForProfile(root, 'primary')
  await assert.rejects(
    updateDesktopProfileContextFile(root, async (current) => {
      writeFileSync(
        desktopProfileContextPath(root),
        serializeDesktopProfileContext(externalChoice),
        'utf8',
      )
      return contextForProfile(
        root,
        current.active.kind,
        current.active.recoveryId,
        new Date().toISOString(),
        acknowledgement,
      )
    }),
    /changed while it was being updated/,
  )
  assert.equal(
    loadDesktopProfileContext(root).active.kind,
    'primary',
    'CAS rejection must preserve the external writer\'s newer choice',
  )

  const linkedId = '11234567-89ab-4cde-8fab-0123456789ab'
  const outside = join(root, 'outside')
  mkdirSync(outside)
  const profileCountBeforeLinkedRoot = allProfileContexts(root).length
  symlinkSync(outside, join(root, 'recovery-profiles', linkedId))
  assert.equal(
    allProfileContexts(root).length,
    profileCountBeforeLinkedRoot,
    'linked recovery roots must be ignored',
  )
  writeFileSync(desktopProfileContextPath(root), serializeDesktopProfileContext(
    contextForProfile(root, 'recovery', linkedId),
  ), 'utf8')
  assert.equal(
    loadDesktopProfileContext(root).issue,
    'desktop_selected_recovery_profile_unsafe',
    'a selected linked recovery root must never be activated',
  )

  const corrupt = '{truncated'
  writeFileSync(desktopProfileContextPath(root), corrupt, 'utf8')
  const corruptLoaded = loadDesktopProfileContext(root)
  assert.equal(corruptLoaded.active.kind, 'primary')
  assert.equal(corruptLoaded.issue, 'desktop_profile_context_corrupt')
  assert.equal(readFileSync(desktopProfileContextPath(root), 'utf8'), corrupt, 'inspection preserves corrupt context')

  writeFileSync(desktopProfileContextPath(root), JSON.stringify({
    schema_version: 2,
    active_profile_kind: 'primary',
    active_recovery_id: null,
    attention_acknowledgement: null,
    updated_at: new Date().toISOString(),
  }), 'utf8')
  assert.equal(
    loadDesktopProfileContext(root).issue,
    'desktop_profile_context_schema_too_new',
  )

  const missingId = '21234567-89ab-4cde-8fab-0123456789ab'
  writeFileSync(desktopProfileContextPath(root), serializeDesktopProfileContext(
    contextForProfile(root, 'recovery', missingId),
  ), 'utf8')
  const missingLoaded = loadDesktopProfileContext(root)
  assert.equal(missingLoaded.active.kind, 'recovery', 'the vanished selection is not silently changed')
  assert.equal(missingLoaded.active.recoveryId, missingId)
  assert.equal(missingLoaded.issue, 'desktop_selected_recovery_profile_missing')

  // An explicit user choice is the only thing that replaces an invalid
  // context. The durable write then clears the blocked selection state.
  await persistDesktopProfileContextFile(root, contextForProfile(root, 'primary'))
  assert.equal(loadDesktopProfileContext(root).issue, null)
  assert.equal(loadDesktopProfileContext(root).active.kind, 'primary')
} finally {
  rmSync(root, { recursive: true, force: true })
}

console.log('desktop profile context checks passed')
