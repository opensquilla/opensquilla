<template>
  <section
    class="hub-attention control-stat-grid"
    style="--control-stat-min: 180px"
    aria-label="Needs attention"
  >
    <button
      type="button"
      class="control-stat control-stat--clickable hub-attention__tile"
      :class="{ 'control-stat--warn': approvalsCount > 0, 'is-blocked': approvalsCount > 0 }"
      @click="emit('open-approvals')"
    >
      <span class="control-stat__label">Needs approval</span>
      <span class="control-stat__value">{{ approvalsCount }}</span>
      <span class="control-stat__hint">
        {{ approvalsCount > 0 ? 'open the blocked session →' : 'nothing waiting on you' }}
      </span>
    </button>
    <div class="control-stat control-stat--static hub-attention__tile">
      <span class="control-stat__label">Active</span>
      <span class="control-stat__value">
        {{ runningCount + queuedCount }}<span v-if="runningCount > 0" class="hub-attention__dot" aria-hidden="true"></span>
      </span>
      <span class="control-stat__hint">
        {{ runningCount }} running · {{ queuedCount }} queued
      </span>
    </div>
    <button
      v-if="costUsd != null"
      type="button"
      class="control-stat control-stat--clickable hub-attention__tile"
      @click="emit('open-usage')"
    >
      <span class="control-stat__label">Cost to date</span>
      <span class="control-stat__value control-stat__value--mono">${{ costUsd.toFixed(2) }}</span>
      <span class="control-stat__hint">view usage →</span>
    </button>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  approvalsCount: number
  runningCount: number
  queuedCount: number
  costUsd: number | null
}>()

const emit = defineEmits<{
  'open-approvals': []
  'open-usage': []
}>()
</script>

<style scoped>
.hub-attention__tile {
  font: inherit;
}

.hub-attention__tile.is-blocked {
  animation: hub-attention-glow 2s ease-in-out infinite;
}

@keyframes hub-attention-glow {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 0%, transparent); }
  50% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 35%, transparent); }
}

.hub-attention__dot {
  background: var(--ok);
  border-radius: 999px;
  display: inline-block;
  height: 8px;
  width: 8px;
  animation: pulse 1.5s ease-in-out infinite;
}
</style>
