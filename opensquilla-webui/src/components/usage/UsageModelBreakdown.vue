<template>
  <div class="usage-expand">
    <div class="usage-expand__head">
      <span class="usage-expand__connector" aria-hidden="true" />
      <span class="usage-expand__eyebrow">Model breakdown</span>
      <span class="usage-expand__count">{{ rows.length }} model{{ rows.length === 1 ? '' : 's' }}</span>
      <span class="usage-expand__spacer" />
      <span class="usage-expand__total">{{ totalTokens.toLocaleString() }} tokens &middot; {{ fmtCost(totalCost) }}</span>
    </div>
    <div v-if="anyProrated" class="usage-expand__notice" role="note">
      Per-model split is estimated; total is the actual billed amount.
    </div>
    <div class="usage-expand__list" role="table" aria-label="Model breakdown">
      <div
        v-for="(m, mi) in rows"
        :key="mi"
        class="usage-expand__row"
        :style="`--i:${mi}`"
        role="row"
      >
        <div class="usage-expand__model" role="cell" :title="m.model">
          <span v-if="m.provider" class="usage-expand__provider">{{ m.provider }}/</span><span class="usage-expand__name">{{ m.name }}</span>
        </div>
        <div class="usage-expand__share" role="cell">
          <span class="usage-expand__share-track">
            <span class="usage-expand__share-fill" :style="`width:${m.share.toFixed(2)}%`" />
          </span>
          <span class="usage-expand__share-pct">{{ m.share.toFixed(1) }}%</span>
        </div>
        <div class="usage-expand__tokens" role="cell">{{ m.tokens.toLocaleString() }}</div>
        <div class="usage-expand__cost" role="cell">{{ fmtCost(m.cost) }}</div>
        <div class="usage-expand__source" role="cell">
          <span
            class="usage-source"
            :class="costSourceClasses(m)"
            :title="costSourceTooltip(m)"
          >{{ costSourceLabel(m) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { BreakdownRow } from '@/types/usage'

defineProps<{
  rows: BreakdownRow[]
  totalTokens: number
  totalCost: number
  anyProrated: boolean
  fmtCost: (cost: number | null | undefined, opts?: { decimals?: number }) => string
  costSourceClasses: (row: BreakdownRow) => Record<string, boolean>
  costSourceLabel: (row: BreakdownRow) => string
  costSourceTooltip: (row: BreakdownRow) => string
}>()
</script>
