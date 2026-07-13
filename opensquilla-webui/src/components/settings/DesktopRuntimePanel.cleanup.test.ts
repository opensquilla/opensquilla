// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const settle = () => new Promise((resolve) => setTimeout(resolve, 20))

function setDesktopApi(api: unknown): void {
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = api
}

function desktopApi(overrides: Record<string, unknown> = {}) {
  return {
    getOsLocale: async () => 'en',
    isAutoUpdateEnabled: async () => true,
    getGatewayStatus: async () => ({
      url: 'http://127.0.0.1:1',
      port: 1,
      owned: true,
      status: 'ready',
      logPath: '',
    }),
    ...overrides,
  }
}

function cleanupReport(
  mode: 'reset-current-settings' | 'delete-current-profile' | 'delete-all-user-data',
  outcome: 'ready' | 'blocked' = 'ready',
) {
  return {
    schema_version: 1 as const,
    outcome,
    stable_code: outcome === 'ready' ? 'cleanup_ready' : 'cleanup_history_invalid',
    mode,
    items: [
      {
        kind: 'primary-home',
        path: '/synthetic/user-data/opensquilla',
        exists: true,
        identity: '1:2',
      },
      {
        kind: 'recovery-profiles-container',
        path: '/synthetic/user-data/recovery-profiles',
        exists: false,
        identity: null,
      },
    ],
    transaction_id: 'synthetic-cleanup',
    revision: 42,
    scope_fingerprint: 'a'.repeat(64),
  }
}

async function mountPanel(api: ReturnType<typeof desktopApi>) {
  vi.resetModules()
  document.body.innerHTML = ''
  setDesktopApi(api)
  const { createApp, nextTick } = await import('vue')
  const i18n = (await import('@/i18n')).default
  i18n.global.locale.value = 'en'
  const Component = (await import('./DesktopRuntimePanel.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(Component)
  app.use(i18n)
  app.mount(el)
  await settle()
  await nextTick()
  return { app, el }
}

beforeEach(() => setDesktopApi(undefined))

describe('DesktopRuntimePanel cleanup', () => {
  it('hides cleanup controls when an older shell has no safe cleanup bridge', async () => {
    const { app, el } = await mountPanel(desktopApi())
    expect(el.querySelector('[data-testid="runtime-cleanup-all"]')).toBeNull()
    app.unmount()
  })

  it('lists every inspected location and sends only an opaque preview approval', async () => {
    const inspectDesktopCleanup = vi.fn(async () => ({
      ok: true,
      previewId: 'opaque-preview',
      report: cleanupReport('delete-all-user-data'),
      profile: { kind: 'primary' as const, recoveryId: null },
    }))
    const applyDesktopCleanup = vi.fn(async () => ({ ok: true, scheduled: true }))
    const discardDesktopCleanup = vi.fn(async () => true)
    const { app, el } = await mountPanel(desktopApi({
      inspectDesktopCleanup,
      discardDesktopCleanup,
      applyDesktopCleanup,
      revealDesktopUserData: vi.fn(async () => true),
    }))

    ;(el.querySelector('[data-testid="runtime-cleanup-all"]') as HTMLButtonElement).click()
    await settle()

    expect(inspectDesktopCleanup).toHaveBeenCalledWith({ mode: 'delete-all-user-data' })
    const summary = el.querySelector('[data-testid="runtime-cleanup-summary"]')
    expect(summary?.textContent).toContain('/synthetic/user-data/opensquilla')
    expect(summary?.textContent).toContain('/synthetic/user-data/recovery-profiles')
    expect(summary?.textContent).toContain('1 of 2 listed locations currently exist')
    expect(document.activeElement?.id).toBe('cleanup-summary-title')

    const apply = el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-apply"]')
    expect(apply?.disabled).toBe(true)
    const checkbox = summary?.querySelector<HTMLInputElement>('input[type="checkbox"]')
    checkbox!.checked = true
    checkbox!.dispatchEvent(new Event('change', { bubbles: true }))
    const phrase = summary?.querySelector<HTMLInputElement>('input[type="text"]')
    phrase!.value = 'DELETE ALL OPENSQUILLA DATA'
    phrase!.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    expect(apply?.disabled).toBe(false)

    apply!.click()
    await settle()
    expect(applyDesktopCleanup).toHaveBeenCalledWith({
      previewId: 'opaque-preview',
      acknowledged: true,
      confirmation: 'DELETE ALL OPENSQUILLA DATA',
    })
    const payload = (applyDesktopCleanup.mock.calls as unknown[][])[0]?.[0] as Record<string, unknown>
    expect(payload).not.toHaveProperty('mode')
    expect(payload).not.toHaveProperty('path')
    expect(payload).not.toHaveProperty('transaction_id')
    expect(payload).not.toHaveProperty('revision')
    app.unmount()
  })

  it('shows blocked inspection recovery information without an apply button', async () => {
    const report = cleanupReport('delete-current-profile', 'blocked')
    const { app, el } = await mountPanel(desktopApi({
      inspectDesktopCleanup: vi.fn(async () => ({
        ok: false,
        previewId: null,
        report,
        profile: { kind: 'recovery' as const, recoveryId: '01234567-89ab-4cde-8fab-0123456789ab' },
      })),
      discardDesktopCleanup: vi.fn(async () => true),
      applyDesktopCleanup: vi.fn(),
      revealDesktopUserData: vi.fn(async () => true),
    }))

    ;(el.querySelector('[data-testid="runtime-cleanup-profile"]') as HTMLButtonElement).click()
    await settle()

    const summary = el.querySelector('[data-testid="runtime-cleanup-summary"]')
    expect(summary?.getAttribute('aria-labelledby')).toBe('cleanup-summary-title')
    expect(summary?.textContent).toContain('cleanup_history_invalid')
    expect(summary?.textContent).toContain('Recovery profile')
    expect(el.querySelector('[data-testid="runtime-cleanup-apply"]')).toBeNull()
    expect(summary?.querySelector('input[type="checkbox"]')).toBeNull()
    expect(summary?.querySelector('input[type="text"]')).toBeNull()
    app.unmount()
  })

  it('discards the main-process preview and returns focus to the trigger on cancel', async () => {
    const discardDesktopCleanup = vi.fn(async () => true)
    const { app, el } = await mountPanel(desktopApi({
      inspectDesktopCleanup: vi.fn(async () => ({
        ok: true,
        previewId: 'cancel-preview',
        report: cleanupReport('delete-current-profile'),
        profile: { kind: 'primary' as const, recoveryId: null },
      })),
      discardDesktopCleanup,
      applyDesktopCleanup: vi.fn(),
      revealDesktopUserData: vi.fn(async () => true),
    }))

    const trigger = el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-profile"]')!
    trigger.click()
    await settle()
    el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-cancel"]')!.click()
    await settle()

    expect(discardDesktopCleanup).toHaveBeenCalledWith({ previewId: 'cancel-preview' })
    expect(el.querySelector('[data-testid="runtime-cleanup-summary"]')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    app.unmount()
  })

  it('re-presents a changed inventory with a new one-shot preview', async () => {
    const initial = cleanupReport('delete-current-profile')
    const changed = {
      ...cleanupReport('delete-current-profile'),
      items: [{
        kind: 'new-profile-log',
        path: '/synthetic/user-data/new-log',
        exists: true,
        identity: '9:9',
      }],
      revision: 43,
      scope_fingerprint: 'b'.repeat(64),
    }
    const applyDesktopCleanup = vi.fn(async () => ({
      ok: false,
      previewId: 'replacement-preview',
      report: changed,
      profile: { kind: 'primary' as const, recoveryId: null },
      detail: 'The cleanup locations changed while the local runtime stopped. Review them again.',
    }))
    const { app, el } = await mountPanel(desktopApi({
      inspectDesktopCleanup: vi.fn(async () => ({
        ok: true,
        previewId: 'initial-preview',
        report: initial,
        profile: { kind: 'primary' as const, recoveryId: null },
      })),
      discardDesktopCleanup: vi.fn(async () => true),
      applyDesktopCleanup,
      revealDesktopUserData: vi.fn(async () => true),
    }))

    el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-profile"]')!.click()
    await settle()
    const checkbox = el.querySelector<HTMLInputElement>(
      '[data-testid="runtime-cleanup-summary"] input[type="checkbox"]',
    )!
    checkbox.checked = true
    checkbox.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-apply"]')!.click()
    await settle()

    const summary = el.querySelector('[data-testid="runtime-cleanup-summary"]')
    expect(summary?.textContent).toContain('/synthetic/user-data/new-log')
    expect(summary?.textContent).not.toContain('/synthetic/user-data/opensquilla')
    expect(summary?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(false)
    expect(el.querySelector<HTMLButtonElement>('[data-testid="runtime-cleanup-apply"]')?.disabled).toBe(true)
    expect(document.activeElement?.id).toBe('cleanup-summary-title')
    app.unmount()
  })
})
