<template>
  <section class="stat-row control-stat-grid" id="usage-metrics">
    <div class="stat stat--hero control-stat control-stat--hero">
      <div class="stat-label control-stat__label">{{ t('usageLogs.summary.totalTokens') }}</div>
      <div class="stat-value control-stat__value">{{ totalTokens }}</div>
      <div class="stat-hint control-stat__hint usage-token-breakdown">
        <template v-for="(part, index) in tokenParts" :key="part.label">
          <span v-if="index > 0" class="usage-token-breakdown__sep">·</span>
          <span><em>{{ part.label }}</em> {{ part.value }}</span>
        </template>
      </div>
    </div>
    <div class="stat control-stat">
      <div class="stat-label control-stat__label">{{ t('usageLogs.summary.totalCost') }}</div>
      <div class="stat-value mono control-stat__value control-stat__value--mono">{{ totalCost }}</div>
      <div class="stat-hint control-stat__hint" :title="costHintTitle">{{ costHintText }}</div>
    </div>
    <div class="stat control-stat">
      <div class="stat-label control-stat__label">{{ t('usageLogs.summary.sessions') }}</div>
      <div class="stat-value control-stat__value">{{ sessionCount }}</div>
      <div class="stat-hint control-stat__hint">{{ t('usageLogs.summary.acrossAllModels') }}</div>
    </div>
    <div class="stat control-stat">
      <div class="stat-label control-stat__label">{{ t('usageLogs.summary.avgCostPerSession') }}</div>
      <div class="stat-value mono control-stat__value control-stat__value--mono">{{ avgCost }}</div>
      <div class="stat-hint control-stat__hint">{{ t('usageLogs.summary.runningAverage') }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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
.stat-hint em {
  color: var(--text-dim);
  font-style: normal;
  margin-right: 4px;
}
</style>
