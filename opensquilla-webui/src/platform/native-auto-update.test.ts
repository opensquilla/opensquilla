// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
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

describe('desktop update platform bridge', () => {
  it('web exposes an inert update API with a non-native idle state', async () => {
    const state = await createWebPlatform().updates.getState()

    expect(state).toMatchObject({
      status: 'idle',
      currentVersion: '',
      latestVersion: null,
      canNativeInstall: false,
    })
  })

  it('forwards desktop update state, actions, and subscriptions from the shell bridge', async () => {
    const unsubscribe = vi.fn()
    const checkForUpdates = vi.fn(async () => ({ status: 'checking' }))
    const downloadUpdate = vi.fn(async () => ({ status: 'downloading' }))
    const relaunchToUpdate = vi.fn(async () => ({ status: 'applying' }))
    const dismissUpdate = vi.fn(async () => ({ status: 'available', snoozedUntil: '2026-07-04T00:00:00.000Z' }))
    setDesktopApi({
      isAutoUpdateEnabled: async () => true,
      getUpdateState: async () => ({
        status: 'available',
        currentVersion: '1.0.0',
        latestVersion: '2.0.0',
        progress: null,
        checkedAt: null,
        error: null,
        snoozedUntil: null,
        canNativeInstall: true,
        releaseUrl: null,
      }),
      checkForUpdates,
      downloadUpdate,
      relaunchToUpdate,
      dismissUpdate,
      onUpdateState: () => unsubscribe,
    })

    const updates = createDesktopPlatform().updates
    expect(await updates.getState()).toMatchObject({ status: 'available', latestVersion: '2.0.0' })
    await updates.check()
    await updates.download()
    await updates.relaunch()
    await updates.dismiss()
    expect(checkForUpdates).toHaveBeenCalledTimes(1)
    expect(downloadUpdate).toHaveBeenCalledTimes(1)
    expect(relaunchToUpdate).toHaveBeenCalledTimes(1)
    expect(dismissUpdate).toHaveBeenCalledTimes(1)
    expect(updates.onState(() => undefined)).toBe(unsubscribe)
  })
})
