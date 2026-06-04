<template>
  <section class="sk-stats">
    <button
      v-for="tile in tiles"
      :key="tile.key"
      class="sk-stat"
      :class="[tile.mods, { 'is-active': activeKey === tile.key }]"
      type="button"
      @click="emit('select', tile.key)"
    >
      <div class="sk-stat__label">{{ tile.label }}</div>
      <div class="sk-stat__value">
        <span v-if="tile.tone" :class="tile.tone">{{ tile.value }}</span>
        <template v-else>{{ tile.value }}</template>
      </div>
      <div class="sk-stat__hint">{{ tile.hint }}</div>
    </button>
    <button
      v-if="proposalCount > 0"
      class="sk-stat sk-stat--proposals"
      :class="{ 'is-active': activeKey === 'proposals' }"
      type="button"
      title="Pending meta-skill proposals - synthesised by meta-skill-creator from your usage patterns"
      @click="emit('showProposals')"
    >
      <div class="sk-stat__label">Pending Proposals</div>
      <div class="sk-stat__value"><span class="sk-stat__warn">{{ proposalCount }}</span></div>
      <div class="sk-stat__hint">awaiting review</div>
    </button>
  </section>
</template>

<script setup lang="ts">
export interface SkillStatTile {
  key: string
  label: string
  value: string
  hint: string
  mods: string
  tone?: string
}

defineProps<{
  tiles: SkillStatTile[]
  activeKey: string
  proposalCount: number
}>()

const emit = defineEmits<{
  select: [key: string]
  showProposals: []
}>()
</script>

<style scoped>
.sk-stats {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}

.sk-stat {
  animation: sk-fade-up 360ms ease both;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: inherit;
  cursor: pointer;
  font: inherit;
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
  text-align: left;
  transition: border-color var(--transition), box-shadow var(--transition), transform 200ms ease;
}

.sk-stat.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.sk-stat:hover {
  border-color: var(--border-focus);
  box-shadow: 0 8px 24px -16px rgba(0, 0, 0, 0.4);
  transform: translateY(-1px);
}

.sk-stat--accent::before,
.sk-stat--proposals::before {
  bottom: 0;
  content: "";
  left: 0;
  position: absolute;
  top: 0;
  width: 3px;
}

.sk-stat--accent::before {
  background: var(--accent);
}

.sk-stat--proposals::before {
  background: var(--warn);
}

.sk-stat__label {
  color: var(--text-dim);
  display: block;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1.25;
  margin-bottom: 6px;
  text-transform: uppercase;
}

.sk-stat__value {
  color: var(--text);
  font-size: 1.75rem;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1.18;
}

.sk-stat__ok {
  color: var(--ok);
}

.sk-stat__warn {
  color: var(--warn);
}

.sk-stat__hint {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 6px;
}
</style>
