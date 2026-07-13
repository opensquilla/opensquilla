// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const channelRows = [
  {
    name: 'ops-slack',
    type: 'slack',
    status: 'connected',
    connected: true,
    enabled: true,
    configured: true,
    connected_since: '2026-07-13T08:00:00Z',
    bot_user_id: 'U-BOT',
    capability_profile: {
      transports: ['webhook'],
      maturity: 'YELLOW-experimental',
      evidence: {
        reply: {
          declared: true,
          implemented: true,
          effective: true,
          evidence_kind: 'method',
          methods: ['build_reply_message'],
          proof_status: 'unverified',
        },
        group_chat: {
          declared: true,
          implemented: true,
          effective: true,
          evidence_kind: 'declaration',
          methods: [],
          proof_status: 'unverified',
        },
      },
    },
    diagnostics: {
      network_probe: 'not_run',
      delivery: {
        ingress: { accepted: { count: 1 } },
        outbox: { sent: { count: 2 } },
        leases: [],
      },
    },
  },
  {
    name: 'alerts-telegram',
    type: 'telegram',
    status: 'stopped',
    connected: false,
    enabled: true,
    configured: true,
    capability_profile: {
      transports: ['polling'],
      maturity: 'YELLOW-experimental',
      evidence: {},
    },
    diagnostics: { network_probe: 'not_run' },
  },
]

function buttonWithText(root: ParentNode, label: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find(candidate => candidate.textContent?.trim() === label)
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

function channelRow(root: ParentNode, name: string): HTMLTableRowElement {
  const row = Array.from(root.querySelectorAll<HTMLTableRowElement>('tbody tr'))
    .find(candidate => candidate.textContent?.includes(name))
  if (!row) throw new Error(`channel row not found: ${name}`)
  return row
}

async function mountChannelsView(options: {
  loadPairings?: (params?: Record<string, unknown>) => Promise<unknown>
} = {}) {
  vi.resetModules()

  const { createApp, defineComponent, h, nextTick, ref } = await import('vue')
  const i18n = (await import('@/i18n')).default
  i18n.global.locale.value = 'en'

  const push = vi.fn(async () => {})
  const pushToast = vi.fn()
  const confirm = vi.fn(async () => true)
  let pairings: Array<{
    pairingId: string
    pairingCode?: string
    channelName: string
    senderId: string
    senderName: string
    status: string
    createdAt?: string
    approvedAt?: string
  }> = [
    {
      pairingId: 'pair-pending',
      pairingCode: 'AB12CD34',
      channelName: 'ops-slack',
      senderId: 'U-PENDING',
      senderName: 'Pending User',
      status: 'pending',
      createdAt: '2026-07-13T08:30:00Z',
    },
    {
      pairingId: 'pair-approved',
      channelName: 'ops-slack',
      senderId: 'U-APPROVED',
      senderName: 'Approved User',
      status: 'approved',
      approvedAt: '2026-07-13T09:00:00Z',
    },
  ]
  const execute = vi.fn(async () => ({ channels: channelRows }))
  const refresh = vi.fn(async () => ({ channels: channelRows }))
  const rpcCall = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'channels.probe') {
      return { status: 'verified', connected: true, latencyMs: 17 }
    }
    if (method === 'channels.restart') {
      return { status: 'restarted', channel: params?.name }
    }
    if (method === 'channels.get') {
      return {
        entry: {
          name: 'ops-slack',
          type: 'slack',
          token: '***',
          signing_secret: '***',
          connection_mode: 'webhook',
        },
        secretFields: ['token', 'signing_secret'],
      }
    }
    if (method === 'channels.pairings') {
      if (options.loadPairings) return options.loadPairings(params)
      return { pairings: pairings.map(pairing => ({ ...pairing })) }
    }
    if (method === 'channels.pairing.approve') {
      pairings = pairings.map(pairing => pairing.pairingId === params?.pairingId
        ? { ...pairing, status: 'approved', approvedAt: '2026-07-13T10:00:00Z' }
        : pairing)
      return { status: 'approved' }
    }
    if (method === 'channels.pairing.revoke') {
      pairings = pairings.filter(pairing => pairing.pairingId !== params?.pairingId)
      return { status: 'revoked' }
    }
    throw new Error(`unexpected rpc method: ${method}`)
  })

  const iconStub = defineComponent({
    name: 'IconStub',
    setup() {
      return () => h('span', { 'data-testid': 'icon' })
    },
  })
  const emptyStub = (name: string) => defineComponent({
    name,
    setup() {
      return () => h('div', { 'data-testid': name })
    },
  })

  vi.doMock('vue-router', () => ({ useRouter: () => ({ push }) }))
  vi.doMock('@/stores/rpc', () => ({
    useRpcStore: () => ({
      call: rpcCall,
      on: vi.fn(() => () => {}),
    }),
  }))
  vi.doMock('@/composables/useRequest', () => ({
    useRequest: () => ({
      data: ref({ channels: channelRows }),
      loading: ref(false),
      error: ref(null),
      execute,
      refresh,
    }),
  }))
  vi.doMock('@/composables/useToasts', () => ({
    useToasts: () => ({ pushToast }),
  }))
  vi.doMock('@/composables/useConfirm', () => ({
    useConfirm: () => ({ confirm }),
  }))
  vi.doMock('@/components/Icon.vue', () => ({ default: iconStub }))
  vi.doMock('@/components/ErrorState.vue', () => ({ default: emptyStub('error-state') }))
  vi.doMock('@/components/LoadingSpinner.vue', () => ({ default: emptyStub('loading-spinner') }))

  const Component = (await import('./ChannelsView.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(Component)
  app.use(i18n)
  app.mount(el)
  await nextTick()

  const flush = async () => {
    await new Promise(resolve => setTimeout(resolve, 0))
    await nextTick()
  }

  return { app, el, flush, nextTick, rpcCall, refresh, confirm, pushToast }
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.doUnmock('vue-router')
  vi.doUnmock('@/stores/rpc')
  vi.doUnmock('@/composables/useRequest')
  vi.doUnmock('@/composables/useToasts')
  vi.doUnmock('@/composables/useConfirm')
  vi.doUnmock('@/components/Icon.vue')
  vi.doUnmock('@/components/ErrorState.vue')
  vi.doUnmock('@/components/LoadingSpinner.vue')
})

describe('ChannelsView channel operations', () => {
  it('filters rows and exercises detail RPC actions and evidence', async () => {
    const { app, el, flush, nextTick, rpcCall, refresh } = await mountChannelsView()

    try {
      expect(channelRow(el, 'ops-slack')).toBeTruthy()
      expect(channelRow(el, 'alerts-telegram')).toBeTruthy()

      const search = el.querySelector<HTMLInputElement>('input[type="search"]')!
      search.value = 'ops'
      search.dispatchEvent(new Event('input', { bubbles: true }))
      await nextTick()
      expect(channelRow(el, 'ops-slack')).toBeTruthy()
      expect(el.textContent).not.toContain('alerts-telegram')

      search.value = ''
      search.dispatchEvent(new Event('input', { bubbles: true }))
      const provider = el.querySelector<HTMLSelectElement>('.ch-select select')!
      provider.value = 'telegram'
      provider.dispatchEvent(new Event('change', { bubbles: true }))
      await nextTick()
      expect(channelRow(el, 'alerts-telegram')).toBeTruthy()
      expect(el.textContent).not.toContain('ops-slack')

      provider.value = 'all'
      provider.dispatchEvent(new Event('change', { bubbles: true }))
      await nextTick()
      channelRow(el, 'ops-slack').click()
      await nextTick()

      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      expect(detail).toBeTruthy()
      expect(detail.querySelector('h2')?.textContent).toBe('ops-slack')

      buttonWithText(detail, 'Test').click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.probe', { name: 'ops-slack' })
      expect(detail.textContent).toContain('Connection verified')

      buttonWithText(detail, 'Restart').click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.restart', { name: 'ops-slack' })
      expect(refresh).toHaveBeenCalled()

      buttonWithText(detail, 'Configuration').click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.get', { name: 'ops-slack' })
      const storedSecrets = detail.querySelectorAll<HTMLElement>('.ch-config-list dd.is-secret')
      expect(storedSecrets).toHaveLength(2)
      expect(Array.from(storedSecrets).every(field => field.textContent === 'Stored securely'))
        .toBe(true)

      buttonWithText(detail, 'Capabilities').click()
      await nextTick()
      const methodEvidence = Array.from(detail.querySelectorAll<HTMLElement>('.ch-capability'))
        .find(row => row.textContent?.includes('Reply'))
      expect(methodEvidence?.textContent).toContain('Backed by: build_reply_message')
      expect(methodEvidence?.textContent).toContain('Implemented')
    } finally {
      app.unmount()
    }
  })

  it('administers channel-local pairing access with confirmations and refreshes', async () => {
    const { app, el, flush, nextTick, rpcCall, confirm, pushToast } = await mountChannelsView()

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!

      buttonWithText(detail, 'Pairings').click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.pairings', { channelName: 'ops-slack' })
      expect(detail.textContent).toContain('Request AB12CD34')
      expect(detail.textContent).toContain('Pending User')
      expect(detail.textContent).toContain('Approved User')
      expect(detail.textContent).toContain('Pending requests')
      expect(detail.textContent).toContain('Approved access')

      detail.querySelector<HTMLButtonElement>('[aria-label="Approve access for Pending User"]')!.click()
      await flush()
      expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Approve pairing request?',
        primaryClass: 'btn--primary',
      }))
      expect(rpcCall).toHaveBeenCalledWith('channels.pairing.approve', {
        channelName: 'ops-slack',
        pairingId: 'pair-pending',
      })
      expect(rpcCall.mock.calls.filter(([method]) => method === 'channels.pairings')).toHaveLength(2)
      expect(pushToast).toHaveBeenCalledWith('Approved pairing access for Pending User', { tone: 'ok' })
      expect(detail.querySelector('[aria-label="Approve access for Pending User"]')).toBeNull()

      detail.querySelector<HTMLButtonElement>('[aria-label="Revoke access for Approved User"]')!.click()
      await flush()
      expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Revoke pairing access?',
      }))
      expect(rpcCall).toHaveBeenCalledWith('channels.pairing.revoke', {
        channelName: 'ops-slack',
        pairingId: 'pair-approved',
      })
      expect(rpcCall.mock.calls.filter(([method]) => method === 'channels.pairings')).toHaveLength(3)
      expect(pushToast).toHaveBeenCalledWith('Revoked pairing access for Approved User', { tone: 'ok' })
      expect(detail.querySelector('[aria-label="Revoke access for Approved User"]')).toBeNull()
    } finally {
      app.unmount()
    }
  })

  it('ignores stale pairing loads when switching channels', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    const firstLoad = new Promise(resolve => { resolveFirst = resolve })
    const loadPairings = vi.fn(async (params?: Record<string, unknown>) => {
      if (params?.channelName === 'ops-slack') return firstLoad
      return {
        pairings: [{
          pairingId: 'pair-telegram',
          pairingCode: 'TG12CD34',
          channelName: 'alerts-telegram',
          senderId: 'TG-USER',
          senderName: 'Telegram User',
          status: 'pending',
        }],
      }
    })
    const { app, el, flush, nextTick } = await mountChannelsView({ loadPairings })

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      buttonWithText(el.querySelector<HTMLElement>('.ch-detail')!, 'Pairings').click()
      await nextTick()

      channelRow(el, 'alerts-telegram').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Pairings').click()
      await flush()

      expect(loadPairings).toHaveBeenCalledTimes(2)
      expect(detail.textContent).toContain('Telegram User')

      resolveFirst?.({
        pairings: [{
          pairingId: 'pair-slack',
          channelName: 'ops-slack',
          senderId: 'SLACK-USER',
          senderName: 'Slack User',
          status: 'pending',
        }],
      })
      await flush()

      expect(detail.textContent).toContain('Telegram User')
      expect(detail.textContent).not.toContain('Slack User')
    } finally {
      app.unmount()
    }
  })
})
