import { describe, expect, it } from 'vitest'
import { sourceStableKey, toSources } from './toSources'
import type { ChatRenderedMessage, ChatToolCall } from '@/types/chat'
import type { SourcePart } from '@/types/parts'
import { toolActionLabel, toolOperationKey } from './toolDisplay'

function baseCall(overrides: Partial<ChatToolCall>): ChatToolCall {
  return {
    toolId: 'tool-1',
    name: 'web_search',
    displayName: 'Web search',
    inputPreview: '',
    isRunning: false,
    status: 'success',
    isError: false,
    result: '',
    resultPreview: '',
    isOpen: false,
    ...overrides,
  }
}

function message(toolCalls: ChatToolCall[]): ChatRenderedMessage {
  return {
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: '',
    timeStr: '',
    showHeader: false,
    toolCalls,
  }
}

describe('toSources', () => {
  it('preserves source trust metadata and merges duplicate URLs', () => {
    const sources = toSources(message([
      baseCall({
        sources: [
          {
            url: 'https://example.com/a',
            canonical_url: 'https://example.com/a',
            provider: 'duckduckgo',
            fetched: false,
            fetch_status: 'not_requested',
          },
          {
            url: 'https://example.com/a#section',
            title: 'Example result',
            provider: 'duckduckgo',
            fetched: true,
            fetch_status: 'ok',
          },
        ],
      }),
    ]))

    expect(sources).toEqual([
      {
        kind: 'web',
        sourceId: 1,
        url: 'https://example.com/a',
        title: 'Example result',
        domain: 'example.com',
        canonicalUrl: 'https://example.com/a',
        provider: 'duckduckgo',
        fetched: true,
        fetchStatus: 'ok',
      },
    ])
  })

  it('upgrades duplicate source metadata when a later entry is verified', () => {
    const sources = toSources(message([
      baseCall({
        sources: [
          {
            url: 'https://example.com/a',
            title: 'Initial result',
            provider: 'duckduckgo',
            fetched: false,
            fetch_status: 'fetch_failed',
          },
          {
            url: 'https://example.com/a',
            provider: 'duckduckgo',
            fetched: true,
            fetch_status: 'ok',
          },
        ],
      }),
    ]))

    expect(sources[0]).toMatchObject({
      kind: 'web',
      url: 'https://example.com/a',
      title: 'Initial result',
      fetched: true,
      fetchStatus: 'ok',
    })
  })

  it('maps only structured Knowledge search/get sidecars and never result JSON', () => {
    const sources = toSources(message([
      baseCall({
        toolId: 'search',
        name: 'knowledge_search',
        result: JSON.stringify({
          results: [{
            evidenceId: 'result-only',
            chunk: { content: 'FULL MODEL RESULT MUST NOT BE RECOVERED' },
          }],
        }),
        sources: [{
          kind: 'knowledge',
          evidenceId: 'ev_search',
          rank: 1,
          document: {
            id: 'doc_search',
            title: 'NAND handbook',
            fileName: 'nand.md',
            sourcePath: 'datasets/nand.md',
            source: 'datasets',
            mediaType: 'text/markdown',
            revision: 'sha256:one',
            uri: 'knowledge://documents/doc_search',
            openUrl: '/knowledge/files/doc_search?chunkId=chunk_1',
          },
          citation: {
            title: 'NAND citation',
            locator: 'page 7',
            uri: 'knowledge://documents/doc_search#chunk=chunk_1',
          },
          snippet: 'bounded search evidence',
          snippetTruncated: false,
          chunk: { content: 'MUST BE DROPPED' },
          content: 'MUST ALSO BE DROPPED',
        }],
      }),
      baseCall({
        toolId: 'get',
        name: 'knowledge_get',
        result: JSON.stringify({ content: 'FULL GET RESULT MUST NOT BE RECOVERED' }),
        sources: [{
          kind: 'knowledge',
          evidenceId: 'ev_get',
          document: {
            id: 'doc_get',
            title: 'Get document',
          },
          citation: { title: 'Get citation', locator: 'section 2' },
          snippet: 'bounded get evidence',
          snippetTruncated: false,
        }],
      }),
      baseCall({
        toolId: 'fake',
        name: 'knowledge_search_preview',
        sources: [{
          kind: 'knowledge',
          evidenceId: 'must-not-map',
          citation: { title: 'Wrong tool' },
          snippet: 'wrong',
        }],
      }),
    ]))

    expect(sources).toHaveLength(2)
    expect(sources[0]).toMatchObject({
      kind: 'knowledge',
      sourceId: 1,
      evidenceId: 'ev_search',
      rank: 1,
      title: 'nand.md',
      documentTitle: 'NAND handbook',
      url: '/knowledge/files/doc_search?chunkId=chunk_1',
      documentId: 'doc_search',
      fileName: 'nand.md',
      sourcePath: 'datasets/nand.md',
      source: 'datasets',
      mediaType: 'text/markdown',
      revision: 'sha256:one',
      documentUri: 'knowledge://documents/doc_search',
      citationTitle: 'NAND citation',
      citationUri: 'knowledge://documents/doc_search#chunk=chunk_1',
      locator: 'page 7',
      snippet: 'bounded search evidence',
      snippetTruncated: false,
    })
    expect(sources[1]).toMatchObject({
      kind: 'knowledge',
      sourceId: 2,
      evidenceId: 'ev_get',
      title: 'Get document',
      locator: 'section 2',
      snippet: 'bounded get evidence',
    })
    expect(JSON.stringify(sources)).not.toContain('FULL MODEL RESULT')
    expect(JSON.stringify(sources)).not.toContain('FULL GET RESULT')
    expectNoChunkOrContent(sources)
  })

  it('does not reconstruct Web or Knowledge sources from model result JSON', () => {
    const sources = toSources(message([
      baseCall({
        name: 'web_search',
        sources: [],
        result: JSON.stringify({
          sources: [{ url: 'https://result.example/hidden', title: 'Hidden Web result' }],
        }),
      }),
      baseCall({
        name: 'knowledge_search',
        sources: [],
        result: JSON.stringify({
          results: [{
            evidenceId: 'hidden',
            chunk: { content: 'full chunk' },
          }],
        }),
      }),
    ]))

    expect(sources).toEqual([])
  })

  it('keeps Knowledge sources without a safe URL and accepts only local or HTTP(S) openUrl values', () => {
    const safeUrls = [
      '/knowledge/files/doc',
      'https://knowledge.example/doc',
      'http://knowledge.example/doc',
    ]
    const unsafeUrls = [
      'javascript:alert(1)',
      'data:text/html,unsafe',
      '//evil.example/doc',
      'https://',
      'https://user:pass@evil.example/doc',
      'https://evil.example\\doc',
      `https://evil.example/${String.fromCharCode(0)}secret`,
      'https://knowledge.example/%',
      '/knowledge/%',
    ]
    const sidecars = [...safeUrls, ...unsafeUrls].map((openUrl, index) => ({
      kind: 'knowledge',
      evidenceId: `ev_${index}`,
      document: { id: `doc_${index}`, title: `Document ${index}`, openUrl },
      citation: { title: `Citation ${index}` },
      snippet: 'evidence',
      snippetTruncated: false,
    }))

    const sources = toSources(message([
      baseCall({ name: 'knowledge_search', sources: sidecars }),
    ]))

    expect(sources).toHaveLength(sidecars.length)
    expect(sources.slice(0, safeUrls.length).map(source => source.url)).toEqual(safeUrls)
    for (const source of sources.slice(safeUrls.length)) {
      expect(source).not.toHaveProperty('url')
      expect(source.kind).toBe('knowledge')
    }
  })

  it('uses fileName, document title, then citation title and preserves a secondary document title', () => {
    const sources = toSources(message([
      baseCall({
        name: 'knowledge_search',
        sources: [
          {
            kind: 'knowledge',
            evidenceId: 'ev_file',
            document: { id: 'doc_file', title: 'Document title', fileName: 'report.pdf' },
            citation: { title: 'Citation title' },
            snippet: '',
            snippetTruncated: false,
          },
          {
            kind: 'knowledge',
            evidenceId: 'ev_document',
            document: { id: 'doc_document', title: 'Document only' },
            citation: { title: 'Citation fallback' },
            snippet: '',
            snippetTruncated: false,
          },
          {
            kind: 'knowledge',
            evidenceId: 'ev_citation',
            citation: { title: 'Citation only' },
            snippet: '',
            snippetTruncated: false,
          },
        ],
      }),
    ]))

    expect(sources.map(source => source.title)).toEqual([
      'report.pdf',
      'Document only',
      'Citation only',
    ])
    expect(sources[0]).toMatchObject({ documentTitle: 'Document title' })
    expect(sources[1]).not.toHaveProperty('documentTitle')
  })

  it('upgrades a duplicate Knowledge title from citation fallback to later document metadata', () => {
    const sources = toSources(message([
      baseCall({
        toolId: 'search',
        name: 'knowledge_search',
        sources: [{
          kind: 'knowledge',
          evidenceId: 'ev_upgrade',
          rank: 2,
          citation: {
            title: 'Early citation title',
            locator: 'page 4',
            uri: 'knowledge://documents/doc_upgrade#chunk=chunk_4',
          },
          snippet: 'early bounded evidence',
          snippetTruncated: false,
        }],
      }),
      baseCall({
        toolId: 'get',
        name: 'knowledge_get',
        sources: [{
          kind: 'knowledge',
          evidenceId: 'ev_upgrade',
          document: {
            id: 'doc_upgrade',
            title: 'Later document title',
            fileName: 'later-report.pdf',
            sourcePath: 'reports/later-report.pdf',
          },
          citation: { title: 'Later citation title' },
          snippet: 'later evidence must not replace the first occurrence',
          snippetTruncated: true,
        }],
      }),
    ]))

    expect(sources).toHaveLength(1)
    expect(sources[0]).toEqual({
      kind: 'knowledge',
      sourceId: 1,
      evidenceId: 'ev_upgrade',
      rank: 2,
      title: 'later-report.pdf',
      documentTitle: 'Later document title',
      documentId: 'doc_upgrade',
      fileName: 'later-report.pdf',
      sourcePath: 'reports/later-report.pdf',
      citationTitle: 'Early citation title',
      citationUri: 'knowledge://documents/doc_upgrade#chunk=chunk_4',
      locator: 'page 4',
      snippet: 'early bounded evidence',
      snippetTruncated: true,
    })
    expect(sourceStableKey(sources[0])).toBe('knowledge:evidence:ev_upgrade')
  })

  it('bounds Knowledge snippets to 400 Unicode characters and preserves truncation state', () => {
    const snippet = '🙂'.repeat(401)
    const [source] = toSources(message([
      baseCall({
        name: 'knowledge_get',
        sources: [{
          kind: 'knowledge',
          evidenceId: 'ev_long',
          citation: { title: 'Long source' },
          snippet,
          snippetTruncated: false,
        }],
      }),
    ]))

    expect(Array.from(source.snippet || '')).toHaveLength(400)
    expect(source.snippetTruncated).toBe(true)
  })

  it('treats legacy kind-less sidecars as Web sources and ignores Knowledge sidecars on Web tools', () => {
    const sources = toSources(message([
      baseCall({
        name: 'web_search',
        sources: [
          { url: 'https://example.com/legacy', title: 'Legacy Web source' },
          {
            kind: 'knowledge',
            evidenceId: 'not-web',
            citation: { title: 'Must not become Web' },
            snippet: 'hidden',
          },
        ],
      }),
    ]))

    expect(sources).toEqual([{
      kind: 'web',
      sourceId: 1,
      url: 'https://example.com/legacy',
      title: 'Legacy Web source',
      domain: 'example.com',
      canonicalUrl: undefined,
      provider: undefined,
      fetched: undefined,
      fetchStatus: undefined,
    }])
  })

  it('uses evidence, document, and citation identity for stable Knowledge keys, never title alone', () => {
    const base: Omit<Extract<SourcePart, { kind: 'knowledge' }>, 'sourceId'> = {
      kind: 'knowledge',
      title: 'Repeated title',
    }

    expect(sourceStableKey({ ...base, sourceId: 1, evidenceId: 'ev_1' })).toBe('knowledge:evidence:ev_1')
    expect(sourceStableKey({ ...base, sourceId: 2, documentId: 'doc_1' })).toBe('knowledge:document:doc_1')
    expect(sourceStableKey({ ...base, sourceId: 3, citationUri: 'knowledge://doc#chunk=1' }))
      .toBe('knowledge:citation:knowledge://doc#chunk=1')
    expect(sourceStableKey({ ...base, sourceId: 4 })).not.toBe(sourceStableKey({ ...base, sourceId: 5 }))
  })

  it('maps exact Knowledge tool identifiers to friendly operations without changing Web mapping', () => {
    expect(toolOperationKey('knowledge_search')).toBe('knowledge.search')
    expect(toolOperationKey('knowledge_get')).toBe('knowledge.get')
    expect(toolActionLabel('knowledge_search')).toBe('Search knowledge')
    expect(toolActionLabel('knowledge_get')).toBe('Read knowledge source')
    expect(toolOperationKey('knowledge_search_preview')).not.toBe('knowledge.search')
    expect(toolOperationKey('web_search')).toBe('web.search')
    expect(toolActionLabel('web_search')).toBe('Search web')
  })
})

function expectNoChunkOrContent(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(expectNoChunkOrContent)
    return
  }
  if (!value || typeof value !== 'object') return
  for (const [key, nested] of Object.entries(value)) {
    expect(['chunk', 'content']).not.toContain(key.toLowerCase())
    expectNoChunkOrContent(nested)
  }
}
