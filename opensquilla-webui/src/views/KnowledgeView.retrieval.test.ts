// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  KeepAlive,
  createApp,
  defineComponent,
  h,
  nextTick,
  ref,
  type App,
  type Ref,
} from 'vue'
import i18n from '@/i18n'
import de from '@/locales/de.json'
import en from '@/locales/en.json'
import es from '@/locales/es.json'
import fr from '@/locales/fr.json'
import ja from '@/locales/ja.json'
import zhHans from '@/locales/zh-Hans.json'

const rpcMock = vi.hoisted(() => ({
  call: vi.fn(),
  waitForConnection: vi.fn(),
}))

vi.mock('@/stores/rpc', () => ({
  useRpcStore: () => rpcMock,
}))

import KnowledgeView from './KnowledgeView.vue'
import {
  browserManagementLink,
  effectiveRetrievalProfile,
  normalizeRagGetResponse,
  normalizeRagProfileSetResponse,
  normalizeRagProviderStatus,
  normalizeRagSearchResponse,
  type RagProviderStatus,
} from './ragProvider'

const READY_STATUS: RagProviderStatus = {
  connectionState: 'READY',
  enabled: true,
  provider: { name: 'OpenSquilla-Knowledge', version: '1.0', instanceId: 'preview' },
  protocolVersion: '1.0',
  capabilities: { search: true, get: true },
  effectiveLimits: {
    maxSearchResults: 20,
    maxSnippetChars: 800,
    maxSearchResponseChars: 12000,
    maxGetContentChars: 8000,
    maxChunkChars: null,
  },
  searchOptions: {
    supportsCollectionScope: true,
    retrievalProfiles: [
      { id: 'hybrid', label: 'Hybrid' },
      { id: 'vector', label: 'Vector' },
    ],
    defaultRetrievalProfile: 'hybrid',
  },
  links: { management: 'https://knowledge.example.com/manage' },
  lastSuccessAt: 1_700_000_000,
  lastErrorCode: null,
  consecutiveFailures: 0,
  retrievalProfileOverride: null,
  collectionScope: ['datasets'],
  legacyConfigPresent: false,
  legacyAdapterEnabled: false,
  warning: null,
}

const PROFILE_SET_RESPONSE = {
  retrievalProfileOverride: 'vector',
  providerDefaultRetrievalProfile: 'hybrid',
  effectiveRetrievalProfile: 'vector',
  restartRequired: false,
}

const NULL_PROFILE_SET_RESPONSE = {
  retrievalProfileOverride: null,
  providerDefaultRetrievalProfile: null,
  effectiveRetrievalProfile: null,
  restartRequired: false,
}

const SEARCH_RESPONSE = {
  returnedCount: 1,
  totalMatched: 9,
  resultsTruncated: true,
  providerBudgetViolation: false,
  results: [{
    evidenceId: 'ev_a',
    snippet: 'NAND evidence',
    snippetTruncated: false,
    citation: { title: 'Document A', locator: 'page 1' },
  }],
}

const V11_SEARCH_RESPONSE = (() => {
  const content = 'Complete normalized NAND evidence.'
  return {
    returnedCount: 1,
    totalMatched: 7,
    resultsTruncated: false,
    retrieval: { profile: 'provider-profile' },
    providerBudgetViolation: false,
    results: [{
      evidenceId: 'ev_full',
      rank: 1,
      document: {
        id: 'doc_a',
        title: 'NAND architecture',
        source: 'datasets',
        fileName: 'nand.md',
        sourcePath: 'datasets/nand.md',
        mediaType: 'text/markdown',
        revision: 'sha256:abc',
        uri: 'knowledge://documents/doc_a',
        openUrl: '/knowledge/files/doc_a?chunkId=chunk_a',
      },
      chunk: {
        id: 'chunk_a',
        content,
        contentChars: content.length,
      },
      snippet: 'Complete normalized',
      snippetTruncated: true,
      citation: {
        title: 'NAND architecture',
        source: 'datasets',
        locator: 'section 2',
        uri: 'knowledge://documents/doc_a#chunk=chunk_a',
      },
    }],
  }
})()

const V11_GET_RESPONSE = (() => {
  const content = 'Complete paged NAND evidence.'
  return {
    evidenceId: 'ev_full',
    document: structuredClone(V11_SEARCH_RESPONSE.results[0].document),
    content,
    contentChars: content.length,
    previousCursor: 'previous-page',
    nextCursor: 'next-page',
    citation: structuredClone(V11_SEARCH_RESPONSE.results[0].citation),
  }
})()

const GET_RESPONSE = {
  evidenceId: 'ev_a',
  document: { title: 'Document A', source: 'datasets' },
  content: 'Normalized source text',
  previousCursor: null,
  nextCursor: 'next-page',
  citation: { title: 'Document A', locator: 'page 1' },
}

async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

async function submitQuery(root: HTMLElement, value: string) {
  const query = root.querySelector<HTMLTextAreaElement>('[data-testid="rag-query"]')!
  query.value = value
  query.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="rag-search"]')!.click()
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

type JsonObject = Record<string, unknown>

function leafPaths(value: JsonObject, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return item && typeof item === 'object' && !Array.isArray(item)
      ? leafPaths(item as JsonObject, path)
      : [path]
  })
}

const EXPECTED_RAG_KEYS = [
  'title', 'subtitle', 'refresh', 'refreshing', 'management', 'managementLocalOnly',
  'status.ready', 'status.degraded', 'status.unavailable', 'status.incompatible',
  'status.connecting', 'status.disabled', 'status.legacy',
  'profile.title', 'profile.description', 'profile.current', 'profile.providerDefault',
  'profile.followProvider', 'profile.notDeclared', 'profile.providerDefaultBadge',
  'profile.activeBadge', 'profile.unsaved', 'profile.unavailable', 'profile.save',
  'profile.saving',
  'search.title', 'search.placeholder', 'search.advanced', 'search.limit', 'search.submit',
  'search.searching',
  'results.title', 'results.returned', 'results.matched', 'results.truncated',
  'results.budgetTrimmed', 'results.snippetTruncated', 'results.empty',
  'reader.title', 'reader.empty', 'reader.loading', 'reader.backToResults',
  'reader.previous', 'reader.next', 'reader.legacyLimited',
  'details.title', 'details.connection', 'details.protocol', 'details.budgets',
  'errors.invalidStatusResponse', 'errors.invalidProfileResponse',
  'errors.invalidSearchResponse', 'errors.invalidGetResponse',
].sort()

const P14_RAG_KEYS = [
  'results.completeChunk',
  'results.chunkCharacters',
  'results.providerExecutedProfile',
  'results.fileName',
  'results.sourcePath',
].sort()

function ragMessages(locale: unknown): JsonObject {
  return ((locale as JsonObject).rag ?? {}) as JsonObject
}

describe('RAG production locale messages', () => {
  it('ships the baseline namespace and keeps P14-owned additions aligned', () => {
    const localeKeys = [en, zhHans, ja, fr, de, es]
      .map(locale => leafPaths(ragMessages(locale)).sort())
    const allowed = new Set([...EXPECTED_RAG_KEYS, ...P14_RAG_KEYS])
    for (const keys of localeKeys) {
      expect(keys).toEqual(expect.arrayContaining(EXPECTED_RAG_KEYS))
      expect(keys.every(key => allowed.has(key))).toBe(true)
    }
    for (const key of P14_RAG_KEYS) {
      expect(new Set(localeKeys.map(keys => keys.includes(key))).size).toBe(1)
    }
  })

  it('keeps approved Chinese copy and applies every language-review replacement', () => {
    expect(ragMessages(zhHans)).toMatchObject({
      title: '知识检索',
      subtitle: '通过已连接的 RAG Provider 检索外部知识，并查看可引用原文。',
      managementLocalOnly: 'Provider 提供了仅本机可用的管理入口。',
      profile: { title: '默认检索方式', followProvider: '跟随 Provider 默认', save: '设为 OpenSquilla 默认' },
      results: { budgetTrimmed: 'OpenSquilla 已按预算裁剪' },
      reader: { previous: '上一段', next: '下一段' },
    })
    expect(ragMessages(ja)).toMatchObject({
      profile: { notDeclared: 'プロバイダーの既定値は宣言されていません' },
      search: { limit: '取得する結果数' },
      results: { budgetTrimmed: 'OpenSquilla の上限に合わせて短縮' },
    })
    expect(ragMessages(fr)).toMatchObject({
      title: 'Recherche dans la base de connaissances',
      managementLocalOnly: 'Le fournisseur expose un chemin d’administration accessible uniquement en local.',
      profile: { providerDefaultBadge: 'Défini par le fournisseur', save: 'Définir par défaut dans OpenSquilla' },
      search: { title: 'Rechercher dans la base de connaissances' },
      results: { returned: 'Résultats renvoyés : {count}', matched: 'Correspondances : {count}' },
      reader: { title: 'Lecteur du texte source' },
    })
    expect(ragMessages(de)).toMatchObject({
      profile: { current: 'Derzeit aktiv', save: 'OpenSquilla-Standard setzen' },
    })
    expect(ragMessages(es)).toMatchObject({
      managementLocalOnly: 'El proveedor ofrece una ruta de gestión accesible solo desde el equipo local.',
      profile: { providerDefaultBadge: 'Definido por el proveedor', save: 'Usar como predeterminado en OpenSquilla' },
      results: { returned: 'Resultados devueltos: {count}', matched: 'Coincidencias: {count}' },
    })
  })
})

describe('RAG Provider response normalization', () => {
  it('accepts every declared state and requires complete READY capabilities', () => {
    for (const connectionState of ['READY', 'DEGRADED', 'LEGACY']) {
      expect(normalizeRagProviderStatus({ ...READY_STATUS, connectionState })?.connectionState).toBe(connectionState)
    }
    for (const connectionState of ['DISABLED', 'CONNECTING', 'UNAVAILABLE', 'INCOMPATIBLE']) {
      expect(normalizeRagProviderStatus({
        ...READY_STATUS,
        connectionState,
        provider: null,
        protocolVersion: null,
        capabilities: null,
        effectiveLimits: null,
        searchOptions: null,
      })?.connectionState).toBe(connectionState)
    }
    expect(normalizeRagProviderStatus({ ...READY_STATUS, provider: null })).toBeNull()
  })

  it('fails closed on malformed status and unsafe management links', () => {
    expect(normalizeRagProviderStatus({ ...READY_STATUS, enabled: 'true' })).toBeNull()
    expect(normalizeRagProviderStatus({ ...READY_STATUS, consecutiveFailures: -1 })).toBeNull()
    expect(normalizeRagProviderStatus({
      ...READY_STATUS,
      links: { management: 'javascript:alert(1)' },
    })).toBeNull()
  })

  it('normalizes maxChunkChars for Protocol 1.1 while preserving Protocol 1.0', () => {
    expect(normalizeRagProviderStatus(READY_STATUS)?.effectiveLimits?.maxChunkChars).toBeNull()
    expect(normalizeRagProviderStatus({
      ...READY_STATUS,
      protocolVersion: '1.1',
      effectiveLimits: {
        ...READY_STATUS.effectiveLimits!,
        maxChunkChars: 4096,
      },
    })?.effectiveLimits?.maxChunkChars).toBe(4096)
    expect(normalizeRagProviderStatus({
      ...READY_STATUS,
      protocolVersion: '1.1',
      effectiveLimits: {
        ...READY_STATUS.effectiveLimits!,
        maxChunkChars: 0,
      },
    })).toBeNull()
  })

  it('requires returnedCount to match the actual search array', () => {
    expect(normalizeRagSearchResponse(SEARCH_RESPONSE)?.results).toHaveLength(1)
    expect(normalizeRagSearchResponse({ ...SEARCH_RESPONSE, returnedCount: 20 })).toBeNull()
    expect(normalizeRagSearchResponse({ ...SEARCH_RESPONSE, providerBudgetViolation: 'false' })).toBeNull()
  })

  it('keeps Protocol 1.0 search snippet-based when Protocol 1.1 fields are absent', () => {
    const normalized = normalizeRagSearchResponse(SEARCH_RESPONSE)
    expect(normalized).toMatchObject({
      returnedCount: 1,
      totalMatched: 9,
      retrievalProfile: null,
      results: [{
        evidenceId: 'ev_a',
        rank: null,
        document: null,
        chunk: null,
        snippet: 'NAND evidence',
      }],
    })
  })

  it('normalizes complete Protocol 1.1 search results without requiring a response query', () => {
    const normalized = normalizeRagSearchResponse({
      ...structuredClone(V11_SEARCH_RESPONSE),
      query: 'must be ignored',
    })
    expect(normalized).toMatchObject({
      returnedCount: 1,
      totalMatched: 7,
      retrievalProfile: 'provider-profile',
      results: [{
        evidenceId: 'ev_full',
        rank: 1,
        document: {
          id: 'doc_a',
          fileName: 'nand.md',
          sourcePath: 'datasets/nand.md',
          openUrl: '/knowledge/files/doc_a?chunkId=chunk_a',
        },
        chunk: {
          id: 'chunk_a',
          content: 'Complete normalized NAND evidence.',
          contentChars: 34,
        },
      }],
    })
    expect(normalized).not.toHaveProperty('query')
    const withoutTotalMatched: Partial<typeof V11_SEARCH_RESPONSE> = structuredClone(V11_SEARCH_RESPONSE)
    delete withoutTotalMatched.totalMatched
    expect(normalizeRagSearchResponse(withoutTotalMatched)?.totalMatched).toBeNull()
  })

  it('rejects misleading counts and invalid Protocol 1.1 core fields', () => {
    expect(normalizeRagSearchResponse({
      ...structuredClone(V11_SEARCH_RESPONSE),
      returnedCount: 20,
    })).toBeNull()
    for (const rank of [0, 2, -1, true]) {
      const payload = structuredClone(V11_SEARCH_RESPONSE)
      payload.results[0].rank = rank as unknown as number
      expect(normalizeRagSearchResponse(payload)).toBeNull()
    }
    for (const contentChars of [-1, 999, true]) {
      const payload = structuredClone(V11_SEARCH_RESPONSE)
      payload.results[0].chunk.contentChars = contentChars as unknown as number
      expect(normalizeRagSearchResponse(payload)).toBeNull()
    }
    expect(normalizeRagSearchResponse({
      ...structuredClone(V11_SEARCH_RESPONSE),
      retrieval: { profile: 7 },
    })).toBeNull()
    const unsafeCitation = structuredClone(V11_SEARCH_RESPONSE)
    unsafeCitation.results[0].citation.uri = 'javascript:alert(1)'
    expect(normalizeRagSearchResponse(unsafeCitation)).toBeNull()
  })

  it('safely drops unsafe paths, URLs, URIs, and malformed optional document metadata', () => {
    const payload = structuredClone(V11_SEARCH_RESPONSE)
    Object.assign(payload.results[0].document, {
      source: 7,
      mediaType: false,
      sourcePath: '/etc/passwd',
      uri: 'javascript:alert(1)',
      openUrl: 'javascript:alert(1)',
    })
    const document = normalizeRagSearchResponse(payload)?.results[0].document
    expect(document).toMatchObject({ id: 'doc_a', title: 'NAND architecture', fileName: 'nand.md' })
    expect(document).not.toHaveProperty('source')
    expect(document).not.toHaveProperty('mediaType')
    expect(document).not.toHaveProperty('sourcePath')
    expect(document).not.toHaveProperty('uri')
    expect(document).not.toHaveProperty('openUrl')
  })

  it('validates get cursors and normalized document content', () => {
    expect(normalizeRagGetResponse(GET_RESPONSE)?.nextCursor).toBe('next-page')
    expect(normalizeRagGetResponse({ ...GET_RESPONSE, nextCursor: 1 })).toBeNull()
    expect(normalizeRagGetResponse({ ...GET_RESPONSE, content: null })).toBeNull()
  })

  it('normalizes Protocol 1.1 Get metadata, content characters, and cursors', () => {
    expect(normalizeRagGetResponse(V11_GET_RESPONSE)).toMatchObject({
      evidenceId: 'ev_full',
      document: {
        id: 'doc_a',
        title: 'NAND architecture',
        fileName: 'nand.md',
        sourcePath: 'datasets/nand.md',
      },
      content: 'Complete paged NAND evidence.',
      contentChars: 29,
      previousCursor: 'previous-page',
      nextCursor: 'next-page',
    })
    expect(normalizeRagGetResponse({
      ...structuredClone(V11_GET_RESPONSE),
      contentChars: 999,
    })).toBeNull()
    expect(normalizeRagGetResponse({
      ...structuredClone(V11_GET_RESPONSE),
      previousCursor: '',
    })).toBeNull()
  })

  it('safely omits unsafe optional Get document metadata', () => {
    const payload = structuredClone(V11_GET_RESPONSE)
    payload.document.sourcePath = '../secrets.txt'
    payload.document.uri = 'file:///etc/passwd'
    payload.document.openUrl = 'https://user:pass@example.com/private'
    const document = normalizeRagGetResponse(payload)?.document
    expect(document).not.toHaveProperty('sourcePath')
    expect(document).not.toHaveProperty('uri')
    expect(document).not.toHaveProperty('openUrl')
  })

  it('derives the effective profile from override before provider default', () => {
    expect(effectiveRetrievalProfile(READY_STATUS)).toBe('hybrid')
    expect(effectiveRetrievalProfile({
      ...READY_STATUS,
      retrievalProfileOverride: 'vector',
    })).toBe('vector')
  })

  it('does not fall back when an invalid explicit profile is present', () => {
    expect(effectiveRetrievalProfile({
      ...READY_STATUS,
      retrievalProfileOverride: '',
    })).toBe('')
  })

  it('normalizes profile set responses strictly', () => {
    expect(normalizeRagProfileSetResponse(PROFILE_SET_RESPONSE)).toEqual(PROFILE_SET_RESPONSE)
    expect(normalizeRagProfileSetResponse(NULL_PROFILE_SET_RESPONSE)).toEqual(NULL_PROFILE_SET_RESPONSE)
    expect(normalizeRagProfileSetResponse({
      ...PROFILE_SET_RESPONSE,
      restartRequired: 'false',
    })).toBeNull()
  })

  it.each([
    ['retrievalProfileOverride', undefined],
    ['providerDefaultRetrievalProfile', false],
    ['effectiveRetrievalProfile', 1],
  ] as const)('rejects an invalid nullable-string field: %s', (field, value) => {
    expect(normalizeRagProfileSetResponse({
      ...PROFILE_SET_RESPONSE,
      [field]: value,
    })).toBeNull()
  })

  it('never treats a provider-relative management path as a browser link', () => {
    expect(browserManagementLink('/knowledge/files')).toBeNull()
    expect(browserManagementLink('https://knowledge.example.com/manage')).toBe(
      'https://knowledge.example.com/manage',
    )
    expect(browserManagementLink('javascript:alert(1)')).toBeNull()
  })
})

describe('KnowledgeView workbench', () => {
  const IdleView = defineComponent({ render: () => h('div', 'idle') })
  let app: App | null = null
  let root: HTMLDivElement
  let active: Ref<boolean>
  let currentStatus: RagProviderStatus
  let mobileViewport: boolean

  function statusCallCount(): number {
    return rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.status').length
  }

  function configureDefaultRpc() {
    rpcMock.call.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.profile.set') {
        const value = params?.retrievalProfileOverride as string | null
        currentStatus = { ...currentStatus, retrievalProfileOverride: value }
        return {
          retrievalProfileOverride: value,
          providerDefaultRetrievalProfile:
            currentStatus.searchOptions?.defaultRetrievalProfile ?? null,
          effectiveRetrievalProfile:
            value ?? currentStatus.searchOptions?.defaultRetrievalProfile ?? null,
          restartRequired: false,
        }
      }
      if (method === 'knowledge.search') return structuredClone(SEARCH_RESPONSE)
      if (method === 'knowledge.get') {
        return { ...structuredClone(GET_RESPONSE), evidenceId: params?.evidenceId }
      }
      throw new Error(`unexpected method ${method}`)
    })
  }

  function mockMobile(matches: boolean) {
    mobileViewport = matches
  }

  function mountView() {
    const Host = defineComponent({
      setup() {
        return () => h(KeepAlive, null, {
          default: () => active.value ? h(KnowledgeView) : h(IdleView),
        })
      },
    })
    app = createApp(Host)
    app.use(i18n)
    app.mount(root)
  }

  async function deactivate() {
    active.value = false
    await nextTick()
  }

  async function reactivate() {
    active.value = true
    await nextTick()
  }

  beforeEach(() => {
    rpcMock.call.mockReset()
    rpcMock.waitForConnection.mockReset().mockResolvedValue(undefined)
    currentStatus = structuredClone(READY_STATUS)
    configureDefaultRpc()
    i18n.global.locale.value = 'en'
    window.history.replaceState(null, '', '/')
    mobileViewport = false
    vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: query === '(max-width: 900px)' ? mobileViewport : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList)
    active = ref(true)
    root = document.createElement('div')
    document.body.appendChild(root)
  })

  afterEach(() => {
    app?.unmount()
    app = null
    window.history.replaceState(null, '', '/')
    i18n.global.locale.value = 'en'
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('loads once per KeepAlive activation and pairs the popstate listener', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    mountView()
    await settle()

    expect(statusCallCount()).toBe(1)
    const popstateAdds = addSpy.mock.calls.filter(([event]) => event === 'popstate')
    expect(popstateAdds).toHaveLength(1)
    const listener = popstateAdds[0]?.[1]

    await deactivate()
    expect(statusCallCount()).toBe(1)
    expect(removeSpy).toHaveBeenCalledWith('popstate', listener)

    await reactivate()
    await settle()
    expect(statusCallCount()).toBe(2)
    expect(addSpy.mock.calls.filter(([event]) => event === 'popstate')).toHaveLength(2)

    const removesBeforeUnmount = removeSpy.mock.calls.filter(
      ([event]) => event === 'popstate',
    ).length
    app?.unmount()
    app = null
    expect(
      removeSpy.mock.calls.filter(([event]) => event === 'popstate').length,
    ).toBeGreaterThan(removesBeforeUnmount)
  })

  it('does not call status when a pending connection wait resolves after deactivation', async () => {
    const connection = deferred<void>()
    rpcMock.waitForConnection.mockReturnValue(connection.promise)
    mountView()
    await settle()
    expect(rpcMock.waitForConnection).toHaveBeenCalledTimes(1)
    expect(statusCallCount()).toBe(0)

    await deactivate()
    connection.resolve(undefined)
    await settle()
    expect(statusCallCount()).toBe(0)

    rpcMock.waitForConnection.mockResolvedValue(undefined)
    await reactivate()
    await settle()
    expect(statusCallCount()).toBe(1)
  })

  it('defers the status refresh after saving until the page is active again', async () => {
    const profileSet = deferred<typeof PROFILE_SET_RESPONSE>()
    rpcMock.call.mockImplementation((method: string) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.profile.set') return profileSet.promise
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.click()
    await nextTick()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')!.click()
    await settle()
    expect(statusCallCount()).toBe(1)

    await deactivate()
    profileSet.resolve(PROFILE_SET_RESPONSE)
    await settle()
    expect(statusCallCount()).toBe(1)

    currentStatus = { ...currentStatus, retrievalProfileOverride: 'vector' }
    await reactivate()
    await settle()
    expect(statusCallCount()).toBe(2)
  })

  it('ignores a stale status response after a newer activation response', async () => {
    const slowStatus = deferred<RagProviderStatus>()
    let request = 0
    rpcMock.call.mockImplementation((method: string) => {
      if (method !== 'knowledge.status') throw new Error(`unexpected method ${method}`)
      request += 1
      if (request === 1) return slowStatus.promise
      return {
        ...structuredClone(READY_STATUS),
        provider: { name: 'Fresh Provider', version: '2.0', instanceId: 'fresh' },
      }
    })
    mountView()
    await settle()
    expect(request).toBe(1)

    await deactivate()
    await reactivate()
    await settle()
    expect(request).toBe(2)
    expect(root.querySelector('[data-testid="rag-provider-name"]')?.textContent).toContain(
      'Fresh Provider',
    )

    slowStatus.resolve({
      ...structuredClone(READY_STATUS),
      provider: { name: 'Stale Provider', version: '0.9', instanceId: 'stale' },
    })
    await settle()
    expect(root.querySelector('[data-testid="rag-provider-name"]')?.textContent).toContain(
      'Fresh Provider',
    )
  })

  it('preserves a dirty profile through manual refresh and reactivation', async () => {
    mountView()
    await settle()
    root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.click()
    await nextTick()

    root.querySelector<HTMLButtonElement>('[data-testid="rag-refresh"]')!.click()
    await settle()
    expect(root.querySelector('[data-profile-id="vector"]')?.getAttribute('aria-checked')).toBe(
      'true',
    )

    await deactivate()
    await reactivate()
    await settle()
    expect(root.querySelector('[data-profile-id="vector"]')?.getAttribute('aria-checked')).toBe(
      'true',
    )
    expect(root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')?.disabled).toBe(
      false,
    )
    expect(rpcMock.call).not.toHaveBeenCalledWith('knowledge.profile.set', expect.anything())
  })

  it('saves a draft explicitly and refreshes stateful status without rolling it back', async () => {
    mountView()
    await settle()
    root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.click()
    await nextTick()
    expect(rpcMock.call).not.toHaveBeenCalledWith('knowledge.profile.set', expect.anything())

    root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')!.click()
    await settle()

    expect(rpcMock.call.mock.calls.map(([method]) => method)).toEqual([
      'knowledge.status',
      'knowledge.profile.set',
      'knowledge.status',
    ])
    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.profile.set', {
      retrievalProfileOverride: 'vector',
    })
    expect(root.querySelector('[data-profile-id="vector"]')?.getAttribute('aria-checked')).toBe(
      'true',
    )
    expect(root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')?.disabled).toBe(
      true,
    )
  })

  it('searches without an automatic Get, then reads selection and cursor pages on desktop', async () => {
    mockMobile(false)
    const pushSpy = vi.spyOn(window.history, 'pushState')
    mountView()
    await settle()
    await submitQuery(root, ' NAND capacity ')
    await settle()

    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.search', {
      query: 'NAND capacity',
      limit: 8,
    })
    expect(rpcMock.call).not.toHaveBeenCalledWith('knowledge.get', expect.anything())
    expect(pushSpy).not.toHaveBeenCalled()

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.get', { evidenceId: 'ev_a' })
    expect(pushSpy).not.toHaveBeenCalled()

    root.querySelector<HTMLButtonElement>('[data-testid="rag-next-segment"]')!.click()
    await settle()
    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.get', {
      evidenceId: 'ev_a',
      cursor: 'next-page',
    })
  })

  it('renders the Provider-executed Protocol 1.1 profile and complete Get window', async () => {
    currentStatus = {
      ...structuredClone(READY_STATUS),
      protocolVersion: '1.1',
      effectiveLimits: {
        ...structuredClone(READY_STATUS.effectiveLimits!),
        maxChunkChars: 4096,
      },
      searchOptions: {
        supportsCollectionScope: true,
        retrievalProfiles: [
          { id: 'selected-profile', label: 'Selected profile' },
          { id: 'provider-profile', label: 'Provider profile' },
        ],
        defaultRetrievalProfile: 'selected-profile',
      },
    }
    rpcMock.call.mockImplementation(async (method: string) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(V11_SEARCH_RESPONSE)
      if (method === 'knowledge.get') return structuredClone(V11_GET_RESPONSE)
      throw new Error(`unexpected method ${method}`)
    })
    i18n.global.mergeLocaleMessage('en', {
      rag: {
        results: {
          completeChunk: 'Complete chunk',
          chunkCharacters: '{count} characters',
          providerExecutedProfile: 'Provider executed profile: {profile}',
          fileName: 'File name',
          sourcePath: 'Source path',
        },
      },
    })

    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()

    expect(root.querySelector('.rag-result-card__title')?.textContent).toContain('nand.md')
    expect(root.textContent).toContain('NAND architecture')
    expect(root.textContent).toContain('Provider executed profile: provider-profile')
    expect(root.textContent).toContain('Complete chunk')
    expect(root.textContent).toContain('34 characters')

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_full"]')!.click()
    await settle()
    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.get', { evidenceId: 'ev_full' })
    expect(root.querySelector('.rag-reader .control-panel__title')?.textContent)
      .toContain('nand.md')
    expect(root.textContent).toContain('29 characters')
    expect(root.textContent).toContain('previous-page')
    expect(root.textContent).toContain('next-page')
  })

  it('does not read selections or cursor pages when Get capability is unavailable', async () => {
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.get')).toHaveLength(1)

    currentStatus = {
      ...currentStatus,
      capabilities: { search: true, get: false },
    }
    root.querySelector<HTMLButtonElement>('[data-testid="rag-refresh"]')!.click()
    await settle()

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-next-segment"]')!.click()
    await settle()
    expect(rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.get')).toHaveLength(1)
  })

  it.each([false, true])(
    'keeps the cached selection and history when Get becomes unavailable (mobile: %s)',
    async (mobile) => {
      mockMobile(mobile)
      const searchResponse = {
        ...structuredClone(SEARCH_RESPONSE),
        returnedCount: 2,
        results: [
          ...structuredClone(SEARCH_RESPONSE.results),
          {
            evidenceId: 'ev_b',
            snippet: 'Second evidence',
            snippetTruncated: false,
            citation: { title: 'Document B', locator: 'page 2' },
          },
        ],
      }
      rpcMock.call.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
        if (method === 'knowledge.status') return structuredClone(currentStatus)
        if (method === 'knowledge.search') return structuredClone(searchResponse)
        if (method === 'knowledge.get') {
          return {
            ...structuredClone(GET_RESPONSE),
            evidenceId: params?.evidenceId,
            content: 'Cached reader A',
          }
        }
        throw new Error(`unexpected method ${method}`)
      })
      mountView()
      await settle()
      await submitQuery(root, 'NAND capacity')
      await settle()
      root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
      await settle()

      currentStatus = {
        ...currentStatus,
        capabilities: { search: true, get: false },
      }
      root.querySelector<HTMLButtonElement>('[data-testid="rag-refresh"]')!.click()
      await settle()
      root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
      await settle()

      expect(rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.get')).toHaveLength(1)
      expect(root.querySelector('[data-evidence-id="ev_a"]')?.classList
        .contains('control-card--selected')).toBe(true)
      expect(root.querySelector('[data-evidence-id="ev_b"]')?.classList
        .contains('control-card--selected')).toBe(false)
      expect(root.textContent).toContain('Cached reader A')
      if (mobile) expect(window.history.state).toMatchObject({ ragReader: 'ev_a' })
      else expect(window.history.state?.ragReader).toBeUndefined()
    },
  )

  it('clears mismatched cached reader content while the next Get is pending', async () => {
    const getB = deferred<typeof GET_RESPONSE>()
    const searchResponse = {
      ...structuredClone(SEARCH_RESPONSE),
      returnedCount: 2,
      results: [
        ...structuredClone(SEARCH_RESPONSE.results),
        {
          evidenceId: 'ev_b',
          snippet: 'Second evidence',
          snippetTruncated: false,
          citation: { title: 'Document B', locator: 'page 2' },
        },
      ],
    }
    rpcMock.call.mockImplementation((method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(searchResponse)
      if (method === 'knowledge.get' && params?.evidenceId === 'ev_b') return getB.promise
      if (method === 'knowledge.get') {
        return { ...structuredClone(GET_RESPONSE), content: 'Cached reader A' }
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(root.textContent).toContain('Cached reader A')

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await settle()
    expect(root.textContent).toContain('Loading source text')
    expect(root.textContent).not.toContain('Cached reader A')
  })

  it('deduplicates an in-flight reader key without blocking a different evidence', async () => {
    const getA = deferred<typeof GET_RESPONSE>()
    const getB = deferred<typeof GET_RESPONSE>()
    const searchResponse = {
      ...structuredClone(SEARCH_RESPONSE),
      returnedCount: 2,
      results: [
        ...structuredClone(SEARCH_RESPONSE.results),
        {
          evidenceId: 'ev_b',
          snippet: 'Second evidence',
          snippetTruncated: false,
          citation: { title: 'Document B', locator: 'page 2' },
        },
      ],
    }
    rpcMock.call.mockImplementation((method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(searchResponse)
      if (method === 'knowledge.get') {
        return params?.evidenceId === 'ev_b' ? getB.promise : getA.promise
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await nextTick()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await nextTick()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_a',
    )).toHaveLength(1)

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await nextTick()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(1)

    getA.resolve({ ...structuredClone(GET_RESPONSE), content: 'Stale reader A' })
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await nextTick()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(1)

    getB.resolve({
      ...structuredClone(GET_RESPONSE),
      evidenceId: 'ev_b',
      content: 'Reader B',
    })
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await settle()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(2)
  })

  it('allows the same reader key to retry after its failure settles', async () => {
    const firstGet = deferred<typeof GET_RESPONSE>()
    let getAttempts = 0
    rpcMock.call.mockImplementation((method: string) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(SEARCH_RESPONSE)
      if (method === 'knowledge.get') {
        getAttempts += 1
        return getAttempts === 1 ? firstGet.promise : structuredClone(GET_RESPONSE)
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await nextTick()

    firstGet.reject(new Error('reader failed once'))
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(getAttempts).toBe(2)
    expect(root.textContent).toContain('Normalized source text')
  })

  it('keeps the latest reader response when an earlier Get resolves later', async () => {
    const getA = deferred<typeof GET_RESPONSE>()
    const getB = deferred<typeof GET_RESPONSE>()
    const searchResponse = {
      ...structuredClone(SEARCH_RESPONSE),
      returnedCount: 2,
      results: [
        ...structuredClone(SEARCH_RESPONSE.results),
        {
          evidenceId: 'ev_b',
          snippet: 'Second evidence',
          snippetTruncated: false,
          citation: { title: 'Document B', locator: 'page 2' },
        },
      ],
    }
    rpcMock.call.mockImplementation((method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(searchResponse)
      if (method === 'knowledge.get') {
        return params?.evidenceId === 'ev_b' ? getB.promise : getA.promise
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await settle()

    getB.resolve({
      ...structuredClone(GET_RESPONSE),
      evidenceId: 'ev_b',
      document: { title: 'Document B', source: 'datasets' },
      content: 'Latest reader B',
    })
    await settle()
    expect(root.textContent).toContain('Latest reader B')

    getA.resolve({ ...structuredClone(GET_RESPONSE), content: 'Stale reader A' })
    await settle()
    expect(root.textContent).toContain('Latest reader B')
    expect(root.textContent).not.toContain('Stale reader A')
  })

  it.each(['resolve', 'reject'] as const)(
    'does not restore an in-flight Get %s after a successful new search',
    async (outcome) => {
      const pendingGet = deferred<typeof GET_RESPONSE>()
      rpcMock.call.mockImplementation((method: string) => {
        if (method === 'knowledge.status') return structuredClone(currentStatus)
        if (method === 'knowledge.search') return structuredClone(SEARCH_RESPONSE)
        if (method === 'knowledge.get') return pendingGet.promise
        throw new Error(`unexpected method ${method}`)
      })
      mountView()
      await settle()
      await submitQuery(root, 'NAND capacity')
      await settle()
      root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
      await settle()

      await submitQuery(root, 'fresh search')
      await settle()
      expect(root.textContent).not.toContain('Loading source text')

      if (outcome === 'resolve') {
        pendingGet.resolve({ ...structuredClone(GET_RESPONSE), content: 'Stale reader content' })
      } else {
        pendingGet.reject(new Error('stale reader failed'))
      }
      await settle()
      expect(root.textContent).not.toContain('Stale reader content')
      expect(root.textContent).not.toContain('stale reader failed')
      expect(root.querySelector('[data-testid="rag-reader-error"]')).toBeNull()
    },
  )

  it('keeps profile, search, and reader errors in independent domains', async () => {
    let searchFails = false
    rpcMock.call.mockImplementation(async (method: string) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.profile.set') throw new Error('profile failed')
      if (method === 'knowledge.search') {
        if (searchFails) throw new Error('search failed')
        return structuredClone(SEARCH_RESPONSE)
      }
      if (method === 'knowledge.get') throw new Error('reader failed')
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()

    root.querySelector<HTMLButtonElement>('[data-profile-id="vector"]')!.click()
    await nextTick()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-profile-save"]')!.click()
    await settle()
    expect(root.textContent).toContain('profile failed')

    await submitQuery(root, 'NAND capacity')
    await settle()
    searchFails = true
    await submitQuery(root, 'NAND capacity')
    await settle()
    expect(root.textContent).toContain('profile failed')
    expect(root.textContent).toContain('search failed')

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(root.textContent).toContain('profile failed')
    expect(root.textContent).toContain('search failed')
    expect(root.textContent).toContain('reader failed')
  })

  it('renders only absolute provider management links', async () => {
    mountView()
    await settle()
    const management = root.querySelector<HTMLAnchorElement>(
      'a[href="https://knowledge.example.com/manage"]',
    )
    expect(management?.target).toBe('_blank')
    expect(management?.rel).toBe('noopener noreferrer')

    app?.unmount()
    app = null
    currentStatus = {
      ...structuredClone(READY_STATUS),
      links: { management: '/knowledge/files' },
    }
    configureDefaultRpc()
    mountView()
    await settle()
    expect(root.querySelector('a[href="/knowledge/files"]')).toBeNull()
    expect(root.textContent).toContain('local-only management path')
  })

  it('uses production English messages without leaking rag keys', async () => {
    mountView()
    await settle()
    expect(root.textContent).toContain('Knowledge search')
    expect(root.textContent).toContain('Default retrieval method')
    expect(root.textContent).toContain('Provider connection and protocol details')

    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(root.textContent).toContain('1 returned')
    expect(root.querySelector('[aria-label="Source reader"]')).not.toBeNull()
    expect(root.textContent).not.toContain('rag.')
  })

  it('closes the mobile history loop across push, replace, close, and popstate', async () => {
    mockMobile(true)
    const searchResponse = {
      ...structuredClone(SEARCH_RESPONSE),
      returnedCount: 2,
      results: [
        ...structuredClone(SEARCH_RESPONSE.results),
        {
          evidenceId: 'ev_b',
          snippet: 'Second evidence',
          snippetTruncated: false,
          citation: { title: 'Document B', locator: 'page 2' },
        },
      ],
    }
    rpcMock.call.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(searchResponse)
      if (method === 'knowledge.get') {
        const evidenceId = String(params?.evidenceId)
        return {
          ...structuredClone(GET_RESPONSE),
          evidenceId,
          document: { title: evidenceId === 'ev_b' ? 'Document B' : 'Document A', source: 'datasets' },
        }
      }
      throw new Error(`unexpected method ${method}`)
    })
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(window.history.state).toMatchObject({ ragReader: 'ev_a' })
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)

    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_b"]')!.click()
    await settle()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(replaceSpy).toHaveBeenCalledWith(expect.objectContaining({ ragReader: 'ev_b' }), '')

    const close = root.querySelector<HTMLButtonElement>('.rag-reader__back')!
    close.click()
    close.click()
    await nextTick()
    expect(backSpy).toHaveBeenCalledTimes(1)
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(false)

    window.dispatchEvent(new PopStateEvent('popstate', { state: { ragReader: 'ev_b' } }))
    await nextTick()
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)
    window.dispatchEvent(new PopStateEvent('popstate', { state: null }))
    await nextTick()
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(false)
  })

  it('deduplicates repeated mobile markers while their reader request is pending', async () => {
    mockMobile(true)
    const pendingGet = deferred<typeof GET_RESPONSE>()
    rpcMock.call.mockImplementation((method: string) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.get') return pendingGet.promise
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()

    window.dispatchEvent(new PopStateEvent('popstate', { state: { ragReader: 'ev_a' } }))
    await nextTick()
    window.dispatchEvent(new PopStateEvent('popstate', { state: { ragReader: 'ev_a' } }))
    await nextTick()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_a',
    )).toHaveLength(1)
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)
  })

  it('consumes a mobile reader marker when a new search returns results', async () => {
    mockMobile(true)
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()

    await submitQuery(root, 'fresh search')
    await settle()
    expect(backSpy).toHaveBeenCalledTimes(1)
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(false)
  })

  it('reads an initial mobile marker once after async status confirms Get capability', async () => {
    mockMobile(true)
    window.history.replaceState({ ragReader: 'ev_b' }, '')
    const statusResponse = deferred<RagProviderStatus>()
    rpcMock.call.mockImplementation((method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return statusResponse.promise
      if (method === 'knowledge.get') {
        return {
          ...structuredClone(GET_RESPONSE),
          evidenceId: params?.evidenceId,
          document: { title: 'Document B', source: 'datasets' },
          content: 'Initial marker B',
        }
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    expect(rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.get')).toHaveLength(0)

    statusResponse.resolve(structuredClone(READY_STATUS))
    await settle()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(1)
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)
    expect(root.textContent).toContain('Initial marker B')
  })

  it('keeps an initial mobile marker closed when async status disables Get capability', async () => {
    mockMobile(true)
    window.history.replaceState({ ragReader: 'ev_b' }, '')
    const statusResponse = deferred<RagProviderStatus>()
    rpcMock.call.mockImplementation((method: string) => {
      if (method === 'knowledge.status') return statusResponse.promise
      if (method === 'knowledge.get') return structuredClone(GET_RESPONSE)
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()

    statusResponse.resolve({
      ...structuredClone(READY_STATUS),
      capabilities: { search: true, get: false },
    })
    await settle()
    expect(rpcMock.call.mock.calls.filter(([method]) => method === 'knowledge.get')).toHaveLength(0)
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(false)
    expect(root.querySelector('[data-evidence-id="ev_b"]')?.classList
      .contains('control-card--selected')).not.toBe(true)
  })

  it('syncs a changed mobile marker on activation and only reads when cache differs', async () => {
    mockMobile(true)
    const searchResponse = {
      ...structuredClone(SEARCH_RESPONSE),
      returnedCount: 2,
      results: [
        ...structuredClone(SEARCH_RESPONSE.results),
        {
          evidenceId: 'ev_b',
          snippet: 'Second evidence',
          snippetTruncated: false,
          citation: { title: 'Document B', locator: 'page 2' },
        },
      ],
    }
    rpcMock.call.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'knowledge.status') return structuredClone(currentStatus)
      if (method === 'knowledge.search') return structuredClone(searchResponse)
      if (method === 'knowledge.get') {
        const evidenceId = String(params?.evidenceId)
        return {
          ...structuredClone(GET_RESPONSE),
          evidenceId,
          document: { title: evidenceId === 'ev_b' ? 'Document B' : 'Document A', source: 'datasets' },
        }
      }
      throw new Error(`unexpected method ${method}`)
    })
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(root.querySelector('[data-evidence-id="ev_a"]')?.classList
      .contains('control-card--selected')).toBe(true)

    await deactivate()
    window.history.replaceState({ ragReader: 'ev_b' }, '')
    await reactivate()
    await settle()
    expect(root.querySelector('[data-evidence-id="ev_b"]')?.classList
      .contains('control-card--selected')).toBe(true)
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(1)

    await deactivate()
    await reactivate()
    await settle()
    expect(rpcMock.call.mock.calls.filter(
      ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
    )).toHaveLength(1)
  })

  it.each(['resolve', 'reject'] as const)(
    'clears mismatched reader content and error before reactivation status can %s',
    async (statusOutcome) => {
      mockMobile(true)
      const statusResponse = deferred<RagProviderStatus>()
      let statusCalls = 0
      const searchResponse = {
        ...structuredClone(SEARCH_RESPONSE),
        returnedCount: 2,
        results: [
          ...structuredClone(SEARCH_RESPONSE.results),
          {
            evidenceId: 'ev_b',
            snippet: 'Second evidence',
            snippetTruncated: false,
            citation: { title: 'Document B', locator: 'page 2' },
          },
        ],
      }
      rpcMock.call.mockImplementation((method: string, params?: Record<string, unknown>) => {
        if (method === 'knowledge.status') {
          statusCalls += 1
          return statusCalls === 1 ? structuredClone(currentStatus) : statusResponse.promise
        }
        if (method === 'knowledge.search') return structuredClone(searchResponse)
        if (method === 'knowledge.get' && params?.evidenceId === 'ev_b') {
          return {
            ...structuredClone(GET_RESPONSE),
            evidenceId: 'ev_b',
            content: 'Reader B',
          }
        }
        if (method === 'knowledge.get' && params?.cursor) throw new Error('Reader A failed')
        if (method === 'knowledge.get') {
          return { ...structuredClone(GET_RESPONSE), content: 'Cached reader A' }
        }
        throw new Error(`unexpected method ${method}`)
      })
      mountView()
      await settle()
      await submitQuery(root, 'NAND capacity')
      await settle()
      root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
      await settle()
      root.querySelector<HTMLButtonElement>('[data-testid="rag-next-segment"]')!.click()
      await settle()
      expect(root.textContent).toContain('Cached reader A')
      expect(root.textContent).toContain('Reader A failed')

      await deactivate()
      window.history.replaceState({ ragReader: 'ev_b' }, '')
      await reactivate()
      await settle()
      expect(root.querySelector('[data-evidence-id="ev_b"]')?.classList
        .contains('control-card--selected')).toBe(true)
      expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)
      expect(root.textContent).not.toContain('Cached reader A')
      expect(root.textContent).not.toContain('Reader A failed')
      expect(rpcMock.call.mock.calls.filter(
        ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
      )).toHaveLength(0)

      if (statusOutcome === 'resolve') statusResponse.resolve(structuredClone(currentStatus))
      else statusResponse.reject(new Error('status refresh failed'))
      await settle()
      expect(root.textContent).not.toContain('Cached reader A')
      expect(root.textContent).not.toContain('Reader A failed')
      expect(rpcMock.call.mock.calls.filter(
        ([method, params]) => method === 'knowledge.get' && params?.evidenceId === 'ev_b',
      )).toHaveLength(statusOutcome === 'resolve' ? 1 : 0)
      if (statusOutcome === 'resolve') expect(root.textContent).toContain('Reader B')
      else expect(root.textContent).not.toContain('Reader B')
    },
  )

  it('clears cached mobile state on deactivation and re-syncs it on activation', async () => {
    mockMobile(true)
    mountView()
    await settle()
    await submitQuery(root, 'NAND capacity')
    await settle()
    root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!.click()
    await settle()
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)

    await deactivate()
    await reactivate()
    await settle()
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(true)

    await deactivate()
    window.history.replaceState(null, '', '/')
    await reactivate()
    await settle()
    expect(root.querySelector('.rag-workspace')?.classList.contains('is-reader-open')).toBe(false)
  })
})
