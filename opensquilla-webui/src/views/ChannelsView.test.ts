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
  adminSenders?: Record<string, string[]>
  /** When set, onboarding.channel.probe rejects with this message. */
  draftProbeError?: { message: string }
} = {}) {
  vi.resetModules()

  const { KeepAlive, createApp, defineComponent, h, nextTick, ref } = await import('vue')
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
    {
      pairingId: 'pair-revoked',
      channelName: 'ops-slack',
      senderId: 'U-REVOKED',
      senderName: 'Revoked User',
      status: 'revoked',
    },
  ]
  const adminSendersMap: Record<string, string[]> = { ...(options.adminSenders || {}) }
  const execute = vi.fn(async () => ({ channels: channelRows }))
  const refresh = vi.fn(async () => ({ channels: channelRows }))
  // Catalog slice mirroring the backend field-spec shape (groups, secrets,
  // show_when, advanced) for the in-place configuration editor.
  const slackSpec = {
    type: 'slack',
    label: 'Slack',
    setupAids: [],
    fields: [
      { name: 'name', label: 'Channel name', type: 'text', required: true },
      { name: 'connection_mode', label: 'Connection mode', type: 'select', default: 'socket', choices: ['socket', 'webhook'] },
      { name: 'slack_channel_id', label: 'Default channel id', type: 'text', default: '' },
      { name: 'token', label: 'Bot token', type: 'password', required: true, secret: true, group: 'credentials' },
      { name: 'signing_secret', label: 'Signing secret', type: 'password', required: true, secret: true, group: 'credentials', showWhen: { connection_mode: 'webhook' } },
      { name: 'reply_in_thread', label: 'Reply in thread', type: 'bool', default: false, advanced: true },
    ],
  }
  const rpcCall = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'onboarding.catalog') {
      return { channels: [slackSpec] }
    }
    if (method === 'onboarding.channel.probe') {
      if (options.draftProbeError) throw new Error(options.draftProbeError.message)
      return { status: 'validated', connected: false, restartRequired: true, warnings: [] }
    }
    if (method === 'onboarding.channel.upsert') {
      const entry = params?.entry as Record<string, unknown> | undefined
      return { changed: true, restartRequired: true, entry: { name: entry?.name } }
    }
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
    if (method === 'config.get') {
      // Members panel reads only the channel_admin_senders map (bounded path
      // read), so mirror the registry's dot-path navigation.
      if (params?.path === 'channel_admin_senders') return { ...adminSendersMap }
      return {}
    }
    if (method === 'channels.pairings') {
      if (options.loadPairings) return options.loadPairings(params)
      return { pairings: pairings.map(pairing => ({ ...pairing })) }
    }
    if (method === 'channels.pairing.approve') {
      pairings = pairings.map(pairing => pairing.pairingId === params?.pairingId
        ? { ...pairing, status: 'approved', approvedAt: '2026-07-13T10:00:00Z' }
        : pairing)
      if (params?.asAdmin) {
        const target = pairings.find(pairing => pairing.pairingId === params?.pairingId)
        if (target) {
          const set = new Set(adminSendersMap['ops-slack'] || [])
          set.add(target.senderId)
          adminSendersMap['ops-slack'] = [...set]
        }
      }
      return { status: 'approved', adminGranted: Boolean(params?.asAdmin) }
    }
    if (method === 'channels.pairing.revoke') {
      pairings = pairings.filter(pairing => pairing.pairingId !== params?.pairingId)
      return { status: 'revoked' }
    }
    if (method === 'channels.admin.set') {
      const channel = String(params?.channelName)
      const senderId = String(params?.senderId)
      const admin = Boolean(params?.admin)
      const set = new Set(adminSendersMap[channel] || [])
      if (admin) set.add(senderId)
      else set.delete(senderId)
      if (set.size) adminSendersMap[channel] = [...set]
      else delete adminSendersMap[channel]
      return { channelName: channel, senderId, admin: set.has(senderId), admins: adminSendersMap[channel] || [] }
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

  const replace = vi.fn(async (_to: { query?: Record<string, unknown> }) => {})
  vi.doMock('vue-router', () => ({
    useRouter: () => ({ push, replace }),
    useRoute: () => ({ path: '/channels', query: {}, hash: '' }),
    onBeforeRouteLeave: vi.fn(),
  }))
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
  // KeepAlive matches the production mount (MonitorHubView) and makes
  // onActivated run — the document Esc listener and catalog refresh live there.
  const app = createApp(defineComponent({
    setup() {
      return () => h(KeepAlive, null, [h(Component)])
    },
  }))
  app.use(i18n)
  app.mount(el)
  await nextTick()

  const flush = async () => {
    await new Promise(resolve => setTimeout(resolve, 0))
    await nextTick()
  }

  return { app, el, flush, nextTick, rpcCall, refresh, confirm, pushToast, push, replace }
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
      expect(rpcCall.mock.calls.some(([method]) => method === 'onboarding.catalog')).toBe(true)
      const storedSecrets = detail.querySelectorAll<HTMLElement>('.cfge__value--secret')
      expect(storedSecrets).toHaveLength(2)
      expect(Array.from(storedSecrets).every(field => field.textContent?.trim() === 'Stored ······'))
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

      buttonWithText(detail, 'Members').click()
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

      // A revoked request can be re-approved via the same approve RPC.
      expect(detail.textContent).toContain('Revoked access')
      detail.querySelector<HTMLButtonElement>('[aria-label="Re-approve access for Revoked User"]')!.click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.pairing.approve', {
        channelName: 'ops-slack',
        pairingId: 'pair-revoked',
      })
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
      buttonWithText(el.querySelector<HTMLElement>('.ch-detail')!, 'Members').click()
      await nextTick()

      channelRow(el, 'alerts-telegram').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Members').click()
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

  it('promotes an approved member to channel admin', async () => {
    const { app, el, flush, nextTick, rpcCall, confirm } = await mountChannelsView()

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Members').click()
      await flush()

      detail.querySelector<HTMLButtonElement>('[aria-label="Make Approved User a channel admin"]')!.click()
      await flush()
      expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Make this member an admin?',
      }))
      expect(rpcCall).toHaveBeenCalledWith('channels.admin.set', {
        channelName: 'ops-slack',
        senderId: 'U-APPROVED',
        admin: true,
      })
      // After the grant + reload the row flips to the admin controls.
      expect(detail.querySelector('[aria-label="Remove admin from Approved User"]')).toBeTruthy()
      expect(detail.querySelector('[aria-label="Make Approved User a channel admin"]')).toBeNull()
    } finally {
      app.unmount()
    }
  })

  it('shows the Admin pill and demotes a channel admin', async () => {
    const { app, el, flush, nextTick, rpcCall, confirm } = await mountChannelsView({
      adminSenders: { 'ops-slack': ['U-APPROVED'] },
    })

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Members').click()
      await flush()

      // The approved admin renders the Admin pill instead of the plain badge.
      const adminPill = Array.from(detail.querySelectorAll<HTMLElement>('.ch-pairing-status.is-admin'))
        .find(node => node.textContent?.trim() === 'Admin')
      expect(adminPill).toBeTruthy()

      detail.querySelector<HTMLButtonElement>('[aria-label="Remove admin from Approved User"]')!.click()
      await flush()
      expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Remove admin access?',
      }))
      expect(rpcCall).toHaveBeenCalledWith('channels.admin.set', {
        channelName: 'ops-slack',
        senderId: 'U-APPROVED',
        admin: false,
      })
      // Back to member controls after the demotion + reload.
      expect(detail.querySelector('[aria-label="Make Approved User a channel admin"]')).toBeTruthy()
    } finally {
      app.unmount()
    }
  })

  it('approves a pending member as admin when the checkbox is ticked', async () => {
    const { app, el, flush, nextTick, rpcCall } = await mountChannelsView()

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Members').click()
      await flush()

      const checkbox = detail.querySelector<HTMLInputElement>(
        '[aria-label="Approve Pending User as a channel admin"]')!
      // There is already an approved member, so the bootstrap default is off.
      expect(checkbox.checked).toBe(false)
      checkbox.checked = true
      checkbox.dispatchEvent(new Event('change', { bubbles: true }))
      await nextTick()

      detail.querySelector<HTMLButtonElement>('[aria-label="Approve access for Pending User"]')!.click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.pairing.approve', {
        channelName: 'ops-slack',
        pairingId: 'pair-pending',
        asAdmin: true,
      })
    } finally {
      app.unmount()
    }
  })

  it('defaults the first pending row to admin when the channel has no members yet', async () => {
    const loadPairings = vi.fn(async () => ({
      pairings: [{
        pairingId: 'pair-first',
        channelName: 'ops-slack',
        senderId: 'U-FIRST',
        senderName: 'First User',
        status: 'pending',
      }],
    }))
    const { app, el, flush, nextTick, rpcCall } = await mountChannelsView({ loadPairings })

    try {
      channelRow(el, 'ops-slack').click()
      await nextTick()
      const detail = el.querySelector<HTMLElement>('.ch-detail')!
      buttonWithText(detail, 'Members').click()
      await flush()

      const checkbox = detail.querySelector<HTMLInputElement>(
        '[aria-label="Approve First User as a channel admin"]')!
      expect(checkbox.checked).toBe(true)

      detail.querySelector<HTMLButtonElement>('[aria-label="Approve access for First User"]')!.click()
      await flush()
      expect(rpcCall).toHaveBeenCalledWith('channels.pairing.approve', {
        channelName: 'ops-slack',
        pairingId: 'pair-first',
        asAdmin: true,
      })
    } finally {
      app.unmount()
    }
  })
})

describe('ChannelsView in-place configuration editor', () => {
  type Ctx = Awaited<ReturnType<typeof mountChannelsView>>

  async function openConfiguration(ctx: Ctx): Promise<HTMLElement> {
    const { el, flush, nextTick } = ctx
    channelRow(el, 'ops-slack').click()
    await nextTick()
    const detail = el.querySelector<HTMLElement>('.ch-detail')!
    buttonWithText(detail, 'Configuration').click()
    await flush()
    return detail
  }

  async function enterEditMode(ctx: Ctx, detail: HTMLElement): Promise<void> {
    buttonWithText(detail, 'Edit').click()
    await ctx.flush()
  }

  function fieldNames(detail: HTMLElement): string[] {
    return Array.from(detail.querySelectorAll<HTMLElement>('.cfge [data-field]'))
      .map(node => node.getAttribute('data-field') || '')
  }

  function setField(detail: HTMLElement, name: string, value: string): void {
    const input = detail.querySelector<HTMLInputElement>(`[data-field="${name}"] input`)!
    input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }

  function bar(el: HTMLElement): HTMLElement {
    const node = el.querySelector<HTMLElement>('.ceb')
    if (!node) throw new Error('editor action bar not found')
    return node
  }

  it('flips read → edit onto the same field skeleton, name locked', async () => {
    const ctx = await mountChannelsView()
    try {
      const detail = await openConfiguration(ctx)
      const readFields = fieldNames(detail)
      // Spec-driven read rows: same set the edit form will own, secrets masked.
      expect(readFields).toEqual(
        ['name', 'connection_mode', 'slack_channel_id', 'token', 'signing_secret', 'reply_in_thread'])
      expect(detail.querySelectorAll('.cfge input')).toHaveLength(0)

      await enterEditMode(ctx, detail)
      expect(fieldNames(detail)).toEqual(readFields)
      // Rows became live fields in place; the name stays locked text.
      expect(detail.querySelector('[data-field="slack_channel_id"] input')).toBeTruthy()
      expect(detail.querySelector('[data-field="name"] input')).toBeNull()
      expect(detail.querySelector('[data-field="name"] .cfge__value--locked')).toBeTruthy()
    } finally {
      ctx.app.unmount()
    }
  })

  it('owns the edit=1 query contract: enter, two-stage Esc exit, never carries across channels', async () => {
    const ctx = await mountChannelsView()
    const { el, flush, replace } = ctx
    const lastQuery = () => {
      const calls = replace.mock.calls
      return calls[calls.length - 1]?.[0]?.query
    }
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)
      expect(lastQuery()).toMatchObject({
        channel: 'ops-slack', tab: 'configuration', edit: '1',
      })

      // First Esc only blurs the autofocused field — still editing.
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flush()
      expect(detail.querySelector('[data-field="slack_channel_id"] input')).toBeTruthy()

      // Second Esc cancels back to read mode and drops edit=1.
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flush()
      expect(detail.querySelector('[data-field="slack_channel_id"] input')).toBeNull()
      const afterExit = lastQuery()
      expect(afterExit).toMatchObject({ channel: 'ops-slack', tab: 'configuration' })
      expect(afterExit?.edit).toBeUndefined()

      // Re-enter edit, then switch channels (clean draft): the new channel's
      // query must never inherit edit=1.
      await enterEditMode(ctx, detail)
      channelRow(el, 'alerts-telegram').click()
      await flush()
      const telegramWrites = replace.mock.calls
        .map(call => call[0]?.query)
        .filter(query => query?.channel === 'alerts-telegram')
      expect(telegramWrites.length).toBeGreaterThan(0)
      expect(telegramWrites.every(query => query?.edit === undefined)).toBe(true)
    } finally {
      ctx.app.unmount()
    }
  })

  it('names the changed fields in the dirty bar and probes the current draft', async () => {
    const ctx = await mountChannelsView()
    const { el, flush, rpcCall } = ctx
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)
      expect(el.querySelector('.ceb')).toBeNull()

      setField(detail, 'slack_channel_id', 'C123')
      await flush()
      expect(bar(el).textContent).toContain('Unsaved — Default channel id')
      expect(detail.querySelector('.ch-tab-dirty')).toBeTruthy()

      buttonWithText(bar(el), 'Test connection').click()
      await flush()
      const probeCall = rpcCall.mock.calls.find(([method]) => method === 'onboarding.channel.probe')
      expect(probeCall).toBeTruthy()
      const entry = (probeCall![1] as { entry: Record<string, unknown> }).entry
      expect(entry).toMatchObject({
        type: 'slack', name: 'ops-slack', connection_mode: 'webhook', slack_channel_id: 'C123',
      })
      // Untouched stored secrets stay out of the draft probe entirely.
      expect('token' in entry).toBe(false)
      expect(JSON.stringify(entry)).not.toContain('***')
      expect(detail.textContent).toContain('Configuration checks passed')
    } finally {
      ctx.app.unmount()
    }
  })

  it('saves via probe → upsert, resets the baseline, and drops edit mode', async () => {
    const ctx = await mountChannelsView()
    const { el, flush, rpcCall, pushToast } = ctx
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)
      setField(detail, 'slack_channel_id', 'C123')
      await flush()

      buttonWithText(bar(el), 'Save changes').click()
      await flush()
      await flush()

      const methods = rpcCall.mock.calls.map(([method]) => method)
      expect(methods.indexOf('onboarding.channel.probe'))
        .toBeLessThan(methods.indexOf('onboarding.channel.upsert'))
      const upsertCall = rpcCall.mock.calls.find(([method]) => method === 'onboarding.channel.upsert')!
      const entry = (upsertCall[1] as { entry: Record<string, unknown> }).entry
      expect(entry).toMatchObject({ name: 'ops-slack', slack_channel_id: 'C123' })
      expect(JSON.stringify(entry)).not.toContain('***')
      expect(pushToast).toHaveBeenCalledWith(
        'Channel saved — configuration validated locally; use Test connection to verify credentials',
        { tone: 'ok' },
      )
      // Baseline reset from the reseed: read mode, no dirty dot, no bar.
      expect(detail.querySelector('[data-field="slack_channel_id"] input')).toBeNull()
      expect(detail.querySelector('.ch-tab-dirty')).toBeNull()
      expect(el.querySelector('.ceb')).toBeNull()
    } finally {
      ctx.app.unmount()
    }
  })

  it('blocks Save on a failed probe with inline rows and offers Save anyway', async () => {
    const ctx = await mountChannelsView({
      draftProbeError: { message: 'invalid channel entry: token: Field required' },
    })
    const { el, flush, rpcCall } = ctx
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)
      setField(detail, 'slack_channel_id', 'C123')
      await flush()

      buttonWithText(bar(el), 'Save changes').click()
      await flush()
      expect(rpcCall.mock.calls.some(([method]) => method === 'onboarding.channel.upsert')).toBe(false)
      expect(detail.textContent).toContain('invalid channel entry: token: Field required')

      buttonWithText(detail, 'Save anyway').click()
      await flush()
      await flush()
      expect(rpcCall.mock.calls.some(([method]) => method === 'onboarding.channel.upsert')).toBe(true)
    } finally {
      ctx.app.unmount()
    }
  })

  it('guards channel switching behind the inline discard confirm', async () => {
    const ctx = await mountChannelsView()
    const { el, flush, rpcCall } = ctx
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)
      setField(detail, 'slack_channel_id', 'C123')
      await flush()

      channelRow(el, 'alerts-telegram').click()
      await flush()
      // The wipe waited: still on ops-slack, confirm pair raised in the bar.
      expect(detail.querySelector('h2')?.textContent).toBe('ops-slack')
      expect(bar(el).textContent).toContain('Discard unsaved changes?')

      buttonWithText(bar(el), 'Keep editing').click()
      await flush()
      expect(detail.querySelector('h2')?.textContent).toBe('ops-slack')
      const input = detail.querySelector<HTMLInputElement>('[data-field="slack_channel_id"] input')!
      expect(input.value).toBe('C123')
      expect(bar(el).textContent).toContain('Unsaved — Default channel id')

      channelRow(el, 'alerts-telegram').click()
      await flush()
      buttonWithText(bar(el), 'Discard').click()
      await flush()
      expect(el.querySelector('.ch-detail h2')?.textContent).toBe('alerts-telegram')
      expect(rpcCall.mock.calls.some(([method]) => method === 'onboarding.channel.upsert')).toBe(false)
    } finally {
      ctx.app.unmount()
    }
  })

  it('never round-trips the redaction sentinel through secret Replace/Cancel', async () => {
    const ctx = await mountChannelsView()
    const { el, flush, nextTick, rpcCall } = ctx
    try {
      const detail = await openConfiguration(ctx)
      await enterEditMode(ctx, detail)

      // Replace → type → cancel: the stored value stays authoritative.
      const tokenRow = detail.querySelector<HTMLElement>('[data-field="token"]')!
      buttonWithText(tokenRow, 'Replace').click()
      await nextTick()
      setField(detail, 'token', 'xoxb-typed-then-cancelled')
      await nextTick()
      buttonWithText(tokenRow, 'Keep stored value').click()
      await nextTick()
      expect(tokenRow.textContent).toContain('Stored ······')

      // Replace the other secret for real and save.
      const signingRow = detail.querySelector<HTMLElement>('[data-field="signing_secret"]')!
      buttonWithText(signingRow, 'Replace').click()
      await nextTick()
      setField(detail, 'signing_secret', 'shhh-new-secret')
      await flush()

      buttonWithText(bar(el), 'Save changes').click()
      await flush()
      await flush()

      for (const method of ['onboarding.channel.probe', 'onboarding.channel.upsert']) {
        const call = rpcCall.mock.calls.find(([m]) => m === method)!
        const entry = (call[1] as { entry: Record<string, unknown> }).entry
        expect(entry.signing_secret).toBe('shhh-new-secret')
        expect('token' in entry).toBe(false)
        expect(JSON.stringify(entry)).not.toContain('***')
      }
      // The reseed masks the replaced secret again.
      expect(detail.querySelector<HTMLElement>('[data-field="signing_secret"]')?.textContent)
        .toContain('Stored ······')
    } finally {
      ctx.app.unmount()
    }
  })
})
