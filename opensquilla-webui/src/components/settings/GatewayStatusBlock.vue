<template>
  <div class="gateway-status-block">
    <span class="gateway-status-block__label">{{ label }}</span>
    <strong class="gateway-status-block__value">{{ value }}</strong>
    <span class="gateway-status-block__hint">{{ hint }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  label: string
  value: string
  hint: string
}>()
</script>

<style scoped>
.gateway-status-block {
  border-left: 3px solid var(--accent);
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 2px 0 2px var(--sp-3);
}

.gateway-status-block__label {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-weight: 760;
  text-transform: uppercase;
}

.gateway-status-block__value {
  color: var(--text);
  font-size: 1.15rem;
  font-weight: 780;
}

.gateway-status-block__hint {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
