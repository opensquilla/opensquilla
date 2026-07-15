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
  results: [{
    evidenceId: 'ev_a',
    snippet: 'NAND evidence',
    snippetTruncated: true,
    citation: { title: 'Document A', locator: 'page 1' },
  }],
}

const GET_RESPONSE: RagGetResponse = {
  evidenceId: 'ev_a',
  document: { title: 'Document A', source: 'datasets' },
  content: 'Normalized source text',
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
  })

  it('uses only placeholder values when no provider status is available', async () => {
    const root = await mountDetails(null)
    expect(root.querySelector('details')).not.toBeNull()
    const values = Array.from(root.querySelectorAll('dd'), item => item.textContent?.trim())
    expect(values.length).toBe(14)
    expect(values.every(value => value === '—')).toBe(true)
  })
})
