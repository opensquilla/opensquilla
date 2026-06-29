import { afterEach, describe, expect, it } from 'vitest'
import {
  clearSessionNavigationDiag,
  readSessionNavigationDiag,
  recordSessionNavigationDiag,
  setSessionNavigationDiagStorageForTest,
  type SessionNavigationDiagStorage,
} from './sessionNavigationDiag'

class MemoryStorage implements SessionNavigationDiagStorage {
  private values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }
}

describe('sessionNavigationDiag', () => {
  afterEach(() => {
    setSessionNavigationDiagStorageForTest(null)
  })

  it('records newest entries first with session context', () => {
    setSessionNavigationDiagStorageForTest(new MemoryStorage())

    recordSessionNavigationDiag('send.start', { requestSession: 'A', current: 'A' })
    recordSessionNavigationDiag('send.response.stale', {
      requestSession: 'A',
      responseSession: 'A',
      current: 'B',
      reason: 'current_session_changed',
    })

    expect(readSessionNavigationDiag()).toMatchObject([
      {
        source: 'send.response.stale',
        requestSession: 'A',
        responseSession: 'A',
        current: 'B',
        reason: 'current_session_changed',
      },
      {
        source: 'send.start',
        requestSession: 'A',
        current: 'A',
      },
    ])
  })

  it('clears stored diagnostics', () => {
    setSessionNavigationDiagStorageForTest(new MemoryStorage())

    recordSessionNavigationDiag('persistSession', { from: 'A', to: 'B' })
    clearSessionNavigationDiag()

    expect(readSessionNavigationDiag()).toEqual([])
  })
})
