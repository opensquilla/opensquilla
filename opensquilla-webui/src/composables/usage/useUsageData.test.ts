import { describe, expect, it } from 'vitest'

import { buildUsageCsv } from './usageCsv'
import { normalizeUsageQueryResponse } from './useUsageQuery'

function parseCsvLine(line: string): string[] {
  const cells: string[] = []
  let cell = ''
  let quoted = false
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index]
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        cell += '"'
        index += 1
      } else {
        quoted = !quoted
      }
    } else if (character === ',' && !quoted) {
      cells.push(cell)
      cell = ''
    } else {
      cell += character
    }
  }
  cells.push(cell)
  return cells
}

describe('usage CSV native billing compatibility', () => {
  it('retains existing columns and appends lossless native receipt fields', () => {
    const native = {
      CNY: {
        amountNanos: '6975000000',
        amount: '6.975',
        usdEquivalentNanos: '1000000000',
        receiptCount: 1,
        normalizationRatesNativePerUsd: ['6.975'],
      },
    }
    const totals = {
      inputTokens: 10,
      outputTokens: 2,
      costNanos: '1000000000',
      billedCostNanos: '1000000000',
      estimatedCostNanos: '0',
      costSource: 'provider_billed',
      costSourceCounts: { provider_billed: 1 },
      nativeBilledByCurrency: native,
      pendingBillingReceiptCount: 0,
      nativeBillingExpectedReceiptCount: 1,
      nativeBillingMissingConfirmedReceiptCount: 0,
    }
    const snapshot = normalizeUsageQueryResponse({
      schemaVersion: 1,
      range: { preset: 'all', timezone: 'UTC', fromMs: null, toMs: 999 },
      totals,
      sessions: [{ sessionKey: 'session-1', totals }],
      coverage: {
        status: 'complete',
        nativeBilling: {
          status: 'complete',
          exactFromMs: 123,
          reasonCodes: [],
          missingConfirmedReceiptCount: 0,
          pendingReceiptCount: 0,
        },
      },
    })

    const [headerLine, summaryLine, sessionLine] = buildUsageCsv(
      snapshot,
      snapshot.sessions,
    ).split('\n')
    const headers = parseCsvLine(headerLine)
    const summary = parseCsvLine(summaryLine)
    const session = parseCsvLine(sessionLine)

    expect(headers.slice(0, 21)).toEqual([
      'row_type',
      'aggregation_mode',
      'coverage_status',
      'range_preset',
      'range_from_ms',
      'range_to_ms',
      'timezone',
      'session',
      'input_tokens',
      'output_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'cost_usd',
      'cost_cny',
      'billed_cost_usd',
      'estimated_cost_usd',
      'estimated_event_count',
      'cost_source',
      'missing_cost_entries',
      'cost_ephemeral',
      'model',
    ])
    expect(headers.slice(21)).toEqual([
      'native_billed_by_currency',
      'pending_billing_receipt_count',
      'native_billing_coverage_status',
      'native_billing_exact_from_ms',
      'native_billing_reason_codes',
      'native_billing_missing_confirmed_receipt_count',
      'native_billing_pending_receipt_count',
    ])
    // Existing cost_cny keeps its historical UI-rate projection semantics;
    // exact native CNY is additive in native_billed_by_currency below.
    expect(summary[13]).toBe('7.250000000')
    expect(session[13]).toBe('7.250000')
    expect(JSON.parse(summary[21]).CNY.amountNanos).toBe('6975000000')
    expect(JSON.parse(session[21]).CNY.usdEquivalentNanos).toBe('1000000000')
    expect(summary.slice(22)).toEqual(['0', 'complete', '123', '', '0', '0'])
    expect(session.slice(22)).toEqual(['0', 'complete', '123', '', '0', '0'])
  })
})
