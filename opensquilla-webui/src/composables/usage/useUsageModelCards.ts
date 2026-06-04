import { computed, type ComputedRef } from 'vue'
import type { ModelCard, SessionRow } from '@/types/usage'

export function useUsageModelCards(options: {
  visibleSessions: ComputedRef<SessionRow[]>
  rowVal: (row: Record<string, unknown>, ...keys: string[]) => unknown
}) {
  const modelCards = computed((): ModelCard[] => {
    const map: Record<string, ModelCard> = {}

    options.visibleSessions.value.forEach(row => {
      const breakdown = Array.isArray(row.modelBreakdown) ? row.modelBreakdown : []
      const items = breakdown.length > 0 ? breakdown : [{
        model: row.model || 'unknown',
        inputTokens: Number(options.rowVal(row, 'input_tokens', 'inputTokens') || 0),
        outputTokens: Number(options.rowVal(row, 'output_tokens', 'outputTokens') || 0),
        cacheReadTokens: Number(options.rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0),
        cacheWriteTokens: Number(options.rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0),
        costUsd: Number(options.rowVal(row, 'cost_usd', 'costUsd') || 0),
      }]
      const modelsSeenInSession = new Set<string>()
      items.forEach(item => {
        const model = item.model || row.model || 'unknown'
        if (!map[model]) {
          map[model] = {
            model,
            provider: '',
            name: '',
            inputTokens: 0,
            outputTokens: 0,
            cacheReadTokens: 0,
            cacheWriteTokens: 0,
            costUsd: 0,
            sessions: 0,
            share: 0,
            totalTokens: 0,
          }
        }
        map[model].inputTokens += Number(options.rowVal(item, 'input_tokens', 'inputTokens') || 0)
        map[model].outputTokens += Number(options.rowVal(item, 'output_tokens', 'outputTokens') || 0)
        map[model].cacheReadTokens += Number(options.rowVal(item, 'cache_read_tokens', 'cacheReadTokens') || 0)
        map[model].cacheWriteTokens += Number(options.rowVal(item, 'cache_write_tokens', 'cacheWriteTokens') || 0)
        map[model].costUsd += Number(options.rowVal(item, 'cost_usd', 'costUsd') || 0)
        if (!modelsSeenInSession.has(model)) {
          map[model].sessions += 1
          modelsSeenInSession.add(model)
        }
      })
    })

    const models = Object.values(map).sort((a, b) => b.costUsd - a.costUsd)
    const totalCost = models.reduce((acc, m) => acc + m.costUsd, 0)

    return models.map(m => {
      const provider = (m.model || '').split('/')[0] || ''
      const name = (m.model || '').split('/').slice(1).join('/') || m.model || 'unknown'
      return {
        ...m,
        provider,
        name,
        share: totalCost > 0 ? (m.costUsd / totalCost) * 100 : 0,
        totalTokens: m.inputTokens + m.outputTokens,
      }
    })
  })

  const modelsMeta = computed(() => {
    const n = modelCards.value.length
    return `${n} model${n === 1 ? '' : 's'}`
  })

  return { modelCards, modelsMeta }
}
