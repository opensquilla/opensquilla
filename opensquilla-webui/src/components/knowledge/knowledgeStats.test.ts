import { describe, expect, it, vi } from 'vitest'
import {
  getKnowledgeLibraryStats,
  parseKnowledgeLibraryStats,
} from './knowledgeStats'
import type { FetchLike } from './knowledgeUpload'

describe('knowledge library stats', () => {
  it('loads current file and chunk totals from the same-origin BFF', async () => {
    const fetcher = vi.fn<FetchLike>().mockResolvedValue(new Response(JSON.stringify({
      filesIndexed: 21_622,
      chunksIndexed: 224_066,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(getKnowledgeLibraryStats(fetcher)).resolves.toEqual({
      filesIndexed: 21_622,
      chunksIndexed: 224_066,
    })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/knowledge/stats', {
      credentials: 'same-origin',
    })
  })

  it('rejects missing, negative, fractional, and boolean counters', () => {
    for (const payload of [
      null,
      {},
      { filesIndexed: -1, chunksIndexed: 2 },
      { filesIndexed: 1.5, chunksIndexed: 2 },
      { filesIndexed: 1, chunksIndexed: true },
    ]) {
      expect(() => parseKnowledgeLibraryStats(payload)).toThrow('invalid library stats')
    }
  })
})
