<template>
  <section class="stat-row" id="usage-metrics">
    <div class="stat stat--hero">
      <div class="stat-label">Total tokens</div>
      <div class="stat-value">{{ totalTokens }}</div>
      <div class="stat-hint usage-token-breakdown">
        <template v-for="(part, index) in tokenParts" :key="part.label">
          <span v-if="index > 0" class="usage-token-breakdown__sep">·</span>
          <span><em>{{ part.label }}</em> {{ part.value }}</span>
        </template>
      </div>
    </div>
    <div class="stat">
      <div class="stat-label">Total cost</div>
      <div class="stat-value mono">{{ totalCost }}</div>
      <div class="stat-hint" :title="costHintTitle">{{ costHintText }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Sessions</div>
      <div class="stat-value">{{ sessionCount }}</div>
      <div class="stat-hint">across all models</div>
    </div>
    <div class="stat">
      <div class="stat-label">Avg cost / session</div>
      <div class="stat-value mono">{{ avgCost }}</div>
      <div class="stat-hint">running average</div>
    </div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  totalTokens: string
  tokenParts: Array<{ label: string; value: string }>
  totalCost: string
  costHintText: string
  costHintTitle: string
  sessionCount: string
  avgCost: string
}>()
</script>

<style scoped>
.stat-row {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-4);
}

.stat--hero {
  position: relative;
}

.stat--hero::after {
  background: radial-gradient(circle at 0% 0%, color-mix(in srgb, var(--accent) 10%, transparent), transparent 60%);
  border-radius: inherit;
  content: "";
  inset: 0;
  pointer-events: none;
  position: absolute;
}

.stat-label {
  color: var(--text-dim);
  display: block;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1.25;
  text-transform: uppercase;
}

.stat-value {
  color: var(--text);
  font-size: 1.75rem;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1.18;
}

.stat-value.mono {
  font-family: var(--font-mono);
  font-size: 1.5rem;
}

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.stat-hint em {
  color: var(--text-dim);
  font-style: normal;
  margin-right: 4px;
}
</style>
