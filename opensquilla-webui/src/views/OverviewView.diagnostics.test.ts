// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'

// Mounted coverage for the Overview diagnostics actions: the conditional
// "diagnose with agent" hand-off, finding→settings deep links, and the
// active-provider latency readout (with null guards for older gateways).

interface MountOptions {
  report?: Record<string, unknown> | null
  providers?: unknown
  failProviders?: boolean
  desktop?: boolean
  connectionUrl?: string
}

interface PushArg {
  path: string
  query?: Record<string, string>
  hash?: string
  state?: { prefill?: string; autosend?: boolean }
}

const mountedApps: Array<{ app: App; el: HTMLElement }> = []

function baseReport(): Record<string, unknown> {
  return {
    status: 'degraded',
    ready: true,
    summary: 'Config at /Users/dummyuser/dir/opensquilla.toml',
    gatewayUrl: 'ws://127.0.0.1:18791/ws',
    configPath: '/Users/dummyuser/dir/opensquilla.toml',
    agentId: 'main',
    counts: { warn: 1 },
    impactCounts: { degrades: 1 },
    findings: [
      {
        id: 'memory.degraded',
        surface: 'memory',
        severity: 'warn',
        readinessImpact: 'degrades',
        title: 'Memory index <stale> & behind',
        detail: 'Index at /Users/dummyuser/state/memory',
      },
    ],
  }
}

async function mountOverview(options: MountOptions = {}) {
  vi.resetModules()
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = options.desktop
    ? {}
    : undefined
  window.localStorage.clear()
  if (options.connectionUrl) {
    window.localStorage.setItem('opensquilla.wsUrl', options.connectionUrl)
  }

  const { createApp, defineComponent, h, nextTick } = await import('vue')
  const { createPinia, setActivePinia } = await import('pinia')
  const i18n = (await import('@/i18n')).default

  const push = vi.fn((_to: PushArg) => Promise.resolve())
  const pushToast = vi.fn()
  const copyText = vi.fn(async (_text: string) => {})
  const rpcCall = vi.fn(async (method: string) => {
    if (method === 'doctor.status') {
      if (options.report === null) throw new Error('doctor unavailable')
      return JSON.parse(JSON.stringify(options.report ?? baseReport()))
    }
    if (method === 'providers.status') {
      if (options.failProviders) throw new Error('providers unavailable')
      return options.providers ?? { providers: [] }
    }
    throw new Error(`unexpected rpc method: ${method}`)
  })

  vi.doMock('vue-router', () => ({ useRouter: () => ({ push }) }))
  vi.doMock('@/stores/rpc', () => ({
    useRpcStore: () => ({
      isConnected: true,
      isConnecting: false,
      on: vi.fn(() => () => {}),
      waitForConnection: vi.fn(async () => {}),
      call: rpcCall,
    }),
  }))
  vi.doMock('@/composables/useRequest', async () => {
    const { ref } = await import('vue')
    return {
      useRequest: () => ({
        data: ref(null),
        error: ref(null),
        loading: ref(false),
        execute: vi.fn(async () => null),
        refresh: vi.fn(async () => null),
      }),
    }
  })
  vi.doMock('@/composables/useToasts', () => ({ useToasts: () => ({ pushToast }) }))
  vi.doMock('@/utils/browser', () => ({ copyTextWithFallback: copyText }))
  vi.doMock('@/components/Icon.vue', () => ({
    default: defineComponent({
      name: 'IconStub',
      props: { name: { type: String, default: '' } },
      setup(props) {
        return () => h('span', { 'data-icon': props.name })
      },
    }),
  }))
  vi.doMock('@/components/ErrorState.vue', () => ({
    default: defineComponent({
      name: 'ErrorStateStub',
      setup() {
        return () => h('div', { 'data-testid': 'error-state' })
      },
    }),
  }))

  const pinia = createPinia()
  setActivePinia(pinia)
  i18n.global.locale.value = 'en'

  const Component = (await import('./OverviewView.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(Component)
  app.component('RouterLink', defineComponent({
    name: 'RouterLinkStub',
    setup(_, { slots }) {
      return () => h('a', slots.default?.())
    },
  }))
  app.use(pinia)
  app.use(i18n)
  app.mount(el)
  mountedApps.push({ app, el })

  async function flush() {
    for (let i = 0; i < 8; i++) await Promise.resolve()
    await nextTick()
  }
  await flush()

  return { el, push, pushToast, copyText, rpcCall, flush }
}

beforeEach(() => {
  document.body.innerHTML = ''
  window.localStorage.clear()
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = undefined
})

afterEach(() => {
  while (mountedApps.length) {
    const { app, el } = mountedApps.pop()!
    app.unmount()
    el.remove()
  }
  vi.doUnmock('vue-router')
  vi.doUnmock('@/stores/rpc')
  vi.doUnmock('@/composables/useRequest')
  vi.doUnmock('@/composables/useToasts')
  vi.doUnmock('@/utils/browser')
  vi.doUnmock('@/components/Icon.vue')
  vi.doUnmock('@/components/ErrorState.vue')
  window.localStorage.clear()
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = undefined
  vi.restoreAllMocks()
})

// The buttons carry resolved translations in their title attributes; the
// suite pins locale 'en' in mountOverview, so select by the en strings.
const DIAGNOSE_SELECTOR = '[title="Diagnose with agent"]'

describe('OverviewView diagnose-with-agent hand-off', () => {
  it('shows the button and routes a sanitized, escaped report into a new chat', async () => {
    const { el, push, flush } = await mountOverview()
    const button = el.querySelector<HTMLButtonElement>(DIAGNOSE_SELECTOR)
    expect(button).toBeTruthy()

    button!.click()
    await flush()

    expect(push).toHaveBeenCalledTimes(1)
    const arg = push.mock.calls[0][0]
    expect(arg.path).toBe('/chat/new')
    expect(arg.query).toEqual({ agent: 'main' })
    expect(arg.state?.autosend).toBe(true)

    const prefill = String(arg.state?.prefill)
    expect(prefill).toContain('Please troubleshoot this OpenSquilla configuration')
    expect(prefill).toContain('<context source="client:diagnostic-context">')
    expect(prefill).toContain('"platform":"web"')
    expect(prefill).toContain('"hasTerminalWorkflow":true')
    expect(prefill).toContain('<untrusted source="doctor:report">')
    expect(prefill).toContain('</untrusted>')
    // Home paths are normalized and the report body is XML-escaped.
    expect(prefill).toContain('~/dir/opensquilla.toml')
    expect(prefill).not.toContain('dummyuser')
    expect(prefill).toContain('Memory index &lt;stale&gt; &amp; behind')
    // Only the minimal report ships — no env fields like configPath.
    expect(prefill).not.toContain('"configPath"')
  })

  it('hides the button when a provider finding blocks the agent', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'provider.key.missing',
        surface: 'provider',
        severity: 'error',
        readinessImpact: 'blocks_ready',
        title: 'Provider API key missing',
      },
    ]
    const { el } = await mountOverview({ report })
    expect(el.querySelector(DIAGNOSE_SELECTOR)).toBeNull()
  })

  it('removes commands from a local Desktop hand-off and supplies in-app remediations', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        severity: 'info',
        readinessImpact: 'optional',
        title: 'Legacy data found',
        fixSteps: [
          {
            label: 'Preview the import',
            command: 'opensquilla migrate opensquilla --source /Users/dummyuser/.opensquilla',
          },
        ],
      },
    ]
    const { el, push, flush } = await mountOverview({ report, desktop: true })

    el.querySelector<HTMLButtonElement>(DIAGNOSE_SELECTOR)!.click()
    await flush()

    const prefill = String(push.mock.calls[0][0].state?.prefill)
    expect(prefill).toContain('"platform":"desktop"')
    expect(prefill).toContain('"hasTerminalWorkflow":false')
    expect(prefill).toContain('"ownsGateway":true')
    expect(prefill).toContain('"connectionScope":"local_owned"')
    expect(prefill).toContain('"route":"/settings/runtime"')
    expect(prefill).toContain('"advancedCliAvailable":true')
    expect(prefill).not.toContain('"command":"opensquilla migrate')
    expect(prefill).not.toContain('dummyuser')
  })

  it('marks a remote Desktop gateway and omits the local Runtime remediation', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        severity: 'info',
        readinessImpact: 'optional',
        title: 'Legacy data found',
      },
    ]
    const { el, push, flush } = await mountOverview({
      report,
      desktop: true,
      connectionUrl: 'ws://remote.example:18791/ws',
    })

    expect(el.querySelector('.health-settings-link')).toBeNull()
    el.querySelector<HTMLButtonElement>(DIAGNOSE_SELECTOR)!.click()
    await flush()

    const prefill = String(push.mock.calls[0][0].state?.prefill)
    expect(prefill).toContain('"ownsGateway":false')
    expect(prefill).toContain('"connectionScope":"remote"')
    expect(prefill).toContain('"remoteGatewayActions":"handle_on_gateway_host"')
    expect(prefill).not.toContain('/settings/runtime')
  })

  it('keeps commands in a Web hand-off with a terminal workflow', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        fixSteps: [{ label: 'Preview', command: 'opensquilla migrate opensquilla --source /tmp/old' }],
      },
    ]
    const { el, push, flush } = await mountOverview({ report })

    el.querySelector<HTMLButtonElement>(DIAGNOSE_SELECTOR)!.click()
    await flush()

    expect(String(push.mock.calls[0][0].state?.prefill))
      .toContain('"command":"opensquilla migrate opensquilla --source /tmp/old"')
  })
})

describe('OverviewView recovery activation copy', () => {
  it('keeps restart guidance on the concrete step without a finding-level restart claim', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'provider.active.not_configured',
        surface: 'provider',
        severity: 'error',
        readinessImpact: 'blocks_ready',
        title: 'Active provider is not configured',
        restartRequired: true,
        fixSteps: [
          {
            label: 'Set provider environment variable',
            detail: 'Set TOKENRHYTHM_API_KEY, then restart OpenSquilla.',
          },
          {
            label: 'Restart gateway',
            command: 'opensquilla gateway restart',
          },
        ],
      },
    ]

    const { el } = await mountOverview({ report })

    expect(el.textContent).not.toContain('Recovery requires restart')
    expect(el.textContent).toContain('then restart OpenSquilla')
    expect(el.textContent).toContain('Restart gateway')
  })

  it('keeps only the migration preview when the current target already has data', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        severity: 'info',
        readinessImpact: 'optional',
        title: 'Legacy data found',
        evidence: { target_fresh: false },
        restartRequired: true,
        fixSteps: [
          {
            label: 'Preview the import',
            command: 'opensquilla migrate opensquilla --source /tmp/old',
          },
          {
            label: 'Apply the import',
            command: 'opensquilla migrate opensquilla --source /tmp/old --apply',
          },
        ],
      },
    ]

    const { el } = await mountOverview({ report })

    expect(el.textContent).toContain('Preview the import')
    expect(el.textContent).not.toContain('Apply the import')
    expect(el.textContent).not.toContain('--apply')
  })

  it('keeps the migration apply step for a fresh target', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        severity: 'warn',
        readinessImpact: 'degrades',
        title: 'Legacy data found',
        evidence: { targetFresh: true },
        fixSteps: [
          {
            label: 'Preview the import',
            command: 'opensquilla migrate opensquilla --source /tmp/old',
          },
          {
            label: 'Apply the import',
            command: 'opensquilla migrate opensquilla --source /tmp/old --apply',
          },
        ],
      },
    ]

    const { el } = await mountOverview({ report })

    expect(el.textContent).toContain('Apply the import')
    expect(el.textContent).toContain('--apply')
  })
})

describe('OverviewView finding settings links', () => {
  it('links mapped surfaces to their settings section and skips the rest', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'provider.model.unknown',
        surface: 'provider',
        severity: 'warn',
        readinessImpact: 'degrades',
        title: 'Model not in catalog',
        evidence: { providerId: 'openrouter' },
      },
      {
        id: 'memory.degraded',
        surface: 'memory',
        severity: 'warn',
        readinessImpact: 'degrades',
        title: 'Memory degraded',
      },
    ]
    const { el, push, flush } = await mountOverview({ report })

    const links = el.querySelectorAll<HTMLButtonElement>('.health-settings-link')
    expect(links.length).toBe(1)

    links[0].click()
    await flush()
    expect(push).toHaveBeenCalledWith({ path: '/settings/provider', hash: '#provider-openrouter' })
  })

  it('links local Desktop migration to Runtime and capability findings to Capabilities', async () => {
    const report = baseReport()
    report.findings = [
      {
        id: 'migration.legacy_home_detected',
        surface: 'migration',
        severity: 'info',
        readinessImpact: 'optional',
        title: 'Legacy data found',
      },
      {
        id: 'image_generation.credentials.missing',
        surface: 'image_generation',
        severity: 'info',
        readinessImpact: 'optional',
        title: 'Image generation key missing',
      },
    ]
    const { el, push, flush } = await mountOverview({ report, desktop: true })

    const links = el.querySelectorAll<HTMLButtonElement>('.health-settings-link')
    expect(links.length).toBe(2)
    links[0].click()
    await flush()
    expect(push).toHaveBeenCalledWith({ path: '/settings/runtime' })
    links[1].click()
    await flush()
    expect(push).toHaveBeenCalledWith({ path: '/settings/capabilities' })
  })
})

describe('OverviewView provider latency line', () => {
  const latencyProviders = {
    providers: [
      {
        providerId: 'anthropic',
        active: false,
        latency: { p50TtftMs: 100, p95TtftMs: 200, samples: 5, windowMinutes: 60 },
      },
      {
        providerId: 'openrouter',
        active: true,
        latency: { p50TtftMs: 380, p95TtftMs: 1200, samples: 87, windowMinutes: 60 },
      },
    ],
  }

  it('renders the compact line for the active provider only', async () => {
    const { el } = await mountOverview({ providers: latencyProviders })
    const line = el.querySelector('.ov-readout__latency code')
    expect(line?.textContent).toBe('p50 380ms · p95 1.2s · 87 samples/60min')
  })

  it('skips the line when the active row has no latency payload', async () => {
    const { el } = await mountOverview({
      providers: { providers: [{ providerId: 'openrouter', active: true, latency: null }] },
    })
    expect(el.querySelector('.ov-readout__latency')).toBeNull()
  })

  it('tolerates a providers.status failure without breaking the view', async () => {
    const { el } = await mountOverview({ failProviders: true })
    expect(el.querySelector('.ov-readout__latency')).toBeNull()
    // The rest of the overview still rendered.
    expect(el.querySelector('.ov-statusline')).toBeTruthy()
    expect(el.querySelector(DIAGNOSE_SELECTOR)).toBeTruthy()
  })

  it('fetches providers.status on mount only, not on health reruns', async () => {
    const { el, rpcCall, flush } = await mountOverview({ providers: latencyProviders })
    const providerCalls = () =>
      rpcCall.mock.calls.filter(([method]) => method === 'providers.status').length
    expect(providerCalls()).toBe(1)

    // "Rerun checks" repeats the deep doctor pass but must not re-instantiate
    // a provider client per registered spec just for the latency line.
    el.querySelector<HTMLButtonElement>('.ov-rerun')!.click()
    await flush()
    expect(rpcCall.mock.calls.filter(([method]) => method === 'doctor.status').length).toBe(2)
    expect(providerCalls()).toBe(1)
  })
})

describe('OverviewView config path readout', () => {
  it('abbreviates Linux home config paths too', async () => {
    const report = baseReport()
    report.configPath = '/home/dummyuser/dir/opensquilla.toml'
    const { el } = await mountOverview({ report })
    const codes = Array.from(el.querySelectorAll('.ov-readout__kv code'))
      .map(code => code.textContent)
    expect(codes).toContain('~/dir/opensquilla.toml')
  })
})
