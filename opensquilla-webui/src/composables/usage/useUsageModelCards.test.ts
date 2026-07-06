import { computed } from 'vue'
import { describe, expect, it } from 'vitest'

import { useUsageModelCards } from './useUsageModelCards'
import type { SessionRow } from '@/types/usage'

function rowVal(row: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] != null) return row[key]
  }
  return null
}

function cardsFor(sessions: SessionRow[]) {
  const { modelCards } = useUsageModelCards({
    visibleSessions: computed(() => sessions),
    rowVal,
  })
  return modelCards.value
}

describe('useUsageModelCards', () => {
  it('aggregates a mixed cost source and flags cache-blind estimates from breakdown items', () => {
    const sessions: SessionRow[] = [
      {
        session: 's1',
        modelBreakdown: [
          { model: 'm1', costUsd: 1, costSource: 'provider_billed' },
        ],
      },
      {
        session: 's2',
        modelBreakdown: [
          {
            model: 'm1',
            costUsd: 2,
            costSource: 'opensquilla_estimate',
            estimateBasis: 'cache_blind',
          },
        ],
      },
    ]

    const cards = cardsFor(sessions)

    expect(cards).toHaveLength(1)
    const [card] = cards
    expect(card.model).toBe('m1')
    expect(card.costUsd).toBeCloseTo(3)
    expect(card.costSource).toBe('mixed')
    expect(card.anyCacheBlind).toBe(true)
  })

  it('reports a single shared cost source (not mixed) when every item agrees', () => {
    const sessions: SessionRow[] = [
      {
        session: 's1',
        modelBreakdown: [{ model: 'm1', costUsd: 1, costSource: 'provider_billed' }],
      },
      {
        session: 's2',
        modelBreakdown: [{ model: 'm1', costUsd: 2, costSource: 'provider_billed' }],
      },
    ]

    const [card] = cardsFor(sessions)

    expect(card.costSource).toBe('provider_billed')
    expect(card.anyCacheBlind).toBe(false)
  })

  it('carries the row cost_source/estimate_basis into the synthetic fallback item when a session has no breakdown', () => {
    const sessions: SessionRow[] = [
      {
        session: 'fallback-1',
        model: 'm2',
        cost_usd: 5,
        cost_source: 'provider_billed',
      },
      {
        session: 'fallback-2',
        model: 'm2',
        cost_usd: 4,
        cost_source: 'opensquilla_estimate',
        estimate_basis: 'cache_blind',
      },
    ]

    const [card] = cardsFor(sessions)

    expect(card.model).toBe('m2')
    expect(card.costUsd).toBeCloseTo(9)
    expect(card.costSource).toBe('mixed')
    expect(card.anyCacheBlind).toBe(true)
  })

  it('keeps a single cost_source for an all-billed fallback session with no cache-blind estimate', () => {
    const sessions: SessionRow[] = [
      {
        session: 'fallback-1',
        model: 'm3',
        cost_usd: 5,
        cost_source: 'provider_billed',
      },
    ]

    const [card] = cardsFor(sessions)

    expect(card.costSource).toBe('provider_billed')
    expect(card.anyCacheBlind).toBe(false)
  })
})
