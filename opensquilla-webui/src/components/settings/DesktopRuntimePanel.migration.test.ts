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

// Dry-run report carrying the non-empty-target preflight error (synthetic).
const reportNeedingOverwrite = {
  items: [
    { kind: 'preflight/target', status: 'error', reason: 'target home already contains session data' },
    { kind: 'state/sessions', status: 'planned', reason: '' },
  ],
  paused_jobs: [{ id: '1', name: 'daily-digest', cron_expr: '0 9 * * *' }],
  preflight: { disk_required_bytes: 1024, disk_free_bytes: 4096 },
  notes: [],
}

const reportNeedingOverwriteWithBlockingError = {
  ...reportNeedingOverwrite,
  items: [
    ...reportNeedingOverwrite.items,
    { kind: 'preflight/disk', status: 'error', reason: 'not enough free disk space' },
  ],
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

beforeEach(() => {
  setDesktopApi(undefined)
})

describe('DesktopRuntimePanel legacy-data import', () => {
  it('hides the row when the desktop shell predates the migration bridge', async () => {
    const { app, el } = await mountPanel(desktopApi())
    expect(el.querySelector('[data-testid="runtime-migration-open"]')).toBeNull()
    app.unmount()
  })

  it('shows the dry-run summary and gates Import behind the overwrite checkbox', async () => {
    const migrationSummary = vi.fn(async () => ({
      // The CLI exits nonzero for a blocked dry run even though stdout carries
      // the valid report that explains how the operator can unblock it.
      ok: false,
      candidate: { kind: 'windows-portable', path: '/tmp/legacy-home' },
      report: reportNeedingOverwrite,
      previewId: 'preview-overwrite',
    }))
    const progressUnsub = vi.fn()
    // Holder object: TS narrowing does not track assignments made from callbacks.
    const progress: { cb: ((state: { phase: string; detail?: string }) => void) | null } = {
      cb: null,
    }
    const api = desktopApi({
      migrationSummary,
      migrationRun: vi.fn(async () => ({ ok: true })),
      onMigrationProgress: vi.fn((cb: (state: { phase: string; detail?: string }) => void) => {
        progress.cb = cb
        return progressUnsub
      }),
    })
    const { app, el } = await mountPanel(api)

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    expect(migrationSummary).toHaveBeenCalledTimes(1)
    const summary = el.querySelector('[data-testid="runtime-migration-summary"]')
    expect(summary).toBeTruthy()
    expect(summary?.textContent).toContain('/tmp/legacy-home')
    expect(summary?.textContent).toContain('windows-portable')
    expect(summary?.textContent).toContain('1 planned')
    expect(summary?.textContent).toContain('1 with errors')
    expect(summary?.textContent).toContain('target home already contains session data')

    // Import stays disabled until the operator opts into overwrite-with-backups.
    const run = el.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-run"]')
    expect(run?.disabled).toBe(true)
    const checkbox = el.querySelector<HTMLInputElement>(
      '[data-testid="runtime-migration-overwrite"] input[type="checkbox"]',
    )
    expect(checkbox).toBeTruthy()
    checkbox!.checked = true
    checkbox!.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    expect(run?.disabled).toBe(false)

    // Progress events surface as phase text while the block is open.
    progress.cb?.({ phase: 'applying', detail: 'copying state' })
    await settle()
    expect(summary?.textContent).toContain('applying — copying state')

    ;(el.querySelector('[data-testid="runtime-migration-cancel"]') as HTMLButtonElement).click()
    await settle()
    expect(el.querySelector('[data-testid="runtime-migration-summary"]')).toBeNull()
    expect(progressUnsub).toHaveBeenCalled()
    app.unmount()
  })

  it('keeps Import disabled when overwrite is acknowledged but another error remains', async () => {
    const api = desktopApi({
      migrationSummary: vi.fn(async () => ({
        ok: false,
        candidate: { kind: 'cli-home', path: '/tmp/legacy-home' },
        report: reportNeedingOverwriteWithBlockingError,
        previewId: 'preview-blocked',
      })),
      migrationRun: vi.fn(async () => ({ ok: true })),
    })
    const { app, el } = await mountPanel(api)

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    const summary = el.querySelector('[data-testid="runtime-migration-summary"]')
    expect(summary?.textContent).toContain('not enough free disk space')
    const run = el.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-run"]')
    const checkbox = el.querySelector<HTMLInputElement>(
      '[data-testid="runtime-migration-overwrite"] input[type="checkbox"]',
    )
    expect(run?.disabled).toBe(true)
    checkbox!.checked = true
    checkbox!.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    expect(run?.disabled).toBe(true)

    app.unmount()
  })

  it('reports when no legacy data is found instead of opening the summary', async () => {
    const api = desktopApi({
      migrationSummary: vi.fn(async () => ({ ok: true, candidate: null, report: null })),
      migrationRun: vi.fn(async () => ({ ok: true })),
    })
    const { app, el } = await mountPanel(api)

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    expect(el.querySelector('[data-testid="runtime-migration-summary"]')).toBeNull()
    app.unmount()
  })

  it('rejects a report that is not bound to a trusted main-process preview', async () => {
    const api = desktopApi({
      migrationSummary: vi.fn(async () => ({
        ok: true,
        candidate: { kind: 'cli-home', path: '/tmp/legacy-home' },
        report: reportNeedingOverwrite,
      })),
      migrationRun: vi.fn(async () => ({ ok: true })),
    })
    const { app, el } = await mountPanel(api)

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    expect(el.querySelector('[data-testid="runtime-migration-summary"]')).toBeNull()
    app.unmount()
  })

  it('consumes a durable terminal result when the replacement renderer mounts', async () => {
    const migrationTakeLastResult = vi.fn(async () => ({
      ok: false,
      migrationApplied: true,
      restartOk: false,
      requiresProviderSetup: false,
      detail: 'import applied but restart failed',
    }))
    const { app } = await mountPanel(desktopApi({ migrationTakeLastResult }))

    expect(migrationTakeLastResult).toHaveBeenCalledTimes(1)
    app.unmount()
  })
})
