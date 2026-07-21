// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/i18n'
import { useRpcStore } from '@/stores/rpc'
import type { ArtifactPayload } from '@/types/rpc'
import ChatArtifactList from './ChatArtifactList.vue'

const htmlArtifact: ArtifactPayload = {
  id: 'art-html',
  name: 'page.html',
  mime: 'text/html',
  download_url: '/api/v1/artifacts/art-html',
}

async function settle() {
  await Promise.resolve()
  await nextTick()
}

async function mountList(options: {
  isOwner: boolean
  artifact?: ArtifactPayload
  onDownload?: (artifact: ArtifactPayload) => void
}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const pinia = createPinia()
  setActivePinia(pinia)
  const rpc = useRpcStore(pinia)
  rpc.auth = { principal: { isOwner: options.isOwner } }
  const app = createApp(ChatArtifactList, {
    artifacts: [options.artifact || htmlArtifact],
    sessionKey: 'agent:main:webchat:ok',
    authToken: 'secret',
    onDownload: options.onDownload,
  })
  app.use(pinia)
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('ChatArtifactList native HTML open', () => {
  it('renders HTML artifacts inline in a sandboxed iframe for owner Web sessions', async () => {
    // Inline preview fetches the artifact bytes (GET) and renders a blob object
    // URL in a sandboxed iframe instead of POSTing to the gateway new-tab
    // endpoint. Stub createObjectURL so happy-dom does not try to navigate the
    // iframe to a real blob: URL (unsupported in the test environment).
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, _opts?: RequestInit) => new Response('<h1>hi</h1>', {
      status: 200,
      headers: { 'content-type': 'text/html' },
    }))
    vi.stubGlobal('fetch', fetchImpl)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('about:blank')
    vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined)
    const { app, el } = await mountList({ isOwner: true })

    const open = Array.from(el.querySelectorAll<HTMLButtonElement>('.msg-artifact-action'))
      .find(button => button.textContent?.includes('Open'))
    expect(open).toBeTruthy()
    open?.click()
    await settle()
    await settle()

    // Fetches the artifact bytes with GET (not a POST to the /open endpoint).
    expect(fetchImpl).toHaveBeenCalled()
    const [calledUrl, calledOpts] = fetchImpl.mock.calls[0]
    expect(String(calledUrl)).toContain('/api/v1/artifacts/art-html')
    expect(String(calledUrl)).not.toContain('/open')
    expect((calledOpts as RequestInit | undefined)?.method).toBe('GET')

    // The inline preview dialog renders a sandboxed iframe (no allow-same-origin).
    const dialog = el.querySelector('[role="dialog"]')
    expect(dialog).toBeTruthy()
    const iframe = dialog?.querySelector('iframe')
    expect(iframe).toBeTruthy()
    expect(iframe?.getAttribute('sandbox')).toBe('allow-scripts')
    app.unmount()
  })

  it('renders HTML artifacts as download-only for non-owner Web sessions', async () => {
    const fetchImpl = vi.fn()
    vi.stubGlobal('fetch', fetchImpl)
    const onDownload = vi.fn()
    const { app, el } = await mountList({ isOwner: false, onDownload })

    expect(el.textContent).not.toContain('Open')
    expect(el.textContent).toContain('Download')
    el.querySelector<HTMLButtonElement>('.msg-artifact-body')?.click()
    await nextTick()

    expect(onDownload).toHaveBeenCalledWith(htmlArtifact)
    expect(fetchImpl).not.toHaveBeenCalled()
    app.unmount()
  })
})
