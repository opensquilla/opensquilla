<template>
  <section class="usage-chart">
    <div class="usage-chart__head">
      <div class="usage-segs" role="tablist" aria-label="Chart metric">
        <button
          class="usage-seg"
          :class="{ 'is-active': chartMode === 'tokens' }"
          role="tab"
          @click="emit('update:chartMode', 'tokens')"
        >Tokens</button>
        <button
          class="usage-seg"
          :class="{ 'is-active': chartMode === 'cost' }"
          role="tab"
          @click="emit('update:chartMode', 'cost')"
        >Cost</button>
      </div>
      <div class="usage-range" role="tablist" aria-label="Date range">
        <button
          v-for="r in ['all', '7', '14', '30']"
          :key="r"
          class="usage-range__btn"
          :class="{ 'is-active': range === r }"
          role="tab"
          @click="emit('setRange', r)"
        >{{ r === 'all' ? 'All' : r + 'd' }}</button>
      </div>
    </div>
    <div class="usage-chart__legend">
      <span class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--input" />Input</span>
      <span v-show="chartMode === 'tokens'" class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--output" />Output</span>
      <span class="usage-chart__legend-spacer" />
      <span class="usage-chart__caption">{{ caption }}</span>
    </div>
    <div class="usage-bars">
      <template v-if="rows.length === 0">
        <div class="usage-bars__empty">
          <div class="usage-bars__empty-icon">
            <Icon name="usage" :size="36" />
          </div>
          <div>No data in the selected window.</div>
        </div>
      </template>
      <button
        v-for="(row, i) in rows"
        :key="i"
        class="usage-bar-row"
        type="button"
        :title="`Open ${row.sessionKey}`"
        :style="`--i:${i}`"
        @click="emit('openSession', row.sessionKey)"
      >
        <span class="usage-bar-row__label">{{ row.label }}</span>
        <span class="usage-bar-row__track">
          <span class="usage-bar-row__fill usage-bar-row__fill--input" :style="`width:${row.inputPct.toFixed(1)}%`" />
          <span
            v-if="row.outputPct > 0"
            class="usage-bar-row__fill usage-bar-row__fill--output"
            :style="`width:${row.outputPct.toFixed(1)}%`"
          />
          <span class="usage-bar-row__cap" :style="`left:${Math.min(100, row.totalPct).toFixed(1)}%`" />
        </span>
        <span class="usage-bar-row__value usage-mono">{{ row.valueLabel }}</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { ChartRow } from '@/types/usage'

defineProps<{
  chartMode: 'tokens' | 'cost'
  range: string
  caption: string
  rows: ChartRow[]
}>()

const emit = defineEmits<{
  'update:chartMode': [mode: 'tokens' | 'cost']
  setRange: [range: string]
  openSession: [sessionKey: string]
}>()
</script>
