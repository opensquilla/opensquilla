<template>
  <section class="usage-models">
    <div class="usage-section-head">
      <h3 class="usage-section-title">By model</h3>
      <span class="usage-section-meta">{{ modelsMeta }}</span>
    </div>
    <div class="usage-model-grid control-card-grid" style="--control-card-min: 260px">
      <template v-if="modelCards.length === 0">
        <div class="usage-models__empty">No model usage yet.</div>
      </template>
      <article
        v-for="(m, i) in modelCards"
        :key="m.model"
        class="usage-model-card control-card control-fade-item"
        :style="`--i:${i}`"
      >
        <header class="usage-model-card__head">
          <div class="usage-model-card__id">
            <span v-if="m.provider" class="usage-model-card__provider">{{ m.provider }}</span>
            <span class="usage-model-card__name" :title="m.model">{{ m.name }}</span>
          </div>
          <span class="usage-model-card__share" title="Share of total cost">{{ m.share.toFixed(1) }}%</span>
        </header>
        <div class="usage-model-card__share-bar">
          <span class="usage-model-card__share-fill" :style="`width:${m.share.toFixed(1)}%`" />
        </div>
        <dl class="usage-model-card__rows">
          <div><dt>Tokens</dt><dd class="usage-mono">{{ m.totalTokens.toLocaleString() }}</dd></div>
          <div><dt>Input</dt><dd class="usage-mono usage-dim">{{ m.inputTokens.toLocaleString() }}</dd></div>
          <div><dt>Output</dt><dd class="usage-mono usage-dim">{{ m.outputTokens.toLocaleString() }}</dd></div>
          <div v-if="m.cacheReadTokens > 0"><dt>Cache R</dt><dd class="usage-mono usage-dim">{{ m.cacheReadTokens.toLocaleString() }}</dd></div>
          <div v-if="m.cacheWriteTokens > 0"><dt>Cache W</dt><dd class="usage-mono usage-dim">{{ m.cacheWriteTokens.toLocaleString() }}</dd></div>
          <div><dt>Sessions</dt><dd>{{ m.sessions }}</dd></div>
          <div class="usage-model-card__cost-row"><dt>Cost</dt><dd class="usage-mono usage-cost">{{ fmtCost(m.costUsd) }}</dd></div>
        </dl>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ModelCard } from '@/types/usage'

defineProps<{
  modelCards: ModelCard[]
  modelsMeta: string
  fmtCost: (cost: number | null | undefined, opts?: { decimals?: number }) => string
}>()
</script>
