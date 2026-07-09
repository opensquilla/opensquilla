// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  readinessLegacyData,
  type ReadinessStatus,
} from '@/composables/setup/useReadinessSummary'

const settle = () => new Promise((resolve) => setTimeout(resolve, 10))

const routerPush = vi.fn()

function setDesktopApi(api: unknown): void {
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = api
}

async function mountBanner(status: unknown, { desktop = false }: { desktop?: boolean } = {}) {
  vi.resetModules()
  document.body.innerHTML = ''
  // A truthy preload bridge flips platform detection to desktop.
  setDesktopApi(desktop ? { getOsLocale: async () => 'en' } : undefined)
  vi.doMock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
  vi.doMock('@/composables/useRpc', async () => {
    const { ref } = await import('vue')
    return {
      useRpcCall: () => ({
        data: ref(status),
        loading: ref(false),
        error: ref(null),
        execute: vi.fn(),
      }),
    }
  })
  const { createApp, nextTick } = await import('vue')
  const i18n = (await import('@/i18n')).default
  i18n.global.locale.value = 'en'
  const Component = (await import('./SidebarSetupBanner.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(Component)
  app.use(i18n)
  app.mount(el)
  await settle()
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  routerPush.mockReset()
  setDesktopApi(undefined)
})

describe('readinessLegacyData', () => {
  it('degrades absent, null, and malformed payloads to null', () => {
    expect(readinessLegacyData(null)).toBeNull()
    expect(readinessLegacyData(undefined)).toBeNull()
    expect(readinessLegacyData({})).toBeNull()
    expect(readinessLegacyData({ legacyData: null })).toBeNull()
    // Older gateways never send the field; future/broken shapes must not throw.
    expect(readinessLegacyData({ legacyData: 'yes' } as unknown as ReadinessStatus)).toBeNull()
    expect(
      readinessLegacyData({ legacyData: { path: '', kind: 'cli-home', command: 'x' } }),
    ).toBeNull()
    expect(
      readinessLegacyData({
        legacyData: { path: 123, kind: 'cli-home', command: 'x' },
      } as unknown as ReadinessStatus),
    ).toBeNull()
    expect(
      readinessLegacyData({ legacyData: { path: '/old', kind: 'cli-home', command: '  ' } }),
    ).toBeNull()
  })

  it('normalizes a populated block, tolerating a missing kind', () => {
    expect(
      readinessLegacyData({
        legacyData: {
          path: '/srv/dummy-legacy/.opensquilla',
          kind: 'cli-home',
          command: 'opensquilla migrate opensquilla',
        },
      }),
    ).toEqual({
      path: '/srv/dummy-legacy/.opensquilla',
      kind: 'cli-home',
      command: 'opensquilla migrate opensquilla',
    })
    expect(
      readinessLegacyData({
        legacyData: { path: '/old', command: 'opensquilla migrate' },
      } as unknown as ReadinessStatus),
    ).toEqual({ path: '/old', kind: '', command: 'opensquilla migrate' })
  })
})

describe('SidebarSetupBanner legacy advisory', () => {
  it('renders no advisory when the status payload has no legacyData', async () => {
    const { app, el } = await mountBanner({ needsOnboarding: false })
    expect(el.querySelector('[data-testid="legacy-data-banner"]')).toBeNull()
    app.unmount()
  })

  it('shows the path and a copyable migrate command on the web, and dismisses per session', async () => {
    const { app, el } = await mountBanner({
      needsOnboarding: false,
      legacyData: {
        path: '/tmp/legacy-home',
        kind: 'windows-portable',
        command: 'opensquilla migrate opensquilla --home /tmp/legacy-home',
      },
    })
    const banner = el.querySelector('[data-testid="legacy-data-banner"]')
    expect(banner).toBeTruthy()
    expect(banner?.textContent).toContain('Legacy OpenSquilla data found')
    expect(banner?.textContent).toContain('/tmp/legacy-home')
    expect(banner?.textContent).toContain(
      'opensquilla migrate opensquilla --home /tmp/legacy-home',
    )
    // The web advisory carries the CLI route, not the desktop settings CTA.
    expect(el.querySelector('[data-testid="legacy-data-open-settings"]')).toBeNull()

    ;(el.querySelector('[data-testid="legacy-data-dismiss"]') as HTMLButtonElement).click()
    await settle()
    expect(el.querySelector('[data-testid="legacy-data-banner"]')).toBeNull()
    app.unmount()
  })

  it('points at Settings → Runtime instead of the CLI command on desktop', async () => {
    const { app, el } = await mountBanner(
      {
        legacyData: {
          path: 'C:/OpenSquilla/data',
          kind: 'windows-portable',
          command: 'opensquilla migrate opensquilla',
        },
      },
      { desktop: true },
    )
    const banner = el.querySelector('[data-testid="legacy-data-banner"]')
    expect(banner).toBeTruthy()
    expect(banner?.textContent).toContain('C:/OpenSquilla/data')
    expect(banner?.textContent).not.toContain('opensquilla migrate')

    const cta = el.querySelector<HTMLButtonElement>('[data-testid="legacy-data-open-settings"]')
    expect(cta).toBeTruthy()
    cta?.click()
    await settle()
    expect(routerPush).toHaveBeenCalledWith('/settings/runtime')
    app.unmount()
  })
})
