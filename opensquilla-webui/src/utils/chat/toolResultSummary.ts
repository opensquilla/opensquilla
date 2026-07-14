import type {
  ToolResultDeliverySummary,
  ToolResultPreviewSummary,
} from '@/types/chat'

export interface ToolResultSummaries {
  delivery: ToolResultDeliverySummary
  preview: ToolResultPreviewSummary
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
    ? value
    : null
}

function structuredCount(value: unknown): number | null {
  const raw = record(value)
  if (!raw) return null
  for (const key of ['results', 'items', 'data', 'matches']) {
    if (Array.isArray(raw[key])) return raw[key].length
  }
  return nonNegativeInteger(raw.returnedCount)
}

function parseResult(result: string): unknown {
  try {
    return JSON.parse(result)
  } catch {
    return null
  }
}

function normalizedDelivery(value: unknown): ToolResultDeliverySummary | null {
  const raw = record(value)
  if (!raw) return null
  const returned = raw.returned_count ?? raw.returnedCount
  const chars = raw.result_chars ?? raw.resultChars
  const violation = raw.provider_budget_violation ?? raw.providerBudgetViolation
  const returnedCount = returned === null ? null : nonNegativeInteger(returned)
  const resultChars = nonNegativeInteger(chars)
  if ((returned !== null && returnedCount === null) || resultChars === null || typeof violation !== 'boolean') return null
  return { returnedCount, resultChars, providerBudgetViolation: violation }
}

function normalizedPreview(value: unknown): ToolResultPreviewSummary | null {
  const raw = record(value)
  if (!raw) return null
  const displayed = raw.displayed_count ?? raw.displayedCount
  const chars = raw.preview_chars ?? raw.previewChars
  const truncated = raw.preview_truncated ?? raw.previewTruncated
  const displayedCount = displayed === null ? null : nonNegativeInteger(displayed)
  const previewChars = nonNegativeInteger(chars)
  if ((displayed !== null && displayedCount === null) || previewChars === null || typeof truncated !== 'boolean') return null
  return { displayedCount, previewChars, previewTruncated: truncated }
}

export function normalizeToolResultSummaries(
  payload: unknown,
  result: string,
  options: { completeResult: boolean },
): ToolResultSummaries {
  const raw = record(payload)
  const delivery = normalizedDelivery(raw?.delivery_summary ?? raw?.deliverySummary)
  const preview = normalizedPreview(raw?.preview_summary ?? raw?.previewSummary)
  if (delivery && preview) return { delivery, preview }

  const parsed = parseResult(result)
  if (options.completeResult) {
    const count = structuredCount(parsed)
    const violation = record(parsed)?.providerBudgetViolation === true
    return {
      delivery: {
        returnedCount: count,
        resultChars: result.length,
        providerBudgetViolation: violation,
      },
      preview: {
        displayedCount: count,
        previewChars: result.length,
        previewTruncated: false,
      },
    }
  }

  const originalChars = nonNegativeInteger(raw?.result_original_chars ?? raw?.resultOriginalChars)
  const truncated = raw?.result_truncated === true || raw?.resultTruncated === true
  return {
    delivery: delivery ?? {
      returnedCount: null,
      resultChars: originalChars ?? result.length,
      providerBudgetViolation: false,
    },
    preview: preview ?? {
      displayedCount: structuredCount(parsed),
      previewChars: result.length,
      previewTruncated: truncated,
    },
  }
}

export function toolResultSummaryText(
  delivery: ToolResultDeliverySummary | undefined,
  preview: ToolResultPreviewSummary | undefined,
): string {
  if (!delivery || !preview) return ''
  const parts: string[] = []
  if (delivery.returnedCount !== null) parts.push(`模型收到 ${delivery.returnedCount} 条结果`)
  if (preview.displayedCount !== null) parts.push(`当前预览显示 ${preview.displayedCount} 条`)
  if (preview.previewTruncated) parts.push(parts.length ? '预览已截断' : '结果预览已截断')
  if (delivery.providerBudgetViolation) parts.push('Provider 超出预算，OpenSquilla 已执行安全裁剪')
  return parts.join(' · ')
}
