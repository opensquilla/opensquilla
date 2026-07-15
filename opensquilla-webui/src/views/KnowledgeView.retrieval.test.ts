// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick, type App } from 'vue'

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
  },
  searchOptions: {
    supportsCollectionScope: true,
    retrievalProfiles: [{ id: 'hybrid', label: 'Hybrid' }],
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

const GET_RESPONSE = {
  evidenceId: 'ev_a',
  document: { title: 'Document A', source: 'datasets' },
  content: 'Normalized source text',
  previousCursor: null,
  nextCursor: 'next-page',
  citation: { title: 'Document A', locator: 'page 1' },
}

async function settle() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

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

  it('requires returnedCount to match the actual search array', () => {
    expect(normalizeRagSearchResponse(SEARCH_RESPONSE)?.results).toHaveLength(1)
    expect(normalizeRagSearchResponse({ ...SEARCH_RESPONSE, returnedCount: 20 })).toBeNull()
    expect(normalizeRagSearchResponse({ ...SEARCH_RESPONSE, providerBudgetViolation: 'false' })).toBeNull()
  })

  it('validates get cursors and normalized document content', () => {
    expect(normalizeRagGetResponse(GET_RESPONSE)?.nextCursor).toBe('next-page')
    expect(normalizeRagGetResponse({ ...GET_RESPONSE, nextCursor: 1 })).toBeNull()
    expect(normalizeRagGetResponse({ ...GET_RESPONSE, content: null })).toBeNull()
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

describe('KnowledgeView Provider console', () => {
  let app: App | null = null
  let root: HTMLDivElement

  beforeEach(() => {
    rpcMock.call.mockReset()
    rpcMock.waitForConnection.mockReset().mockResolvedValue(undefined)
    rpcMock.call.mockImplementation((method: string) => {
      if (method === 'knowledge.status') return READY_STATUS
      if (method === 'knowledge.search') return SEARCH_RESPONSE
      if (method === 'knowledge.get') return GET_RESPONSE
      throw new Error(`unexpected method ${method}`)
    })
    root = document.createElement('div')
    document.body.appendChild(root)
    app = createApp(KnowledgeView)
    app.mount(root)
  })

  afterEach(() => {
    app?.unmount()
    app = null
    document.body.innerHTML = ''
  })

  it('shows status and removes Provider-management controls from OpenSquilla', async () => {
    await settle()

    expect(root.querySelector('[data-testid="rag-state"]')?.textContent).toContain('READY')
    expect(root.textContent).toContain('打开 Provider 管理页面')
    expect(root.textContent).not.toContain('构建知识库')
    expect(root.textContent).not.toContain('Collection ingest')
    expect(root.textContent).not.toContain('Golden queries')
    expect(root.textContent).not.toContain('BM25')
  })

  it('sends only query and limit, then reads by evidenceId and cursor', async () => {
    await settle()
    const query = root.querySelector<HTMLTextAreaElement>('[data-testid="rag-query"]')!
    query.value = ' NAND capacity '
    query.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-search"]')!.click()
    await settle()

    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.search', {
      query: 'NAND capacity',
      limit: 8,
    })
    expect(root.textContent).toContain('Document A')

    const read = Array.from(root.querySelectorAll('button')).find(button => button.textContent?.includes('读取原文'))!
    read.click()
    await settle()

    expect(rpcMock.call).toHaveBeenCalledWith('knowledge.get', { evidenceId: 'ev_a' })
    expect(root.querySelector('[data-testid="rag-content"]')?.textContent).toContain('Normalized source text')
  })
})
