// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive, type App } from 'vue'
import i18n from '@/i18n'
import KnowledgeSearchWorkspace from './KnowledgeSearchWorkspace.vue'
import KnowledgeProviderDetails from './KnowledgeProviderDetails.vue'
import type {
  RagGetResponse,
  RagProviderStatus,
  RagSearchResponse,
} from '@/views/ragProvider'

const SEARCH_RESPONSE: RagSearchResponse = {
  returnedCount: 1,
  totalMatched: 9,
  resultsTruncated: true,
  providerBudgetViolation: true,
  retrievalProfile: null,
  results: [{
    evidenceId: 'ev_a',
    rank: null,
    document: null,
    chunk: null,
    snippet: 'NAND evidence',
    snippetTruncated: true,
    citation: { title: 'Document A', locator: 'page 1' },
  }],
}

const GET_RESPONSE: RagGetResponse = {
  evidenceId: 'ev_a',
  document: { title: 'Document A', source: 'datasets' },
  content: 'Normalized source text',
  contentChars: null,
  previousCursor: null,
  nextCursor: 'next-page',
  citation: { title: 'Document A', locator: 'page 1' },
  legacyLimitedGet: false,
}

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
    retrievalProfiles: [{ id: 'hybrid', label: 'Hybrid' }],
    defaultRetrievalProfile: 'hybrid',
  },
  links: {},
  lastSuccessAt: 1_700_000_000,
  lastErrorCode: null,
  consecutiveFailures: 0,
  retrievalProfileOverride: null,
  effectiveRetrievalProfile: 'hybrid',
  collectionScope: ['datasets', 'manuals'],
  legacyConfigPresent: false,
  legacyAdapterEnabled: false,
  warning: null,
}

interface WorkspaceProps {
  query: string
  limit: number
  canSearch: boolean
  searching: boolean
  searchError: string
  searchResponse: RagSearchResponse | null
  selectedEvidenceId: string | null
  getResponse: RagGetResponse | null
  reading: boolean
  readError: string
  mobileReaderOpen: boolean
  expectedRetrievalProfile: string | null
}

const mountedApps: App[] = []

async function mountWorkspace(overrides: Partial<WorkspaceProps> = {}) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  const props = reactive<WorkspaceProps>({
    query: 'NAND capacity',
    limit: 8,
    canSearch: true,
    searching: false,
    searchError: '',
    searchResponse: null,
    selectedEvidenceId: null,
    getResponse: null,
    reading: false,
    readError: '',
    mobileReaderOpen: false,
    expectedRetrievalProfile: null,
    ...overrides,
  })
  const onUpdateQuery = vi.fn()
  const onUpdateLimit = vi.fn()
  const onSearch = vi.fn()
  const onSelect = vi.fn()
  const onPage = vi.fn()
  const onCloseReader = vi.fn()
  const app = createApp({
    render: () => h(KnowledgeSearchWorkspace, {
      ...props,
      'onUpdate:query': onUpdateQuery,
      'onUpdate:limit': onUpdateLimit,
      onSearch,
      onSelect,
      onPage,
      onCloseReader,
    }),
  })
  app.use(i18n)
  app.mount(root)
  mountedApps.push(app)
  await nextTick()
  return {
    root,
    props,
    onUpdateQuery,
    onUpdateLimit,
    onSearch,
    onSelect,
    onPage,
    onCloseReader,
  }
}

async function mountDetails(status: RagProviderStatus | null) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  const app = createApp(KnowledgeProviderDetails, { status })
  app.use(i18n)
  app.mount(root)
  mountedApps.push(app)
  await nextTick()
  return root
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  i18n.global.mergeLocaleMessage('en', {
    rag: {
      search: {
        title: 'Search knowledge',
        placeholder: 'Enter a question, topic, company, product, or event…',
        advanced: 'Advanced options',
        limit: 'Results to return',
        submit: 'Search',
        searching: 'Searching',
      },
      results: {
        title: 'Results',
        returned: '{count} returned',
        matched: '{count} matched',
        truncated: 'Results truncated',
        budgetTrimmed: 'Trimmed to the OpenSquilla budget',
        snippetTruncated: 'Snippet truncated',
        completeChunk: 'Complete chunk',
        chunkCharacters: '{count} characters',
        providerExecutedProfile: 'Provider executed profile',
        fileName: 'File name',
        sourcePath: 'Source path',
        empty: 'Search the knowledge base to see citable evidence.',
      },
      reader: {
        title: 'Source reader',
        empty: 'Select a result to read its source text.',
        loading: 'Loading source text',
        backToResults: 'Back to results',
        previous: 'Previous segment',
        next: 'Next segment',
        legacyLimited: 'Compatibility mode only guarantees nearby text.',
      },
      details: {
        title: 'Provider connection and protocol details',
        connection: 'Connection',
        protocol: 'Protocol capabilities',
        budgets: 'Response budgets',
      },
    },
  })
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('KnowledgeSearchWorkspace', () => {
  it('submits with command-enter and does not select a result automatically', async () => {
    const { root, onSearch, onSelect } = await mountWorkspace({
      searchResponse: SEARCH_RESPONSE,
    })
    const query = root.querySelector<HTMLTextAreaElement>('[data-testid="rag-query"]')!
    query.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter',
      metaKey: true,
      bubbles: true,
    }))
    await nextTick()
    expect(onSearch).toHaveBeenCalledTimes(1)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('selects the result card and pages by cursor', async () => {
    const { root, onSelect, onPage } = await mountWorkspace({
      searchResponse: SEARCH_RESPONSE,
      selectedEvidenceId: 'ev_a',
      getResponse: GET_RESPONSE,
    })
    const card = root.querySelector<HTMLButtonElement>('[data-evidence-id="ev_a"]')!
    card.click()
    root.querySelector<HTMLButtonElement>('[data-testid="rag-next-segment"]')!.click()
    await nextTick()
    expect(card.querySelector('button')).toBeNull()
    expect(onSelect).toHaveBeenCalledWith('ev_a')
    expect(onPage).toHaveBeenCalledWith('ev_a', 'next-page')
  })

  it('keeps search and reader errors in their own regions', async () => {
    const { root } = await mountWorkspace({
      searchError: 'search failed',
      readError: 'read failed',
    })
    expect(root.querySelector('[data-testid="rag-search-error"]')?.textContent)
      .toContain('search failed')
    expect(root.querySelector('[data-testid="rag-reader-error"]')?.textContent)
      .toContain('read failed')
  })

  it('emits query and limit drafts without searching', async () => {
    const { root, onUpdateQuery, onUpdateLimit, onSearch } = await mountWorkspace()
    const query = root.querySelector<HTMLTextAreaElement>('[data-testid="rag-query"]')!
    query.value = 'new query'
    query.dispatchEvent(new Event('input', { bubbles: true }))
    const limit = root.querySelector<HTMLInputElement>('input[type="number"]')!
    limit.value = '12'
    limit.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    expect(onUpdateQuery).toHaveBeenCalledWith('new query')
    expect(onUpdateLimit).toHaveBeenCalledWith(12)
    expect(onSearch).not.toHaveBeenCalled()
  })

  it('returns reader content to the top when a page changes', async () => {
    const { root, props } = await mountWorkspace({ getResponse: GET_RESPONSE })
    const reader = root.querySelector<HTMLElement>('.rag-reader')!
    const content = root.querySelector<HTMLElement>('.rag-reader__content')!
    reader.scrollTop = 80
    props.getResponse = { ...GET_RESPONSE, content: 'Second page' }
    await nextTick()
    await nextTick()
    expect(reader.scrollTop).toBe(0)
    expect(content.textContent).toContain('Second page')
  })

  it('closes the mobile reader only through its explicit action', async () => {
    const { root, onCloseReader, onSearch } = await mountWorkspace({
      getResponse: GET_RESPONSE,
      mobileReaderOpen: true,
    })
    root.querySelector<HTMLButtonElement>('.rag-reader__back')!.click()
    await nextTick()
    expect(onCloseReader).toHaveBeenCalledTimes(1)
    expect(onSearch).not.toHaveBeenCalled()
  })

  it('renders Protocol 1.1 identity compactly and expands the complete chunk explicitly', async () => {
    const content = 'Complete normalized NAND evidence.'
    const response: RagSearchResponse = {
      returnedCount: 1,
      totalMatched: null,
      resultsTruncated: false,
      providerBudgetViolation: false,
      retrievalProfile: 'provider-actual',
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
    const { root } = await mountWorkspace({
      searchResponse: response,
      expectedRetrievalProfile: 'selected-profile',
    })

    const result = root.querySelector<HTMLElement>('[data-result-id="ev_full"]')!
    expect(result.querySelector('.rag-result-card__title')?.textContent).toContain('nand.md')
    expect(result.querySelector('.rag-result-card__document-title')?.textContent)
      .toContain('NAND architecture')
    expect(result.textContent).toContain('datasets/nand.md')
    expect(result.textContent).toContain('datasets')
    expect(result.textContent).toContain('#1')
    expect(result.textContent).toContain('section 2')
    const executedProfile = root.querySelector<HTMLElement>(
      '[data-testid="rag-executed-profile"]',
    )
    expect(executedProfile?.textContent).toContain('Provider executed profile')
    expect(executedProfile?.querySelector('code')?.textContent).toBe('provider-actual')
    expect(executedProfile?.classList.contains('control-pill--warn')).toBe(true)
    expect(root.querySelector('a[href="javascript:alert(1)"]')).toBeNull()

    const complete = result.querySelector<HTMLDetailsElement>('[data-testid="rag-complete-chunk"]')!
    expect(complete.open).toBe(false)
    expect(complete.querySelector('summary')?.textContent).toContain('Complete chunk')
    expect(complete.textContent).toContain(`${content.length} characters`)
    complete.querySelector<HTMLElement>('summary')!.click()
    await nextTick()
    expect(complete.open).toBe(true)
    expect(complete.textContent).toContain(content)
  })

  it('renders full Get document metadata, character count, and cursor values', async () => {
    const content = 'Complete paged NAND evidence.'
    const response: RagGetResponse = {
      evidenceId: 'ev_full',
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
      content,
      contentChars: content.length,
      previousCursor: 'previous-page',
      nextCursor: 'next-page',
      citation: {
        title: 'NAND architecture',
        source: 'datasets',
        locator: 'section 2',
        uri: 'knowledge://documents/doc_a#chunk=chunk_a',
      },
      legacyLimitedGet: false,
    }
    const { root } = await mountWorkspace({ getResponse: response })

    expect(root.querySelector('.rag-reader .control-panel__title')?.textContent)
      .toContain('nand.md')
    expect(root.textContent).toContain('NAND architecture')
    expect(root.textContent).toContain('File name')
    expect(root.textContent).toContain('datasets/nand.md')
    expect(root.textContent).toContain(`${content.length} characters`)
    expect(root.textContent).toContain('previous-page')
    expect(root.textContent).toContain('next-page')
  })
})

describe('KnowledgeProviderDetails', () => {
  it('renders connection, protocol, and response-budget values from status', async () => {
    const root = await mountDetails(READY_STATUS)
    expect(root.textContent).toContain('Connection')
    expect(root.textContent).toContain('Protocol capabilities')
    expect(root.textContent).toContain('Response budgets')
    expect(root.textContent).toContain('OpenSquilla-Knowledge')
    expect(root.textContent).toContain('preview')
    expect(root.textContent).toContain('datasets, manuals')
    expect(root.textContent).toContain('12000')
    expect(root.textContent).toContain('maxChunkChars')
  })

  it('uses only placeholder values when no provider status is available', async () => {
    const root = await mountDetails(null)
    expect(root.querySelector('details')).not.toBeNull()
    const values = Array.from(root.querySelectorAll('dd'), item => item.textContent?.trim())
    expect(values.length).toBe(15)
    expect(values.every(value => value === '—')).toBe(true)
  })
})
