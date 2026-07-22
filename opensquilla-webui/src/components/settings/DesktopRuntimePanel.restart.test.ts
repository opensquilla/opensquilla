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
  const { toasts } = (await import('@/composables/useToasts')).useToasts()
  toasts.value = []
  return { app, el, toasts }
}

function findRestartButton(el: HTMLElement): HTMLButtonElement {
  const button = Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
    .find((candidate) => candidate.textContent?.includes('Restart runtime'))
  if (!button) throw new Error('Restart runtime button was not rendered')
  return button
}

beforeEach(() => setDesktopApi(undefined))

describe('DesktopRuntimePanel runtime restart', () => {
  it('announces restarting only when the desktop retry succeeds', async () => {
    const getGatewayStatus = vi.fn(async () => ({
      url: 'http://127.0.0.1:1',
      port: 1,
      owned: true,
      status: 'ready' as const,
      logPath: '',
    }))
    const retryStartup = vi.fn(async () => ({ ok: true }))
    const { app, el, toasts } = await mountPanel(desktopApi({
      getGatewayStatus,
      retryStartup,
    }))

    findRestartButton(el).click()
    await settle()

    expect(retryStartup).toHaveBeenCalledTimes(1)
    expect(getGatewayStatus).toHaveBeenCalledTimes(2)
    expect(toasts.value[toasts.value.length - 1]).toMatchObject({
      message: 'Restarting the local runtime…',
      tone: 'info',
    })
    app.unmount()
  })

  it('surfaces an explicit retry failure without claiming the runtime is restarting', async () => {
    const getGatewayStatus = vi.fn(async () => ({
      url: 'http://127.0.0.1:1',
      port: 1,
      owned: true,
      status: 'ready' as const,
      logPath: '',
    }))
    const retryStartup = vi.fn(async () => ({
      ok: false,
      error: 'The previous gateway is still shutting down.',
    }))
    const { app, el, toasts } = await mountPanel(desktopApi({
      getGatewayStatus,
      retryStartup,
    }))

    findRestartButton(el).click()
    await settle()

    expect(retryStartup).toHaveBeenCalledTimes(1)
    expect(getGatewayStatus).toHaveBeenCalledTimes(1)
    expect(toasts.value.map((toast) => toast.message)).not.toContain(
      'Restarting the local runtime…',
    )
    expect(toasts.value[toasts.value.length - 1]).toMatchObject({
      message: 'Restart failed: The previous gateway is still shutting down.',
      tone: 'danger',
    })
    app.unmount()
  })

  it('keeps a migration restart failure visible when the desktop retry is rejected', async () => {
    const migrationDismissLastResult = vi.fn(async () => ({ ok: true }))
    const retryStartup = vi.fn(async () => ({
      ok: false,
      error: 'The previous gateway is still shutting down.',
    }))
    const { app, el } = await mountPanel(desktopApi({
      getDesktopProfileKind: async () => 'primary',
      retryStartup,
      migrationPeekLastResult: async () => ({
        ok: false,
        migrationApplied: true,
        restartOk: false,
        failureCode: 'gateway_restart_failed',
        failureStage: 'restart',
      }),
      migrationDismissLastResult,
      migrationSummary: async () => ({ ok: true }),
      migrationRun: async () => ({ ok: true }),
    }))

    const restart = el.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-restart"]')
    expect(restart).toBeTruthy()
    restart!.click()
    await settle()

    expect(retryStartup).toHaveBeenCalledTimes(1)
    expect(migrationDismissLastResult).not.toHaveBeenCalled()
    expect(el.querySelector('[data-testid="runtime-migration-applied-restart-failed"]'))
      .toBeTruthy()
    app.unmount()
  })

  it('keeps a migration restart failure visible when refreshed status cannot be read', async () => {
    const migrationDismissLastResult = vi.fn(async () => ({ ok: true }))
    const retryStartup = vi.fn(async () => ({ ok: true }))
    const getGatewayStatus = vi.fn()
      .mockResolvedValueOnce({
        url: 'http://127.0.0.1:1',
        port: 1,
        owned: true,
        status: 'ready' as const,
        logPath: '',
      })
      .mockRejectedValueOnce(new Error('status unavailable'))
    const { app, el } = await mountPanel(desktopApi({
      getGatewayStatus,
      getDesktopProfileKind: async () => 'primary',
      retryStartup,
      migrationPeekLastResult: async () => ({
        ok: false,
        migrationApplied: true,
        restartOk: false,
        failureCode: 'gateway_restart_failed',
        failureStage: 'restart',
      }),
      migrationDismissLastResult,
      migrationSummary: async () => ({ ok: true }),
      migrationRun: async () => ({ ok: true }),
    }))

    const restart = el.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-restart"]')
    expect(restart).toBeTruthy()
    restart!.click()
    await settle()

    expect(retryStartup).toHaveBeenCalledTimes(1)
    expect(getGatewayStatus).toHaveBeenCalledTimes(2)
    expect(migrationDismissLastResult).not.toHaveBeenCalled()
    expect(el.querySelector('[data-testid="runtime-migration-applied-restart-failed"]'))
      .toBeTruthy()
    app.unmount()
  })
})
