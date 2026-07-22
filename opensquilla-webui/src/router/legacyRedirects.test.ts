import { describe, expect, it } from 'vitest'
import { legacyChannelHashRedirect } from './legacyRedirects'

describe('legacyChannelHashRedirect', () => {
  it('rewrites the reserved compose hash to the workspace takeover', () => {
    expect(legacyChannelHashRedirect({ path: '/settings/channels', hash: '#channel-new' }))
      .toEqual({ path: '/channels', query: { compose: '1' }, replace: true })
  })

  it('rewrites named channel hashes into the in-place editor', () => {
    expect(legacyChannelHashRedirect({ path: '/settings/channels', hash: '#channel-team-slack' }))
      .toEqual({
        path: '/channels',
        query: { channel: 'team-slack', tab: 'configuration', edit: '1' },
        replace: true,
      })
    // Encoded names decode through parseChannelHash's contract.
    expect(legacyChannelHashRedirect({ path: '/settings/channels', hash: '#channel-a%20b' }))
      .toEqual({
        path: '/channels',
        query: { channel: 'a b', tab: 'configuration', edit: '1' },
        replace: true,
      })
  })

  it('leaves the bare section and unrelated routes alone', () => {
    expect(legacyChannelHashRedirect({ path: '/settings/channels', hash: '' })).toBeNull()
    expect(legacyChannelHashRedirect({ path: '/settings/channels', hash: '#provider-openai' })).toBeNull()
    expect(legacyChannelHashRedirect({ path: '/settings/provider', hash: '#channel-x' })).toBeNull()
    expect(legacyChannelHashRedirect({ path: '/channels', hash: '#channel-x' })).toBeNull()
  })
})
