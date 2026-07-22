// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

async function mountJumpCard(options: {
  statusError?: boolean
  channels?: Array<{ name: string; configured?: boolean; connected?: boolean }>
} = {}) {
  vi.resetModules()

  const { createApp, nextTick } = await import('vue')
  const i18n = (await import('@/i18n')).default
  i18n.global.locale.value = 'en'

  const push = vi.fn(async (_to: unknown) => {})
  const rpcCall = vi.fn(async (method: string) => {
    if (method === 'channels.status') {
      if (options.statusError) throw new Error('gateway unreachable')
      return { channels: options.channels || [] }
    }
    throw new Error(`unexpected rpc method: ${method}`)
  })

  vi.doMock('vue-router', () => ({
    useRouter: () => ({ push }),
  }))
  vi.doMock('@/stores/rpc', () => ({
    useRpcStore: () => ({ call: rpcCall, waitForConnection: async () => {} }),
  }))

  const Component = (await import('./SettingsChannelsJumpCard.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(Component)
  app.use(i18n)
  app.mount(el)
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()

  return { app, el, push, rpcCall }
}

function buttonWithText(root: ParentNode, label: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
    .find(candidate => candidate.textContent?.trim() === label)
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.doUnmock('vue-router')
  vi.doUnmock('@/stores/rpc')
})

describe('SettingsChannelsJumpCard', () => {
  it('summarizes channel status and routes to the workspace', async () => {
    const { app, el, push } = await mountJumpCard({
      channels: [
        { name: 'a', connected: true },
        { name: 'b', connected: false },
        { name: 'runtime-only', configured: false, connected: true },
      ],
    })
    try {
      expect(el.textContent).toContain('2 configured · 1 connected')

      buttonWithText(el, 'Open channel workspace').click()
      expect(push).toHaveBeenCalledWith('/channels')

      buttonWithText(el, 'Add channel').click()
      expect(push).toHaveBeenCalledWith({ path: '/channels', query: { compose: '1' } })
    } finally {
      app.unmount()
    }
  })

  it('falls back to static copy when channels.status is unavailable', async () => {
    const { app, el } = await mountJumpCard({ statusError: true })
    try {
      expect(el.textContent).toContain('Add, edit, and test chat channels on the workspace.')
    } finally {
      app.unmount()
    }
  })
})
