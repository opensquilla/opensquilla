<template>
  <section class="sk-stats control-stat-grid" style="--control-stat-min: 160px">
    <button
      v-for="tile in tiles"
      :key="tile.key"
      class="sk-stat control-stat control-stat--clickable"
      :class="[tile.mods, {
        'is-active': activeKey === tile.key,
        'control-stat--accent': tile.mods.includes('sk-stat--accent') || activeKey === tile.key,
        'control-stat--hero': activeKey === tile.key,
      }]"
      type="button"
      @click="emit('select', tile.key)"
    >
      <div class="sk-stat__label control-stat__label">{{ tile.label }}</div>
      <div class="sk-stat__value control-stat__value">
        <span v-if="tile.tone" :class="tile.tone">{{ tile.value }}</span>
        <template v-else>{{ tile.value }}</template>
      </div>
      <div class="sk-stat__hint control-stat__hint">{{ tile.hint }}</div>
    </button>
    <button
      v-if="proposalCount > 0"
      class="sk-stat sk-stat--proposals control-stat control-stat--clickable control-stat--accent control-stat--warn"
      :class="{ 'is-active': activeKey === 'proposals', 'control-stat--hero': activeKey === 'proposals' }"
      type="button"
      title="Pending meta-skill proposals - synthesised by meta-skill-creator from your usage patterns"
      @click="emit('showProposals')"
    >
      <div class="sk-stat__label control-stat__label">Pending Proposals</div>
      <div class="sk-stat__value control-stat__value"><span class="sk-stat__warn">{{ proposalCount }}</span></div>
      <div class="sk-stat__hint control-stat__hint">awaiting review</div>
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
.sk-stat__ok {
  color: var(--ok);
}

.sk-stat__warn {
  color: var(--warn);
}

</style>
