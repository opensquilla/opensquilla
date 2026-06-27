import { describe, it, expect } from 'vitest'
import {
  bindingMatches,
  bindingsEqual,
  eventToBinding,
  formatBinding,
  type Binding,
} from './keychord'

// The unit env is `node` (no DOM / KeyboardEvent). The keychord helpers only
// read key + the four modifier flags, so a plain object stands in fine.
function evt(opts: Partial<KeyboardEvent>): KeyboardEvent {
  return {
    key: '',
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...opts,
  } as KeyboardEvent
}

describe('eventToBinding', () => {
  it('records a Ctrl chord on non-Mac', () => {
    expect(eventToBinding(evt({ key: 'k', ctrlKey: true }), false)).toEqual({
      primary: true,
      alt: undefined,
      shift: undefined,
      key: 'k',
    })
  })

  it('records a Cmd+Shift chord on Mac and lower-cases the key', () => {
    expect(eventToBinding(evt({ key: 'K', metaKey: true, shiftKey: true }), true)).toEqual({
      primary: true,
      alt: undefined,
      shift: true,
      key: 'k',
    })
  })

  it('returns null without the platform-primary modifier', () => {
    // Ctrl held but we are on Mac, where Cmd is primary.
    expect(eventToBinding(evt({ key: 'k', ctrlKey: true }), true)).toBeNull()
    // Bare letter, no primary modifier.
    expect(eventToBinding(evt({ key: 'k' }), false)).toBeNull()
  })

  it('returns null for a lone modifier press', () => {
    expect(eventToBinding(evt({ key: 'Shift', shiftKey: true, ctrlKey: true }), false)).toBeNull()
  })
})

describe('bindingMatches', () => {
  const palette: Binding = { primary: true, key: 'k' }
  const newChat: Binding = { primary: true, shift: true, key: 'k' }

  it('matches Ctrl+K to the palette binding on non-Mac', () => {
    expect(bindingMatches(evt({ key: 'k', ctrlKey: true }), palette, false)).toBe(true)
  })

  it('does not match when Shift differs', () => {
    expect(bindingMatches(evt({ key: 'k', ctrlKey: true, shiftKey: true }), palette, false)).toBe(false)
    expect(bindingMatches(evt({ key: 'k', ctrlKey: true, shiftKey: true }), newChat, false)).toBe(true)
  })

  it('rejects when the secondary modifier is also held (mac Ctrl+Cmd+K)', () => {
    expect(bindingMatches(evt({ key: 'k', metaKey: true, ctrlKey: true }), palette, true)).toBe(false)
  })

  it('never matches a null binding (disabled shortcut)', () => {
    expect(bindingMatches(evt({ key: 'k', ctrlKey: true }), null, false)).toBe(false)
  })
})

describe('formatBinding', () => {
  it('renders compact glyphs on Mac', () => {
    expect(formatBinding({ primary: true, shift: true, key: 'k' }, true)).toBe('⌘⇧K')
  })

  it('renders +-joined names off Mac', () => {
    expect(formatBinding({ primary: true, shift: true, key: 'k' }, false)).toBe('Ctrl+Shift+K')
  })

  it('returns empty for a null binding', () => {
    expect(formatBinding(null, false)).toBe('')
  })
})

describe('bindingsEqual', () => {
  it('treats normalized modifier flags as equal', () => {
    expect(bindingsEqual({ primary: true, key: 'k' }, { primary: true, shift: false, key: 'k' })).toBe(true)
  })
  it('distinguishes different chords', () => {
    expect(bindingsEqual({ primary: true, key: 'k' }, { primary: true, shift: true, key: 'k' })).toBe(false)
  })
})
