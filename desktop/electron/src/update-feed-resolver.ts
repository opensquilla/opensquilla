// Pure release-tag resolution for the macOS desktop updater, split out of
// main.ts so it can be unit-tested without pulling in Electron.
//
// OpenSquilla ships two spellings of the same release: PEP440 for the Git tag /
// Python wheel (e.g. v0.5.0rc2) and npm semver for the Electron app metadata
// (0.5.0-rc2). electron-updater's GitHub provider filters release tags with
// semver.valid(), which rejects PEP440 rc tags, so a packaged prerelease build
// finds no updates. Even semver-spelled rc tags land on distinct electron-updater
// channels (rc1 vs rc2), so rc1 would never see rc2. This module resolves the
// correct candidate release ourselves; a generic feed is then pointed at it.

export const GITHUB_UPDATE_OWNER = 'opensquilla'
export const GITHUB_UPDATE_REPO = 'opensquilla'
export const MAC_UPDATE_FEED_ASSET = 'latest-mac.yml'

export interface ParsedReleaseTag {
  base: string
  rc: number | null
}

export interface ReleaseSummary {
  tag_name?: string
  draft?: boolean
  assets?: { name?: string }[]
}

export interface MacPrereleaseCandidate {
  tag: string
  version: string
  feedUrl: string
}

// Accept the PEP440 rc tag (v0.5.0rc2), the semver rc spelling (v0.5.0-rc2 /
// v0.5.0-rc.2), and a plain stable tag (v0.5.0). Returns null for anything else
// (doc/website releases, monorepo tags, malformed tags).
export function parseOpenSquillaReleaseTag(tag: string): ParsedReleaseTag | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-?rc\.?(\d+))?$/i.exec(String(tag ?? '').trim())
  if (!match) return null
  const [, major, minor, patch, rc] = match
  return {
    base: `${Number(major)}.${Number(minor)}.${Number(patch)}`,
    rc: rc === undefined ? null : Number(rc),
  }
}

// Given the running prerelease (base + rc) and the repo's releases, pick the
// highest same-base release that is newer than the current rc — a later rc or the
// final stable for this base — and that actually ships the macOS update feed. The
// final stable outranks any rc of the same base; among rcs, the higher wins.
// Returns null when nothing newer for this base is publishable (e.g. only the
// current rc exists, or the newer release is missing latest-mac.yml).
export function selectMacPrereleaseCandidate(
  current: { base: string; rc: number },
  releases: ReleaseSummary[],
): MacPrereleaseCandidate | null {
  let best: { parsed: ParsedReleaseTag; tag: string; rank: number } | null = null
  for (const release of releases) {
    if (release?.draft) continue
    const tag = String(release?.tag_name ?? '')
    const parsed = parseOpenSquillaReleaseTag(tag)
    if (!parsed || parsed.base !== current.base) continue
    const isStable = parsed.rc === null
    const isHigherRc = parsed.rc !== null && parsed.rc > current.rc
    if (!isStable && !isHigherRc) continue
    if (!(release.assets || []).some((asset) => asset?.name === MAC_UPDATE_FEED_ASSET)) continue
    const rank = isStable ? Number.MAX_SAFE_INTEGER : (parsed.rc as number)
    if (!best || rank > best.rank) best = { parsed, tag, rank }
  }
  if (!best) return null
  return {
    tag: best.tag,
    version: best.parsed.rc === null ? best.parsed.base : `${best.parsed.base}-rc${best.parsed.rc}`,
    feedUrl: `https://github.com/${GITHUB_UPDATE_OWNER}/${GITHUB_UPDATE_REPO}/releases/download/${best.tag}`,
  }
}
