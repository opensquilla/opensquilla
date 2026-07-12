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

const reportNeedingReplacement = {
  items: [
    {
      kind: 'preflight/target',
      status: 'error',
      reason: 'target home already contains session data',
    },
    { kind: 'state/sessions', status: 'planned', reason: '' },
  ],
  paused_jobs: [{ id: '1', name: 'daily-digest', cron_expr: '0 9 * * *' }],
  preflight: { disk_required_bytes: 1024, disk_free_bytes: 4096 },
  notes: ['source profile remains unchanged'],
}

const reportNeedingReplacementWithBlockingError = {
  ...reportNeedingReplacement,
  items: [
    ...reportNeedingReplacement.items,
    { kind: 'preflight/disk', status: 'error', reason: 'not enough free disk space' },
  ],
}

const emptyTargetReport = {
  ...reportNeedingReplacement,
  items: reportNeedingReplacement.items.slice(1),
}

const cliCandidate = {
  kind: 'cli-home',
  path: '/tmp/cli-home',
  version: '0.5.0rc3',
  session_count: 3,
  size_bytes: 2048,
  estimated_activity_at: '2026-07-10T10:00:00Z',
  previously_imported: true,
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

describe('DesktopRuntimePanel profile import', () => {
  it('hides the row when the desktop shell predates the migration bridge', async () => {
    const { app, el } = await mountPanel(desktopApi())
    expect(el.querySelector('[data-testid="runtime-migration-open"]')).toBeNull()
    app.unmount()
  })

  it('requires an explicit source choice even when exactly one profile is detected', async () => {
    const migrationRun = vi.fn(async () => ({ ok: true }))
    const migrationSummary = vi.fn(async (payload?: { source?: string }) => (
      payload?.source
        ? {
            ok: true,
            candidates: [cliCandidate],
            candidate: cliCandidate,
            report: emptyTargetReport,
            previewId: 'selected-preview',
          }
        : {
            ok: true,
            candidates: [cliCandidate],
            candidate: null,
            report: null,
            requiresSelection: true,
          }
    ))
    const { app, el } = await mountPanel(desktopApi({ migrationSummary, migrationRun }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    const chooser = el.querySelector('[data-testid="runtime-migration-summary"]')
    expect(chooser?.textContent).toContain('Nothing is selected automatically')
    expect(chooser?.textContent).toContain('/tmp/cli-home')
    expect(el.querySelector('[data-testid="runtime-migration-run"]')).toBeNull()
    expect(migrationSummary).toHaveBeenCalledTimes(1)

    ;(chooser?.querySelector('.migration-candidate') as HTMLButtonElement).click()
    await settle()

    expect(migrationSummary).toHaveBeenNthCalledWith(2, { source: '/tmp/cli-home' })
    expect(el.querySelector('[data-testid="runtime-migration-run"]')).toBeTruthy()
    expect(migrationRun).not.toHaveBeenCalled()
    app.unmount()
  })

  it('groups CLI and Desktop as supported and Portable as a historical source', async () => {
    const portableCandidate = {
      ...cliCandidate,
      kind: 'windows-portable',
      path: '/tmp/portable-home',
      previously_imported: false,
    }
    const desktopCandidate = {
      ...cliCandidate,
      kind: 'desktop-home',
      path: '/tmp/desktop-home',
      previously_imported: false,
    }
    const { app, el } = await mountPanel(desktopApi({
      migrationSummary: vi.fn(async () => ({
        ok: true,
        candidates: [cliCandidate, desktopCandidate, portableCandidate],
        candidate: null,
        report: null,
        requiresSelection: true,
      })),
      migrationRun: vi.fn(async () => ({ ok: true })),
    }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()

    const supported = el.querySelector('[data-testid="runtime-migration-supported"]')
    const historical = el.querySelector('[data-testid="runtime-migration-historical"]')
    expect(supported?.textContent).toContain('Supported OpenSquilla installations')
    expect(supported?.textContent).toContain('OpenSquilla CLI (supported)')
    expect(supported?.textContent).toContain('OpenSquilla Desktop (supported)')
    expect(historical?.textContent).toContain('Historical data sources')
    expect(historical?.textContent).toContain('Windows Portable (historical, discontinued)')
    expect(el.textContent).toContain('3 sessions')
    expect(el.textContent).toContain('Estimated recent activity')
    expect(el.textContent).toContain('Previously imported (still selectable)')
    expect(
      Array.from(el.querySelectorAll('.migration-candidate__head strong'))
        .some((label) => label.textContent === 'cli-home'),
    ).toBe(false)
    app.unmount()
  })

  it('can be skipped without running an import or hiding the usable runtime', async () => {
    const migrationRun = vi.fn(async () => ({ ok: true }))
    const { app, el } = await mountPanel(desktopApi({
      migrationSummary: vi.fn(async () => ({
        ok: true,
        candidates: [cliCandidate],
        candidate: null,
        report: null,
        requiresSelection: true,
      })),
      migrationRun,
    }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()
    const skip = el.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-cancel"]')
    expect(skip?.textContent).toContain('Not now')
    skip?.click()
    await settle()

    expect(el.querySelector('[data-testid="runtime-migration-summary"]')).toBeNull()
    expect(el.textContent).toContain('Desktop-owned process')
    expect(migrationRun).not.toHaveBeenCalled()
    app.unmount()
  })

  it('explains whole-profile replacement and gates it behind complete backup consent', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const progressUnsub = vi.fn()
    const progress: { cb: ((state: { phase: string; detail?: string }) => void) | null } = {
      cb: null,
    }
    const migrationRun = vi.fn(async () => ({
      ok: true,
      migrationApplied: true,
      restartOk: true,
      source: '/tmp/portable-home',
      sourceKind: 'windows-portable',
      targetReplaced: true,
    }))
    const candidate = {
      ...cliCandidate,
      kind: 'windows-portable',
      path: '/tmp/portable-home',
    }
    const migrationSummary = vi.fn(async (payload?: { source?: string }) => (
      payload?.source
        ? {
            ok: false,
            candidates: [candidate],
            candidate,
            report: reportNeedingReplacement,
            previewId: 'preview-replacement',
          }
        : {
            ok: true,
            candidates: [candidate],
            candidate: null,
            report: null,
            requiresSelection: true,
          }
    ))
    const { app, el } = await mountPanel(desktopApi({
      migrationSummary,
      migrationRun,
      onMigrationProgress: vi.fn((cb: (state: { phase: string; detail?: string }) => void) => {
        progress.cb = cb
        return progressUnsub
      }),
    }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()
    ;(el.querySelector('.migration-candidate') as HTMLButtonElement).click()
    await settle()

    const summary = el.querySelector('[data-testid="runtime-migration-summary"]')
    expect(summary?.querySelector('.migration-summary__kind')?.textContent).toContain(
      'Windows Portable (historical, discontinued)',
    )
    expect(summary?.textContent).toContain('Identity, personality, and memory')
    expect(summary?.textContent).toContain('Chats')
    expect(summary?.textContent).toContain('Settings and provider configuration')
    expect(summary?.textContent).toContain('Skills and media')
    expect(summary?.textContent).toContain('target home already contains session data')
    expect(summary?.textContent).toContain('replace it as a whole')
    expect(summary?.textContent).toContain('files are never merged')
    expect(summary?.querySelector('.migration-summary__errors')).toBeNull()

    ;(summary?.querySelector('[data-testid="runtime-migration-copy-path"]') as HTMLButtonElement)
      .click()
    await settle()
    expect(writeText).toHaveBeenCalledWith('/tmp/portable-home')

    const run = summary?.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-run"]')
    const checkbox = summary?.querySelector<HTMLInputElement>(
      '[data-testid="runtime-migration-overwrite"] input[type="checkbox"]',
    )
    expect(run?.disabled).toBe(true)
    checkbox!.checked = true
    checkbox!.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    expect(run?.disabled).toBe(false)

    progress.cb?.({ phase: 'applying', detail: 'copying state' })
    await settle()
    expect(summary?.textContent).toContain('applying — copying state')

    run?.click()
    await settle()
    expect(migrationRun).toHaveBeenCalledWith({
      overwrite: true,
      previewId: 'preview-replacement',
    })
    expect(progressUnsub).toHaveBeenCalled()
    app.unmount()
  })

  it('explains the independent copy before importing into an empty target', async () => {
    const migrationRun = vi.fn(async () => ({
      ok: true,
      migrationApplied: true,
      restartOk: true,
      source: cliCandidate.path,
      sourceKind: cliCandidate.kind,
      targetReplaced: false,
    }))
    const migrationSummary = vi.fn(async (payload?: { source?: string }) => (
      payload?.source
        ? {
            ok: true,
            candidates: [cliCandidate],
            candidate: cliCandidate,
            report: emptyTargetReport,
            previewId: 'preview-empty-target',
          }
        : {
            ok: true,
            candidates: [cliCandidate],
            candidate: null,
            report: null,
            requiresSelection: true,
          }
    ))
    const { app, el } = await mountPanel(desktopApi({ migrationSummary, migrationRun }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()
    ;(el.querySelector('.migration-candidate') as HTMLButtonElement).click()
    await settle()
    ;(el.querySelector('[data-testid="runtime-migration-run"]') as HTMLButtonElement).click()
    await settle()

    const { useConfirm } = await import('@/composables/useConfirm')
    const confirmation = useConfirm()
    const body = confirmation.confirmState.value?.body || ''
    expect(body).toContain('stops the local gateway')
    expect(body).toContain('one-time independent copy')
    expect(body).toContain('source profile stays unchanged')
    expect(body).toContain('will not sync')
    confirmation.resolveConfirm(true)
    await settle()
    expect(migrationRun).toHaveBeenCalledWith({
      overwrite: false,
      previewId: 'preview-empty-target',
    })
    app.unmount()
  })

  it('keeps the directory browser reachable when detection finds nothing', async () => {
    const migrationBrowseSource = vi.fn(async () => ({ ok: false, aborted: true }))
    const { app, el } = await mountPanel(desktopApi({
      migrationSummary: vi.fn(async () => ({
        ok: true,
        candidates: [],
        candidate: null,
        report: null,
        requiresSelection: true,
      })),
      migrationBrowseSource,
      migrationRun: vi.fn(async () => ({ ok: true })),
    }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()
    const browse = el.querySelector<HTMLButtonElement>(
      '[data-testid="runtime-migration-browse-cli-home"]',
    )
    expect(browse).toBeTruthy()
    browse?.click()
    await settle()
    expect(migrationBrowseSource).toHaveBeenCalledWith({ kind: 'cli-home' })
    app.unmount()
  })

  it('keeps replacement disabled when a separate blocking error remains', async () => {
    const migrationSummary = vi.fn(async (payload?: { source?: string }) => (
      payload?.source
        ? {
            ok: false,
            candidates: [cliCandidate],
            candidate: cliCandidate,
            report: reportNeedingReplacementWithBlockingError,
            previewId: 'preview-blocked',
          }
        : {
            ok: true,
            candidates: [cliCandidate],
            candidate: null,
            report: null,
            requiresSelection: true,
          }
    ))
    const { app, el } = await mountPanel(desktopApi({
      migrationSummary,
      migrationRun: vi.fn(async () => ({ ok: true })),
    }))

    ;(el.querySelector('[data-testid="runtime-migration-open"]') as HTMLButtonElement).click()
    await settle()
    ;(el.querySelector('.migration-candidate') as HTMLButtonElement).click()
    await settle()

    const summary = el.querySelector('[data-testid="runtime-migration-summary"]')
    expect(summary?.textContent).toContain('not enough free disk space')
    const run = summary?.querySelector<HTMLButtonElement>('[data-testid="runtime-migration-run"]')
    const checkbox = summary?.querySelector<HTMLInputElement>(
      '[data-testid="runtime-migration-overwrite"] input[type="checkbox"]',
    )
    checkbox!.checked = true
    checkbox!.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    expect(run?.disabled).toBe(true)
    app.unmount()
  })

  it('shows a durable completion card and leaves the source path visible', async () => {
    const migrationPeekLastResult = vi.fn(async () => ({
      ok: true,
      migrationApplied: true,
      restartOk: true,
      source: '/tmp/cli-profile',
      sourceKind: 'cli-home',
      targetReplaced: true,
    }))
    const migrationDismissLastResult = vi.fn(async () => ({ ok: true }))
    const revealRecoveryPath = vi.fn(async () => true)
    const { app, el } = await mountPanel(desktopApi({
      migrationPeekLastResult,
      migrationDismissLastResult,
      revealRecoveryPath,
    }))

    const card = el.querySelector('[data-testid="runtime-migration-complete"]')
    expect(card?.textContent).toContain('Import complete')
    expect(card?.textContent).toContain('/tmp/cli-profile')
    expect(card?.textContent).toContain('source profile stays unchanged')
    expect(card?.textContent).toContain('complete backup')
    expect(card?.textContent).toContain('never merged')
    expect(card?.textContent).toContain('will not sync')

    const buttons = card?.querySelectorAll<HTMLButtonElement>('button')
    buttons?.[0]?.click()
    await settle()
    expect(revealRecoveryPath).toHaveBeenCalledWith({ target: 'backups' })
    buttons?.[1]?.click()
    await settle()
    expect(migrationDismissLastResult).toHaveBeenCalledTimes(1)
    expect(el.querySelector('[data-testid="runtime-migration-complete"]')).toBeNull()
    app.unmount()
  })
})
