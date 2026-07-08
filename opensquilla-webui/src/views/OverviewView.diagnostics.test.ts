// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'

// Mounted coverage for the Overview diagnostics actions: the copy-JSON
// button, the conditional "diagnose with agent" hand-off, finding→settings
// deep links, and the active-provider latency readout (with null guards for
// backends that predate the latency field).

interface MountOptions {
  report?: Record<string, unknown> | null
  providers?: unknown
  failProviders?: boolean
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
  vi.restoreAllMocks()
})

// The buttons carry resolved translations in their title attributes; the
// suite pins locale 'en' in mountOverview, so select by the en strings.
const DIAGNOSE_SELECTOR = '[title="Diagnose with agent"]'
const COPY_JSON_SELECTOR = '[title="Copy diagnostics JSON"]'

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
})

describe('OverviewView copy diagnostics JSON', () => {
  it('copies the normalized report with gatewayUrl and copiedAt attached', async () => {
    const { el, copyText, pushToast, flush } = await mountOverview()
    const button = el.querySelector<HTMLButtonElement>(COPY_JSON_SELECTOR)
    expect(button).toBeTruthy()

    button!.click()
    await flush()

    expect(copyText).toHaveBeenCalledTimes(1)
    const text = copyText.mock.calls[0][0]
    expect(text).not.toContain('dummyuser')
    const parsed = JSON.parse(text) as Record<string, unknown>
    expect(parsed.gatewayUrl).toBe('ws://127.0.0.1:18791/ws')
    expect(parsed.configPath).toBe('~/dir/opensquilla.toml')
    expect(typeof parsed.copiedAt).toBe('string')
    expect(Number.isNaN(Date.parse(String(parsed.copiedAt)))).toBe(false)
    expect(pushToast).toHaveBeenCalledWith('Diagnostics JSON copied', { tone: 'ok' })
  })

  it('disables the button when the doctor report is unavailable', async () => {
    const { el, copyText, pushToast, flush } = await mountOverview({ report: null })
    const button = el.querySelector<HTMLButtonElement>(COPY_JSON_SELECTOR)
    expect(button).toBeTruthy()
    expect(button!.disabled).toBe(true)
    // The diagnose hand-off is hidden without a live report too.
    expect(el.querySelector(DIAGNOSE_SELECTOR)).toBeNull()

    // Even a forced click copies nothing and shows no success toast.
    button!.click()
    await flush()
    expect(copyText).not.toHaveBeenCalled()
    expect(pushToast).not.toHaveBeenCalled()
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
    expect(el.querySelector(COPY_JSON_SELECTOR)).toBeTruthy()
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
