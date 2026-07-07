<template>
  <!-- A hard, flat, exact-width bar — a reusable primitive harvested from the
       Out-of-Register data-viz: no rounded pill, width == value, tabular label.
       Colour is a semantic status FILL (ink/fill discipline), not the accent by
       default only when tone is unset. -->
  <div class="coverage-bar" :data-tone="tone" role="img" :aria-label="ariaLabel">
    <span class="coverage-bar__track">
      <span class="coverage-bar__fill" :style="{ inlineSize: pct + '%' }" />
    </span>
    <span v-if="showLabel" class="coverage-bar__label">{{ label ?? Math.round(pct) + '%' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    max?: number
    label?: string
    showLabel?: boolean
    tone?: 'accent' | 'ok' | 'warn' | 'danger' | 'info' | 'queued'
  }>(),
  { max: 100, showLabel: true, tone: 'accent' },
)

const pct = computed(() => {
  // An empty/uninitialised denominator means "no coverage to show" — render 0%,
  // never a confident full bar (value/0 would otherwise clamp to 100).
  if (props.max <= 0) return 0
  return Math.max(0, Math.min(100, (props.value / props.max) * 100))
})

const ariaLabel = computed(() => props.label ?? `${Math.round(pct.value)} percent`)
</script>

<style scoped>
.coverage-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.coverage-bar__track {
  flex: 1;
  block-size: 8px;
  background: var(--bg-hover);
  box-shadow: var(--elev-1);
  overflow: hidden;
}
.coverage-bar__fill {
  display: block;
  block-size: 100%;
  background: var(--accent);
}
.coverage-bar[data-tone='ok'] .coverage-bar__fill { background: var(--ok-fill); }
.coverage-bar[data-tone='warn'] .coverage-bar__fill { background: var(--warn-fill); }
.coverage-bar[data-tone='danger'] .coverage-bar__fill { background: var(--danger-fill); }
.coverage-bar[data-tone='info'] .coverage-bar__fill { background: var(--info-fill); }
.coverage-bar[data-tone='queued'] .coverage-bar__fill { background: var(--queued-fill); }
.coverage-bar__label {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  min-inline-size: 4ch;
  text-align: end;
}
</style>
