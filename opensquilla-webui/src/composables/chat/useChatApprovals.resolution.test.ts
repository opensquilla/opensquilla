import { describe, it, expect } from 'vitest'
import { formatCountdown, resolutionFromPayload } from './useChatApprovals'

describe('resolutionFromPayload', () => {
  it('maps an explicit expiry to a distinct expired state', () => {
    expect(resolutionFromPayload({ approved: false, resolution: 'expired' })).toBe('expired')
  })

  it('keeps an explicit deny distinct from an expiry', () => {
    expect(resolutionFromPayload({ approved: false, resolution: 'denied' })).toBe('denied')
  })

  it('maps an approval to approved', () => {
    expect(resolutionFromPayload({ approved: true, resolution: 'approved' })).toBe('approved')
  })

  it('falls back to denied/approved when no resolution field is present', () => {
    // Back-compat: older payloads without `resolution` still resolve.
    expect(resolutionFromPayload({ approved: false })).toBe('denied')
    expect(resolutionFromPayload({ approved: true })).toBe('approved')
  })

  it('treats expired as not-denied even though approved is false', () => {
    const r = resolutionFromPayload({ approved: false, resolution: 'expired' })
    expect(r).not.toBe('denied')
  })
})

describe('formatCountdown', () => {
  it('renders sub-minute counts as seconds', () => {
    expect(formatCountdown(0)).toBe('0s')
    expect(formatCountdown(45)).toBe('45s')
    expect(formatCountdown(59)).toBe('59s')
  })

  it('renders minute counts as m:ss', () => {
    expect(formatCountdown(60)).toBe('1:00')
    expect(formatCountdown(125)).toBe('2:05')
    expect(formatCountdown(300)).toBe('5:00')
  })

  it('clamps negatives to 0s', () => {
    expect(formatCountdown(-10)).toBe('0s')
  })
})
