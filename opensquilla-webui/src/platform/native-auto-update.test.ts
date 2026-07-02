// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'
import { createWebPlatform } from './web'
import { createDesktopPlatform } from './desktop'

// The update banner suppresses itself only when the host applies updates
// NATIVELY. These tests pin that decision per platform so the transitional
// behaviour (browser + unsigned Windows keep the notice; macOS hides it) — and
// its forward path (Windows hides it automatically once native update turns on)
// — can't silently regress.

function setDesktopApi(api: unknown): void {
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = api
}

afterEach(() => {
  setDesktopApi(undefined)
})

describe('nativeAutoUpdateEnabled', () => {
  it('is false on web — the browser never auto-updates, so the banner shows', async () => {
    expect(await createWebPlatform().nativeAutoUpdateEnabled()).toBe(false)
  })

  it('mirrors the shell when native update is ON (macOS / signed Windows) → banner hidden', async () => {
    setDesktopApi({ isAutoUpdateEnabled: async () => true })
    expect(await createDesktopPlatform().nativeAutoUpdateEnabled()).toBe(true)
  })

  it('mirrors the shell when native update is OFF (unsigned Windows) → banner shown', async () => {
    setDesktopApi({ isAutoUpdateEnabled: async () => false })
    expect(await createDesktopPlatform().nativeAutoUpdateEnabled()).toBe(false)
  })

  it('defaults to true (suppress) if an older shell lacks the bridge', async () => {
    setDesktopApi({})
    expect(await createDesktopPlatform().nativeAutoUpdateEnabled()).toBe(true)
  })

  it('defaults to true (suppress) if the bridge throws', async () => {
    setDesktopApi({
      isAutoUpdateEnabled: async () => {
        throw new Error('ipc boom')
      },
    })
    expect(await createDesktopPlatform().nativeAutoUpdateEnabled()).toBe(true)
  })
})
