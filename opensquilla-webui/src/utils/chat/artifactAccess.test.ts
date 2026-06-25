import { describe, expect, it, vi } from 'vitest'
import type { ArtifactPayload } from '@/types/rpc'
import {
  artifactAccessHeaders,
  artifactAccessUrl,
  artifactOpenFailureMessage,
  fetchArtifactBlob,
  openArtifactBlobUrl,
} from './artifactAccess'

function artifact(overrides: Partial<ArtifactPayload> = {}): ArtifactPayload {
  return {
    id: 'art-report',
    name: 'report.md',
    mime: 'text/markdown',
    download_url: '/api/v1/artifacts/art-report?token=old-token&sessionKey=old-session&session_key=old-session-snake',
    ...overrides,
  }
}

describe('artifactAccessUrl', () => {
  it('removes token and session query values for same-origin artifact URLs', () => {
    expect(artifactAccessUrl(artifact(), 'http://127.0.0.1:18793')).toBe('/api/v1/artifacts/art-report')
  })

  it('keeps cross-origin URLs absolute and does not rewrite their query string', () => {
    const url = artifactAccessUrl(
      artifact({ download_url: 'https://files.example.test/artifacts/art-report?token=share-token' }),
      'http://127.0.0.1:18793',
    )

    expect(url).toBe('https://files.example.test/artifacts/art-report?token=share-token')
  })

  it('builds the default artifact route from the artifact id', () => {
    expect(artifactAccessUrl(artifact({ download_url: undefined }), 'http://127.0.0.1:18793')).toBe(
      '/api/v1/artifacts/art-report',
    )
  })
})

describe('artifactAccessHeaders', () => {
  it('adds WebUI auth and session headers for same-origin artifact fetches', () => {
    expect(artifactAccessHeaders('/api/v1/artifacts/art-report', {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
    })).toEqual({
      'x-opensquilla-session-key': 'agent:main:webchat:ok',
      Authorization: 'Bearer secret',
    })
  })

  it('does not attach local credentials to cross-origin artifact URLs', () => {
    expect(artifactAccessHeaders('https://files.example.test/artifacts/art-report', {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
    })).toEqual({})
  })
})

describe('fetchArtifactBlob', () => {
  it('fetches the sanitized artifact URL with WebUI headers', async () => {
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': 'text/markdown' },
    }))

    const result = await fetchArtifactBlob(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
    })

    expect(result.ok).toBe(true)
    expect(fetchImpl).toHaveBeenCalledWith('/api/v1/artifacts/art-report', {
      method: 'GET',
      headers: {
        'x-opensquilla-session-key': 'agent:main:webchat:ok',
        Authorization: 'Bearer secret',
      },
      credentials: 'same-origin',
    })
    if (result.ok) {
      expect(await result.blob.text()).toBe('hello')
      expect(result.blob.type).toBe('text/markdown')
    }
  })

  it('omits WebUI credentials for cross-origin artifact fetches', async () => {
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': 'text/markdown' },
    }))

    const result = await fetchArtifactBlob(
      artifact({ download_url: 'https://files.example.test/artifacts/art-report?token=share-token' }),
      {
        baseOrigin: 'http://127.0.0.1:18793',
        sessionKey: 'agent:main:webchat:ok',
        authToken: 'secret',
        fetchImpl,
      },
    )

    expect(result.ok).toBe(true)
    expect(fetchImpl).toHaveBeenCalledWith('https://files.example.test/artifacts/art-report?token=share-token', {
      method: 'GET',
      headers: {},
      credentials: 'omit',
    })
  })

  it('returns a user-facing failure result when the server rejects the request', async () => {
    const fetchImpl = vi.fn(async () => new Response('{"code":"NOT_FOUND"}', {
      status: 404,
      headers: { 'content-type': 'application/json' },
    }))

    const result = await fetchArtifactBlob(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:missing',
      authToken: 'secret',
      fetchImpl,
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.status).toBe(404)
      expect(result.message).toBe('Artifact is unavailable in this session: report.md')
    }
  })
})

describe('openArtifactBlobUrl', () => {
  it('opens a blob URL created from the authenticated artifact response', async () => {
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': 'text/markdown' },
    }))
    const createObjectUrl = vi.fn(() => 'blob:artifact-report')
    const revokeObjectUrl = vi.fn()
    const opened = { opener: {}, location: { href: '' }, close: vi.fn() }
    const openWindow = vi.fn(() => opened)
    const scheduleRevoke = vi.fn((_url: string, revoke: () => void) => revoke())

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      revokeObjectUrl,
      openWindow,
      scheduleRevoke,
    })

    expect(result.ok).toBe(true)
    expect(createObjectUrl).toHaveBeenCalledOnce()
    expect(openWindow).toHaveBeenCalledWith('', '_blank', '')
    expect(opened.opener).toBeNull()
    expect(opened.location.href).toBe('blob:artifact-report')
    expect(scheduleRevoke).toHaveBeenCalledOnce()
    expect(scheduleRevoke.mock.calls[0][0]).toBe('blob:artifact-report')
    expect(typeof scheduleRevoke.mock.calls[0][1]).toBe('function')
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:artifact-report')
  })

  it('returns failure and revokes immediately when the browser blocks the new tab', async () => {
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': 'text/markdown' },
    }))
    const createObjectUrl = vi.fn(() => 'blob:artifact-report')
    const revokeObjectUrl = vi.fn()
    const openWindow = vi.fn(() => null)
    const scheduleRevoke = vi.fn()

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      revokeObjectUrl,
      openWindow,
      scheduleRevoke,
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.status).toBe(0)
      expect(result.message).toBe('Artifact open failed. Use Download instead: report.md')
    }
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(createObjectUrl).not.toHaveBeenCalled()
    expect(revokeObjectUrl).not.toHaveBeenCalled()
    expect(scheduleRevoke).not.toHaveBeenCalled()
  })

  it('fails closed when opener isolation throws', async () => {
    const opened = {
      get opener() { return {} },
      set opener(_value: unknown) { throw new Error('nope') },
      location: { href: '' },
      close: vi.fn(),
    }
    const fetchImpl = vi.fn(async () => new Response('hello'))
    const openWindow = vi.fn(() => opened)

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      openWindow,
    })

    expect(result.ok).toBe(false)
    expect(opened.close).toHaveBeenCalledOnce()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('fails closed when opener isolation cannot be verified', async () => {
    const opened = { opener: {}, location: { href: '' }, close: vi.fn(() => undefined) }
    Object.defineProperty(opened, 'opener', {
      configurable: true,
      get: () => ({}),
      set: () => {},
    })
    const fetchImpl = vi.fn(async () => new Response('hello'))
    const openWindow = vi.fn(() => opened)

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      openWindow,
    })

    expect(result.ok).toBe(false)
    expect(opened.close).toHaveBeenCalledOnce()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('closes the pre-opened tab when the authenticated fetch fails', async () => {
    const opened = { opener: {}, location: { href: '' }, close: vi.fn() }
    const fetchImpl = vi.fn(async () => new Response('missing', { status: 404 }))
    const openWindow = vi.fn(() => opened)

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:missing',
      authToken: 'secret',
      fetchImpl,
      openWindow,
    })

    expect(result.ok).toBe(false)
    expect(opened.close).toHaveBeenCalledOnce()
    expect(opened.location.href).toBe('')
  })

  it('revokes and closes when blob navigation fails', async () => {
    const location = {
      get href() { return '' },
      set href(_value: string) { throw new Error('navigation blocked') },
    }
    const opened = { opener: {}, location, close: vi.fn() }
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': 'text/markdown' },
    }))
    const createObjectUrl = vi.fn(() => 'blob:artifact-report')
    const revokeObjectUrl = vi.fn()
    const openWindow = vi.fn(() => opened)
    const scheduleRevoke = vi.fn()

    const result = await openArtifactBlobUrl(artifact(), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      revokeObjectUrl,
      openWindow,
      scheduleRevoke,
    })

    expect(result.ok).toBe(false)
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:artifact-report')
    expect(opened.close).toHaveBeenCalledOnce()
    expect(scheduleRevoke).not.toHaveBeenCalled()
  })

  it('does not open active HTML artifacts as same-origin blob documents', async () => {
    const opened = { opener: {}, location: { href: '' }, close: vi.fn() }
    const fetchImpl = vi.fn(async () => new Response('<script>window.__x = 1</script>', {
      status: 200,
      headers: { 'content-type': 'text/html' },
    }))
    const createObjectUrl = vi.fn(() => 'blob:artifact-html')
    const openWindow = vi.fn(() => opened)
    const scheduleRevoke = vi.fn()

    const result = await openArtifactBlobUrl(artifact({ name: 'page.html', mime: 'text/html' }), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      openWindow,
      scheduleRevoke,
    })

    expect(result.ok).toBe(false)
    expect(createObjectUrl).not.toHaveBeenCalled()
    expect(opened.close).toHaveBeenCalledOnce()
    expect(opened.location.href).toBe('')
    expect(scheduleRevoke).not.toHaveBeenCalled()
  })

  it('blocks active HTML artifacts even when the response content type is missing', async () => {
    const opened = { opener: {}, location: { href: '' }, close: vi.fn() }
    const fetchImpl = vi.fn(async () => new Response('<html></html>', { status: 200 }))
    const createObjectUrl = vi.fn(() => 'blob:artifact-html')
    const openWindow = vi.fn(() => opened)

    const result = await openArtifactBlobUrl(artifact({ name: 'page.html', mime: '' }), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      openWindow,
    })

    expect(result.ok).toBe(false)
    expect(createObjectUrl).not.toHaveBeenCalled()
    expect(opened.close).toHaveBeenCalledOnce()
  })

  it.each([
    ['notes.md', 'text/markdown'],
    ['notes.txt', 'text/plain'],
    ['report.pdf', 'application/pdf'],
  ])('opens passive document artifacts: %s', async (name, mime) => {
    const opened = { opener: {}, location: { href: '' }, close: vi.fn() }
    const fetchImpl = vi.fn(async () => new Response('hello', {
      status: 200,
      headers: { 'content-type': mime },
    }))
    const createObjectUrl = vi.fn(() => `blob:${name}`)
    const openWindow = vi.fn(() => opened)
    const scheduleRevoke = vi.fn()

    const result = await openArtifactBlobUrl(artifact({ name, mime }), {
      baseOrigin: 'http://127.0.0.1:18793',
      sessionKey: 'agent:main:webchat:ok',
      authToken: 'secret',
      fetchImpl,
      createObjectUrl,
      openWindow,
      scheduleRevoke,
    })

    expect(result.ok).toBe(true)
    expect(opened.location.href).toBe(`blob:${name}`)
    expect(opened.close).not.toHaveBeenCalled()
  })
})

describe('artifactOpenFailureMessage', () => {
  it('distinguishes auth, session, and network failures', () => {
    expect(artifactOpenFailureMessage(401, 'report.md')).toBe('Artifact open is not authorized. Refresh the page and try again.')
    expect(artifactOpenFailureMessage(403, 'report.md')).toBe('Artifact open is not authorized. Refresh the page and try again.')
    expect(artifactOpenFailureMessage(404, 'report.md')).toBe('Artifact is unavailable in this session: report.md')
    expect(artifactOpenFailureMessage(0, 'report.md')).toBe('Artifact open failed. Use Download instead: report.md')
  })
})
