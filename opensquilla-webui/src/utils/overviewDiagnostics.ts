// Pure helpers behind the Overview diagnostics actions (copy-JSON, "diagnose
// with agent", finding→settings deep links, provider latency line). Kept out
// of the component so privacy-sensitive normalization and the conservative
// surface→settings map stay unit-testable without mounting the view.

export interface DiagnosticFindingLike {
  surface?: string
  severity?: string
  readinessImpact?: string
  evidence?: Record<string, unknown>
}

export interface FindingSettingsLink {
  path: string
  hash?: string
}

// A home directory embedded in serialized diagnostics leaks the local account
// name. Collapse `/Users/<name>/` (macOS) and `/home/<name>/` (Linux) to `~/`.
// The username segment excludes `/`, `"` and `\` so the match never crosses a
// JSON string boundary or an escape sequence.
const HOME_PATH_RE = /\/(?:Users|home)\/[^/"\\]+\//g

export function normalizeHomePaths(text: string): string {
  return text.replace(HOME_PATH_RE, '~/')
}

// Minimal XML escaping (& < >) so a report wrapped in an <untrusted> envelope
// cannot close the tag or smuggle markup into the prompt.
export function xmlEscape(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// The in-app "diagnose with agent" hand-off needs a working provider: when a
// provider finding blocks readiness the agent turn itself would fail, so the
// action must be hidden instead of sending the operator into a dead chat.
export function providerBlocksAgent(
  findings: readonly DiagnosticFindingLike[] | undefined | null,
): boolean {
  return (findings || []).some(finding =>
    String(finding?.surface || '') === 'provider'
    && (
      String(finding?.readinessImpact || '') === 'blocks_ready'
      || String(finding?.severity || '') === 'error'
    ),
  )
}

// Only providerIds shaped like registry slugs are trusted into a URL hash.
const PROVIDER_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

// Conservative surface→settings map: only surfaces with an unambiguous
// settings section get a deep link; everything else renders no link at all.
export function settingsLinkForFinding(
  finding: DiagnosticFindingLike | undefined | null,
): FindingSettingsLink | null {
  const surface = String(finding?.surface || '')
  if (surface === 'provider') {
    const providerId = finding?.evidence?.providerId
    if (typeof providerId === 'string' && PROVIDER_ID_RE.test(providerId)) {
      return { path: '/settings/provider', hash: `#provider-${providerId}` }
    }
    return { path: '/settings/provider' }
  }
  if (surface === 'channels') {
    // Runtime findings carry the channel name in evidence once the backend
    // populates it; a nameless finding degrades to the bare section.
    const name = finding?.evidence?.channelName ?? finding?.evidence?.channel
    if (typeof name === 'string' && name.trim() && name !== 'new') {
      return { path: '/settings/channels', hash: `#channel-${encodeURIComponent(name.trim())}` }
    }
    return { path: '/settings/channels' }
  }
  if (surface === 'router' || surface === 'squilla_router') {
    return { path: '/settings/modelStrategy' }
  }
  return null
}

function finiteNonNegative(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

function formatTtft(ms: number): string {
  if (ms >= 1000) {
    const seconds = ms / 1000
    return `${seconds >= 10 ? Math.round(seconds) : Number(seconds.toFixed(1))}s`
  }
  return `${Math.round(ms)}ms`
}

// Compact mono latency readout, e.g. 'p50 380ms · p95 1.2s · 87 samples/60min'.
// Every field is optional: backends that predate TTFT stats send no latency
// object at all, and low-sample windows null out individual percentiles —
// returns null when nothing is renderable so callers can skip the line.
export function formatLatencyLine(latency: unknown): string | null {
  if (!latency || typeof latency !== 'object' || Array.isArray(latency)) return null
  const record = latency as Record<string, unknown>
  const parts: string[] = []
  const p50 = finiteNonNegative(record.p50TtftMs)
  const p95 = finiteNonNegative(record.p95TtftMs)
  if (p50 != null) parts.push(`p50 ${formatTtft(p50)}`)
  if (p95 != null) parts.push(`p95 ${formatTtft(p95)}`)
  const samples = finiteNonNegative(record.samples)
  if (samples != null) {
    const windowMinutes = finiteNonNegative(record.windowMinutes)
    parts.push(windowMinutes != null ? `${samples} samples/${windowMinutes}min` : `${samples} samples`)
  }
  return parts.length ? parts.join(' · ') : null
}
