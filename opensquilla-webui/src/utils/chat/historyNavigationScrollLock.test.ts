import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { createHistoryNavigationScrollLock } from './historyNavigationScrollLock'

describe('createHistoryNavigationScrollLock', () => {
  it('ignores near-bottom smooth-scroll frames until minimap navigation ends', () => {
    const autoScroll = ref(true)
    const lock = createHistoryNavigationScrollLock(autoScroll)

    lock.start()
    lock.updateFromScroll(12)
    expect(autoScroll.value).toBe(false)
    expect(lock.locked).toBe(true)

    lock.finish()
    lock.updateFromScroll(12)
    expect(autoScroll.value).toBe(true)
    expect(lock.locked).toBe(false)

    lock.start()
    lock.updateFromScroll(12)
    lock.finish()
    lock.updateFromScroll(180)
    expect(autoScroll.value).toBe(false)
  })
})
