import { describe, expect, it } from 'vitest'
import { parseChannelHash } from './useSettingsSection'

describe('parseChannelHash', () => {
  it('parses edit targets and decodes names', () => {
    expect(parseChannelHash('#channel-team-slack')).toEqual({ kind: 'edit', name: 'team-slack' })
    expect(parseChannelHash('#channel-a%20b')).toEqual({ kind: 'edit', name: 'a b' })
    expect(parseChannelHash('channel-x')).toEqual({ kind: 'edit', name: 'x' })
  })

  it('reserves #channel-new for the compose form', () => {
    expect(parseChannelHash('#channel-new')).toEqual({ kind: 'new' })
  })

  it('rejects everything else', () => {
    expect(parseChannelHash('#provider-openai')).toBeNull()
    expect(parseChannelHash('#channel-')).toBeNull()
    expect(parseChannelHash('')).toBeNull()
    expect(parseChannelHash(undefined)).toBeNull()
    expect(parseChannelHash(42)).toBeNull()
  })
})
