import {
  constants,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  type Stats,
} from 'node:fs'
import { open, rename, rm } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { dirname, join, resolve } from 'node:path'

import { DesktopContextLock } from './desktop-context-lock.js'

export type DesktopProfileKind = 'primary' | 'recovery'

export interface DesktopProfilePaths {
  kind: DesktopProfileKind
  recoveryId: string | null
  home: string
  credentialPath: string
  logsDir: string
}

/**
 * Only the selected profile kind and opaque recovery UUID are persisted. Paths
 * are derived from Electron's current userData root on every launch so an app
 * data relocation cannot make the context escape into a stale directory.
 */
export interface DesktopProfileContextFile {
  schema_version: 1
  active_profile_kind: DesktopProfileKind
  active_recovery_id: string | null
  attention_acknowledgement: DesktopAttentionAcknowledgement | null
  updated_at: string
}

export interface DesktopAttentionAcknowledgement {
  stable_code: string
  candidates: Array<{
    path: string
    identity: string | null
    modified_at_ns: number | null
  }>
}

export interface DesktopProfileContext {
  active: DesktopProfilePaths
  primary: DesktopProfilePaths
  persisted: DesktopProfileContextFile
  /**
   * A persisted selection that cannot be trusted is kept visible but never
   * activated. The main process turns this code into recovery_required before
   * it inspects, creates, or starts anything under `active.home`.
   */
  issue: DesktopProfileContextIssue | null
}

export type DesktopProfileContextIssue =
  | 'desktop_profile_context_corrupt'
  | 'desktop_profile_context_schema_too_new'
  | 'desktop_profile_context_schema_unsupported'
  | 'desktop_profile_context_unreadable'
  | 'desktop_selected_recovery_profile_missing'
  | 'desktop_selected_recovery_profile_unsafe'

const RECOVERY_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function desktopProfileContextPath(userData: string): string {
  return join(resolve(userData), 'desktop-profile-context.json')
}

export function primaryProfilePaths(userData: string): DesktopProfilePaths {
  const root = resolve(userData)
  return {
    kind: 'primary',
    recoveryId: null,
    home: join(root, 'opensquilla'),
    credentialPath: join(root, 'desktop-credential.json'),
    logsDir: join(root, 'logs'),
  }
}

export function isRecoveryProfileId(value: unknown): value is string {
  return typeof value === 'string' && RECOVERY_ID_RE.test(value)
}

export function recoveryProfilePaths(userData: string, recoveryId: string): DesktopProfilePaths {
  if (!isRecoveryProfileId(recoveryId)) throw new Error('Invalid recovery profile id.')
  const root = join(resolve(userData), 'recovery-profiles', recoveryId)
  return {
    kind: 'recovery',
    recoveryId,
    home: join(root, 'opensquilla'),
    credentialPath: join(root, 'desktop-credential.json'),
    logsDir: join(root, 'logs'),
  }
}

export function defaultDesktopProfileContext(userData: string): DesktopProfileContext {
  const primary = primaryProfilePaths(userData)
  return {
    active: primary,
    primary,
    persisted: {
      schema_version: 1,
      active_profile_kind: 'primary',
      active_recovery_id: null,
      attention_acknowledgement: null,
      updated_at: new Date(0).toISOString(),
    },
    issue: null,
  }
}

export function contextForProfile(
  userData: string,
  kind: DesktopProfileKind,
  recoveryId: string | null = null,
  updatedAt = new Date().toISOString(),
  attentionAcknowledgement: DesktopAttentionAcknowledgement | null = null,
): DesktopProfileContext {
  const primary = primaryProfilePaths(userData)
  const active = kind === 'recovery'
    ? recoveryProfilePaths(userData, recoveryId || '')
    : primary
  return {
    active,
    primary,
    persisted: {
      schema_version: 1,
      active_profile_kind: kind,
      active_recovery_id: kind === 'recovery' ? active.recoveryId : null,
      attention_acknowledgement: attentionAcknowledgement,
      updated_at: updatedAt,
    },
    issue: null,
  }
}

export function loadDesktopProfileContext(userData: string): DesktopProfileContext {
  const fallback = defaultDesktopProfileContext(userData)
  const contextPath = desktopProfileContextPath(userData)
  let raw = ''
  try {
    const info = lstatSync(contextPath)
    if (!info.isFile() || info.isSymbolicLink()) {
      return contextWithIssue(fallback, 'desktop_profile_context_unreadable')
    }
    raw = readFileSync(contextPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return fallback
    return contextWithIssue(fallback, 'desktop_profile_context_unreadable')
  }

  try {
    const parsed = JSON.parse(raw) as Partial<DesktopProfileContextFile>
    if (typeof parsed.schema_version !== 'number') {
      return contextWithIssue(fallback, 'desktop_profile_context_corrupt')
    }
    if (parsed.schema_version > 1) {
      return contextWithIssue(fallback, 'desktop_profile_context_schema_too_new')
    }
    if (parsed.schema_version !== 1) {
      return contextWithIssue(fallback, 'desktop_profile_context_schema_unsupported')
    }
    if (typeof parsed.updated_at !== 'string') {
      return contextWithIssue(fallback, 'desktop_profile_context_corrupt')
    }
    if (parsed.active_profile_kind === 'primary') {
      if (parsed.active_recovery_id !== null) {
        return contextWithIssue(fallback, 'desktop_profile_context_corrupt')
      }
      return contextForProfile(
        userData,
        'primary',
        null,
        String(parsed.updated_at || ''),
        parseAttentionAcknowledgement(parsed.attention_acknowledgement),
      )
    }
    if (
      parsed.active_profile_kind === 'recovery'
      && isRecoveryProfileId(parsed.active_recovery_id)
    ) {
      const candidate = recoveryProfilePaths(userData, parsed.active_recovery_id)
      const candidateStatus = recoveryProfileStatus(userData, candidate)
      if (candidateStatus === 'valid') {
        return contextForProfile(
          userData,
          'recovery',
          parsed.active_recovery_id,
          String(parsed.updated_at || ''),
          parseAttentionAcknowledgement(parsed.attention_acknowledgement),
        )
      }
      // Preserve the selected UUID in memory so the recovery UI and sanitized
      // diagnostics can explain what became unavailable. Startup is blocked by
      // `issue`; nothing creates this missing home or silently selects primary.
      return contextWithIssue(
        contextForProfile(
          userData,
          'recovery',
          parsed.active_recovery_id,
          parsed.updated_at,
          parseAttentionAcknowledgement(parsed.attention_acknowledgement),
        ),
        candidateStatus === 'missing'
          ? 'desktop_selected_recovery_profile_missing'
          : 'desktop_selected_recovery_profile_unsafe',
      )
    }
  } catch {
    return contextWithIssue(fallback, 'desktop_profile_context_corrupt')
  }
  return contextWithIssue(fallback, 'desktop_profile_context_corrupt')
}

function contextWithIssue(
  context: DesktopProfileContext,
  issue: DesktopProfileContextIssue,
): DesktopProfileContext {
  return { ...context, issue }
}

function parseAttentionAcknowledgement(value: unknown): DesktopAttentionAcknowledgement | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Partial<DesktopAttentionAcknowledgement>
  if (typeof record.stable_code !== 'string' || !Array.isArray(record.candidates)) return null
  const candidates: DesktopAttentionAcknowledgement['candidates'] = []
  for (const item of record.candidates) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return null
    const candidate = item as Record<string, unknown>
    if (
      typeof candidate.path !== 'string'
      || (candidate.identity !== null && typeof candidate.identity !== 'string')
      || (candidate.modified_at_ns !== null && typeof candidate.modified_at_ns !== 'number')
    ) return null
    candidates.push({
      path: candidate.path,
      identity: candidate.identity as string | null,
      modified_at_ns: candidate.modified_at_ns as number | null,
    })
  }
  return { stable_code: record.stable_code, candidates }
}

function realDirectoryStatus(path: string): 'valid' | 'missing' | 'unsafe' {
  try {
    const info = lstatSync(path)
    return info.isDirectory() && !info.isSymbolicLink() ? 'valid' : 'unsafe'
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'ENOENT' ? 'missing' : 'unsafe'
  }
}

function recoveryProfileStatus(
  userData: string,
  profile: DesktopProfilePaths,
): 'valid' | 'missing' | 'unsafe' {
  const recoveryRoot = join(resolve(userData), 'recovery-profiles')
  const profileRoot = dirname(profile.home)
  for (const path of [recoveryRoot, profileRoot, profile.home]) {
    const status = realDirectoryStatus(path)
    if (status !== 'valid') return status
  }
  try {
    const resolvedRecoveryRoot = realpathSync(recoveryRoot)
    const resolvedProfileRoot = realpathSync(profileRoot)
    const resolvedHome = realpathSync(profile.home)
    if (dirname(resolvedProfileRoot) !== resolvedRecoveryRoot) return 'unsafe'
    if (dirname(resolvedHome) !== resolvedProfileRoot) return 'unsafe'
    return 'valid'
  } catch {
    return 'unsafe'
  }
}

/**
 * Enumerate every Desktop-owned profile for cleanup/backup UIs. Recovery roots
 * are accepted only when the UUID and no-follow directory shape both match;
 * symlinks and junction-like aliases are never traversed.
 */
export function allProfileContexts(userData: string): DesktopProfilePaths[] {
  const profiles = [primaryProfilePaths(userData)]
  const recoveryRoot = join(resolve(userData), 'recovery-profiles')
  let entries: string[] = []
  try {
    const rootInfo = lstatSync(recoveryRoot)
    if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) return profiles
    entries = readdirSync(recoveryRoot)
  } catch {
    return profiles
  }
  for (const entry of entries.sort()) {
    if (!isRecoveryProfileId(entry)) continue
    const profile = recoveryProfilePaths(userData, entry)
    if (recoveryProfileStatus(userData, profile) !== 'valid') continue
    profiles.push(profile)
  }
  return profiles
}

export function serializeDesktopProfileContext(context: DesktopProfileContext): string {
  return `${JSON.stringify(context.persisted, null, 2)}\n`
}

interface DesktopProfileContextDiskSnapshot {
  exists: boolean
  identity: string | null
  bytes: Buffer | null
}

const desktopProfileContextLock = new DesktopContextLock()

function diskIdentity(info: Stats): string {
  return [
    info.dev,
    info.ino,
    info.mode,
    info.nlink,
    info.size,
    info.mtimeMs,
    info.ctimeMs,
  ].join(':')
}

function captureDesktopProfileContextDiskSnapshot(
  userData: string,
): DesktopProfileContextDiskSnapshot {
  const path = desktopProfileContextPath(userData)
  let before: Stats
  try {
    before = lstatSync(path)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return { exists: false, identity: null, bytes: null }
    }
    throw error
  }

  let bytes: Buffer | null = null
  if (before.isFile() && !before.isSymbolicLink()) {
    try {
      bytes = readFileSync(path)
    } catch {
      // An explicit user choice may repair an unreadable context. The no-follow
      // identity still participates in CAS even when its bytes cannot be read.
    }
  }
  let after: Stats
  try {
    after = lstatSync(path)
  } catch {
    throw new Error('Desktop profile context changed while it was being updated.')
  }
  if (diskIdentity(before) !== diskIdentity(after)) {
    throw new Error('Desktop profile context changed while it was being updated.')
  }
  return { exists: true, identity: diskIdentity(after), bytes }
}

function sameDiskSnapshot(
  left: DesktopProfileContextDiskSnapshot,
  right: DesktopProfileContextDiskSnapshot,
): boolean {
  if (left.exists !== right.exists || left.identity !== right.identity) return false
  if (left.bytes === null || right.bytes === null) return left.bytes === right.bytes
  return left.bytes.equals(right.bytes)
}

/**
 * Durably replace the Desktop-owned context after an explicit profile choice.
 * The temp file is created owner-only and fsynced before rename; the containing
 * directory is fsynced where the platform supports directory handles. A failed
 * load never calls this function, so corrupt/future context remains untouched
 * until the user explicitly chooses a profile.
 */
async function persistDesktopProfileContextFileWithSnapshot(
  userData: string,
  context: DesktopProfileContext,
  expectedSnapshot: DesktopProfileContextDiskSnapshot | null = null,
): Promise<void> {
  const root = resolve(userData)
  mkdirSync(root, { recursive: true, mode: 0o700 })
  const rootInfo = lstatSync(root)
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new Error('Desktop user data is not a safe local directory.')
  }

  const destination = desktopProfileContextPath(root)
  const temporary = `${destination}.${randomUUID()}.tmp`
  try {
    const handle = await open(
      temporary,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
      0o600,
    )
    try {
      await handle.writeFile(serializeDesktopProfileContext(context), 'utf8')
      await handle.sync()
    } finally {
      await handle.close()
    }
    if (
      expectedSnapshot
      && !sameDiskSnapshot(
        expectedSnapshot,
        captureDesktopProfileContextDiskSnapshot(root),
      )
    ) {
      throw new Error('Desktop profile context changed while it was being updated.')
    }
    await rename(temporary, destination)
    await syncDirectoryWhereSupported(root)
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => null)
    throw error
  }
}

export async function persistDesktopProfileContextFile(
  userData: string,
  context: DesktopProfileContext,
): Promise<void> {
  const root = resolve(userData)
  await desktopProfileContextLock.runExclusive(
    desktopProfileContextPath(root),
    () => persistDesktopProfileContextFileWithSnapshot(root, context),
  )
}

/**
 * Serialize every cooperative profile-context write, including direct
 * persistence after an explicit choice, as a fresh read-modify-write. Electron
 * owns the application single-instance lock before these writers are activated,
 * while this shared context lock closes the final CAS-check-to-rename window
 * between in-process writers. The CAS snapshot also refuses to overwrite an
 * uncoordinated writer that changed the context while the updater was deciding.
 */
export async function updateDesktopProfileContextFile(
  userData: string,
  updater: (
    current: DesktopProfileContext,
  ) => DesktopProfileContext | Promise<DesktopProfileContext>,
): Promise<DesktopProfileContext> {
  const root = resolve(userData)
  const key = desktopProfileContextPath(root)
  return desktopProfileContextLock.runExclusive(key, async () => {
    const expectedSnapshot = captureDesktopProfileContextDiskSnapshot(root)
    const current = loadDesktopProfileContext(root)
    const next = await updater(current)
    await persistDesktopProfileContextFileWithSnapshot(root, next, expectedSnapshot)
    return next
  })
}

async function syncDirectoryWhereSupported(path: string): Promise<void> {
  let handle: Awaited<ReturnType<typeof open>> | null = null
  try {
    handle = await open(path, constants.O_RDONLY)
    await handle.sync()
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    // Windows and a few network filesystems do not expose fsync-capable
    // directory handles. The file itself was still fsynced before rename.
    if (!['EACCES', 'EINVAL', 'EISDIR', 'ENOTSUP', 'EPERM'].includes(code || '')) {
      throw error
    }
  } finally {
    await handle?.close().catch(() => null)
  }
}

export function profileKindEnvironment(kind: DesktopProfileKind): 'desktop-primary' | 'desktop-recovery' {
  return kind === 'primary' ? 'desktop-primary' : 'desktop-recovery'
}
