import { describe, it, expect } from 'vitest'
import {
  approvalChoiceForDecision,
  buildApprovalResolveBody,
  formatCountdown,
  resolutionFromPayload,
} from './useChatApprovals'

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

describe('approvalChoiceForDecision', () => {
  it('maps the three visible approval buttons to backend choices', () => {
    expect(approvalChoiceForDecision('allow-once')).toBe('allow_once')
    expect(approvalChoiceForDecision('allow-always')).toBe('allow_same_type')
    expect(approvalChoiceForDecision('deny')).toBe('deny')
  })
})

describe('buildApprovalResolveBody', () => {
  it('sends only id, namespace, approved, and choice for a plain approve', () => {
    const body = buildApprovalResolveBody('ap-1', 'exec', 'allow-once')
    expect(body).toEqual({ id: 'ap-1', namespace: 'exec', approved: true, choice: 'allow_once' })
  })

  it('never carries the removed allowAlways / rememberIntent params', () => {
    for (const decision of ['allow-once', 'allow-always', 'deny'] as const) {
      const body = buildApprovalResolveBody('ap', 'exec', decision)
      expect(body).not.toHaveProperty('allowAlways')
      expect(body).not.toHaveProperty('rememberIntent')
    }
  })

  it('marks a deny as not approved and keeps the deny choice', () => {
    const body = buildApprovalResolveBody('ap-2', 'exec', 'deny')
    expect(body.approved).toBe(false)
    expect(body.choice).toBe('deny')
  })

  it('expresses a sandbox allow-same-type through the choice alone', () => {
    const body = buildApprovalResolveBody('ap-3', 'exec', 'allow-always')
    expect(body.approved).toBe(true)
    expect(body.choice).toBe('allow_same_type')
    expect(body).not.toHaveProperty('allowAlways')
  })

  it('defaults a blank namespace to exec', () => {
    expect(buildApprovalResolveBody('ap-4', '', 'allow-once').namespace).toBe('exec')
  })
})
