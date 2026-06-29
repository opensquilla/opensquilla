// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest'
import { isRestorableRoute, saveLastRoute, readLastRoute, LAST_ROUTE_KEY } from './lastRoute'

beforeEach(() => localStorage.clear())

describe('isRestorableRoute', () => {
  it('accepts the known top-level views and settings sections', () => {
    for (const p of [
      '/chat', '/sessions', '/approvals', '/agents', '/channels',
      '/cron', '/skills', '/overview', '/usage', '/logs',
      '/settings', '/settings/router', '/settings/auto',
    ]) {
      expect(isRestorableRoute(p)).toBe(true)
    }
  })

  it('rejects root, the chat draft, and unknown/removed paths', () => {
    for (const p of ['/', '/chat/new', '/health', '/nope', '/settingsx', '']) {
      expect(isRestorableRoute(p)).toBe(false)
    }
  })
})

describe('saveLastRoute / readLastRoute', () => {
  it('round-trips a restorable view', () => {
    saveLastRoute('/cron')
    expect(readLastRoute()).toBe('/cron')
    saveLastRoute('/settings/router')
    expect(readLastRoute()).toBe('/settings/router')
  })

  it('never persists a non-restorable path (draft / root)', () => {
    saveLastRoute('/chat/new')
    expect(localStorage.getItem(LAST_ROUTE_KEY)).toBeNull()
    saveLastRoute('/')
    expect(readLastRoute()).toBeNull()
  })

  it('re-validates on read: a stale/removed saved value yields null (falls back to default)', () => {
    localStorage.setItem(LAST_ROUTE_KEY, '/removed-view')
    expect(readLastRoute()).toBeNull()
  })
})
