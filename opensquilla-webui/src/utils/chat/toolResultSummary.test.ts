import { describe, expect, it } from 'vitest'
import {
  normalizeToolResultSummaries,
  toolResultSummaryText,
} from './toolResultSummary'

describe('tool result summaries', () => {
  it('normalizes persisted snake_case summaries without recounting preview JSON', () => {
    const summaries = normalizeToolResultSummaries(
      {
        delivery_summary: {
          returned_count: 20,
          result_chars: 12_345,
          provider_budget_violation: false,
        },
        preview_summary: {
          displayed_count: 1,
          preview_chars: 1_900,
          preview_truncated: true,
        },
      },
      '{"returnedCount":20,"results":[{}]}',
      { completeResult: false },
    )

    expect(summaries.delivery.returnedCount).toBe(20)
    expect(summaries.preview.displayedCount).toBe(1)
    expect(toolResultSummaryText(summaries.delivery, summaries.preview)).toBe(
      '模型收到 20 条结果 · 当前预览显示 1 条 · 预览已截断',
    )
  })

  it('accepts camelCase summaries', () => {
    const summaries = normalizeToolResultSummaries(
      {
        deliverySummary: { returnedCount: 2, resultChars: 100, providerBudgetViolation: true },
        previewSummary: { displayedCount: 2, previewChars: 100, previewTruncated: false },
      },
      '{}',
      { completeResult: false },
    )

    expect(toolResultSummaryText(summaries.delivery, summaries.preview)).toContain(
      'Provider 超出预算，OpenSquilla 已执行安全裁剪',
    )
  })

  it('derives matching delivery and preview counts for a complete live result', () => {
    const raw = '{"returnedCount":3,"results":[{},{},{}]}'
    const summaries = normalizeToolResultSummaries({}, raw, { completeResult: true })

    expect(summaries.delivery.returnedCount).toBe(3)
    expect(summaries.preview.displayedCount).toBe(3)
    expect(summaries.preview.previewTruncated).toBe(false)
  })

  it('uses the actual live array length when declared count metadata is stale', () => {
    const raw = '{"returnedCount":20,"results":[{}]}'
    const summaries = normalizeToolResultSummaries({}, raw, { completeResult: true })

    expect(summaries.delivery.returnedCount).toBe(1)
    expect(summaries.preview.displayedCount).toBe(1)
  })

  it('does not invent zero when historical JSON is incomplete', () => {
    const summaries = normalizeToolResultSummaries(
      { result_truncated: true, result_original_chars: 5000 },
      '{broken',
      { completeResult: false },
    )

    expect(summaries.delivery.returnedCount).toBeNull()
    expect(summaries.preview.displayedCount).toBeNull()
    expect(toolResultSummaryText(summaries.delivery, summaries.preview)).toBe('结果预览已截断')
  })
})
