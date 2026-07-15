export type ProfileSourceKind = 'cli-home' | 'desktop-home' | 'windows-portable'

const PROFILE_SOURCE_KINDS = new Set<ProfileSourceKind>([
  'cli-home',
  'desktop-home',
  'windows-portable',
])

const PROFILE_SOURCE_LABEL_KEYS: Record<ProfileSourceKind, string> = {
  'cli-home': 'setup.runtime.migrationSourceCli',
  'desktop-home': 'setup.runtime.migrationSourceDesktop',
  'windows-portable': 'setup.runtime.migrationSourceWindowsPortable',
}

export function isProfileSourceKind(value: unknown): value is ProfileSourceKind {
  return typeof value === 'string' && PROFILE_SOURCE_KINDS.has(value as ProfileSourceKind)
}

export function profileSourceGroup(
  kind: string,
): 'supported' | 'historical' | 'unknown' {
  if (kind === 'cli-home' || kind === 'desktop-home') return 'supported'
  if (kind === 'windows-portable') return 'historical'
  return 'unknown'
}

export function profileSourceLabelKey(kind: string): string {
  return isProfileSourceKind(kind)
    ? PROFILE_SOURCE_LABEL_KEYS[kind]
    : 'setup.runtime.migrationSourceUnknown'
}

export function formatEstimatedActivity(
  value: string,
  locale: string,
  now = Date.now(),
): string | null {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return null
  const deltaSeconds = (timestamp - now) / 1000
  const magnitude = Math.abs(deltaSeconds)
  let unit: Intl.RelativeTimeFormatUnit = 'second'
  let divisor = 1
  if (magnitude >= 365 * 24 * 60 * 60) {
    unit = 'year'
    divisor = 365 * 24 * 60 * 60
  } else if (magnitude >= 30 * 24 * 60 * 60) {
    unit = 'month'
    divisor = 30 * 24 * 60 * 60
  } else if (magnitude >= 24 * 60 * 60) {
    unit = 'day'
    divisor = 24 * 60 * 60
  } else if (magnitude >= 60 * 60) {
    unit = 'hour'
    divisor = 60 * 60
  } else if (magnitude >= 60) {
    unit = 'minute'
    divisor = 60
  }
  return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(
    Math.round(deltaSeconds / divisor),
    unit,
  )
}
