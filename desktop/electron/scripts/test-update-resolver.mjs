import assert from 'node:assert/strict'

import {
  parseOpenSquillaReleaseTag,
  selectMacPrereleaseCandidate,
} from '../dist/update-feed-resolver.js'

// This exercises the resolver shipped after Preview 2. It proves that clients
// containing this resolver can select later releases; it does not prove that
// the already-published Preview 1/2 binaries can discover Preview 3.

// --- tag parsing: PEP440 rc, semver rc, stable, and rejects ---
assert.deepEqual(parseOpenSquillaReleaseTag('v0.5.0rc2'), { base: '0.5.0', rc: 2 })
assert.deepEqual(parseOpenSquillaReleaseTag('0.5.0-rc2'), { base: '0.5.0', rc: 2 })
assert.deepEqual(parseOpenSquillaReleaseTag('v0.5.0-rc.3'), { base: '0.5.0', rc: 3 })
assert.deepEqual(parseOpenSquillaReleaseTag('v0.5.0'), { base: '0.5.0', rc: null })
assert.equal(parseOpenSquillaReleaseTag('website-2026-01'), null)
assert.equal(parseOpenSquillaReleaseTag('v0.5'), null)

const withMacFeed = (tag) => ({ tag_name: tag, assets: [{ name: 'latest-mac.yml' }] })
const noMacFeed = (tag) => ({ tag_name: tag, assets: [{ name: 'OpenSquilla-mac.zip' }] })

// 1. A resolver-enabled client on 0.5.0-rc1 sees v0.5.0rc2 (PEP440 tag).
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 1 }, [
    withMacFeed('v0.5.0rc2'),
    withMacFeed('v0.5.0rc1'),
  ])
  assert.ok(c, 'rc1 should find rc2')
  assert.equal(c.tag, 'v0.5.0rc2')
  assert.equal(c.version, '0.5.0-rc2')
  assert.equal(c.feedUrl, 'https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc2')
}

// 2. A resolver-enabled client on 0.5.0-rc2 sees v0.5.0rc3.
{
  const c = selectMacPrereleaseCandidate(
    { base: '0.5.0', rc: 2 },
    [withMacFeed('v0.5.0rc3'), withMacFeed('v0.5.0rc2')],
  )
  assert.ok(c)
  assert.equal(c.tag, 'v0.5.0rc3')
  assert.equal(c.version, '0.5.0-rc3')
}

// 3. 0.5.0-rc2 sees the final stable v0.5.0 (stable outranks a later rc).
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 2 }, [
    withMacFeed('v0.5.0'),
    withMacFeed('v0.5.0rc3'),
    withMacFeed('v0.5.0rc2'),
  ])
  assert.ok(c, 'rc2 should find a candidate')
  assert.equal(c.tag, 'v0.5.0')
  assert.equal(c.version, '0.5.0')
}

// 2b. Two-digit rc ordering is numeric, not string: rc9 sees rc10 (not the
//     reverse). electron-updater's own semver gate sorts rc10 below rc9, which is
//     why the resolver path also sets allowDowngrade — see main.ts.
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 9 }, [
    withMacFeed('v0.5.0rc10'),
    withMacFeed('v0.5.0rc9'),
  ])
  assert.ok(c, 'rc9 should find rc10')
  assert.equal(c.tag, 'v0.5.0rc10')
  assert.equal(c.version, '0.5.0-rc10')
}
// rc10 does not regress to rc9.
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 10 }, [
    withMacFeed('v0.5.0rc10'),
    withMacFeed('v0.5.0rc9'),
  ])
  assert.equal(c, null, 'rc10 must not pick the lower rc9')
}

// 4. A prerelease does NOT jump to a different base's preview (0.5.0-rc2 ignores v0.6.0rc1).
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 2 }, [
    withMacFeed('v0.6.0rc1'),
    withMacFeed('v0.5.0rc2'),
  ])
  assert.equal(c, null, 'rc2 must not cross to a different base')
}

// 4a. A newer same-base release without latest-mac.yml is skipped.
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 1 }, [noMacFeed('v0.5.0rc2')])
  assert.equal(c, null, 'candidate without latest-mac.yml is skipped')
}

// 4b. When the highest release lacks the feed, fall back to the highest that has it.
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 1 }, [
    noMacFeed('v0.5.0rc3'),
    withMacFeed('v0.5.0rc2'),
  ])
  assert.ok(c, 'should fall back to rc2 which has the feed')
  assert.equal(c.tag, 'v0.5.0rc2')
}

// 5. No newer same-base release → no candidate (current rc is the latest).
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 2 }, [withMacFeed('v0.5.0rc2')])
  assert.equal(c, null, 'only the current rc exists → up to date')
}

// 6. Draft releases are ignored.
{
  const c = selectMacPrereleaseCandidate({ base: '0.5.0', rc: 1 }, [
    { tag_name: 'v0.5.0rc2', draft: true, assets: [{ name: 'latest-mac.yml' }] },
  ])
  assert.equal(c, null, 'draft releases are not upgrade candidates')
}

console.log('Update resolver tests passed.')
