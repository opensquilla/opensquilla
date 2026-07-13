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

interface RpcHandles {
  data?: { value: unknown }
  execute?: ReturnType<typeof vi.fn>
}

async function mountBanner(status: unknown, { desktop = false }: { desktop?: boolean } = {}) {
  vi.resetModules()
  document.body.innerHTML = ''
  // A truthy preload bridge flips platform detection to desktop.
  setDesktopApi(desktop ? { getOsLocale: async () => 'en' } : undefined)
  vi.doMock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
  const handles: RpcHandles = {}
  vi.doMock('@/composables/useRpc', async () => {
    const { ref } = await import('vue')
    const data = ref(status)
    const execute = vi.fn()
    handles.data = data
    handles.execute = execute
    return {
      useRpcCall: () => ({
        data,
        loading: ref(false),
        error: ref(null),
        execute,
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
  return { app, el, handles }
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
    expect(banner?.textContent).toContain('Another OpenSquilla profile is available')
    expect(banner?.textContent).toContain('/tmp/legacy-home')
    expect(banner?.textContent).toContain(
      'opensquilla migrate opensquilla --home /tmp/legacy-home',
    )
    // The narrow sidebar wraps the command onto multiple lines; the default
    // single-line scroll strip hides all but the first few characters there.
    expect(
      banner?.querySelector('.setup-command-block')?.classList.contains('setup-command-block--wrap'),
    ).toBe(true)
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
    expect(banner?.textContent).toContain('Import from another OpenSquilla installation')
    expect(banner?.textContent).not.toContain('opensquilla migrate')

    const cta = el.querySelector<HTMLButtonElement>('[data-testid="legacy-data-open-settings"]')
    expect(cta).toBeTruthy()
    cta?.click()
    await settle()
    expect(routerPush).toHaveBeenCalledWith('/settings/runtime')
    app.unmount()
  })
})

describe('SidebarSetupBanner readiness refresh', () => {
  it('re-fetches readiness and clears once a settings save invalidates it', async () => {
    const { app, el, handles } = await mountBanner({ needsOnboarding: true })
    expect(el.querySelector('.sidebar-setup-banner')).toBeTruthy()

    // A save hot-applies config, re-loads the Settings dialog data, and
    // signals invalidation; the banner must re-fetch instead of holding its
    // mount-time snapshot until the next full page reload.
    handles.execute!.mockImplementation(async () => {
      handles.data!.value = { needsOnboarding: false }
    })
    const { invalidateReadiness } = await import('@/composables/setup/useReadinessSummary')
    invalidateReadiness()
    await settle()

    expect(handles.execute).toHaveBeenCalled()
    expect(el.querySelector('.sidebar-setup-banner')).toBeNull()
    app.unmount()
  })

  it('stops listening for readiness invalidations after unmount', async () => {
    const { app, handles } = await mountBanner({ needsOnboarding: true })
    app.unmount()

    const { invalidateReadiness } = await import('@/composables/setup/useReadinessSummary')
    invalidateReadiness()

    expect(handles.execute).not.toHaveBeenCalled()
  })
})
