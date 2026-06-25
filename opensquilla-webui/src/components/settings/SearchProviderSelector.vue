<template>
  <div class="settings-choice-grid">
    <button
      type="button"
      class="settings-choice"
      :class="{ 'is-selected': model === 'duckduckgo' }"
      @click="model = 'duckduckgo'"
    >
      <Icon name="search" :size="18" />
      <span><strong>DuckDuckGo</strong><small>No key required</small></span>
    </button>
    <button
      type="button"
      class="settings-choice"
      :class="{ 'is-selected': model === 'brave' }"
      @click="model = 'brave'"
    >
      <Icon name="search" :size="18" />
      <span><strong>Brave Search</strong><small>Requires your API key</small></span>
    </button>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'

const model = defineModel<'duckduckgo' | 'brave'>({ required: true })
</script>

<style scoped>
.settings-choice-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-choice {
  align-items: center;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  display: grid;
  font: inherit;
  gap: var(--sp-3);
  grid-template-columns: auto 1fr;
  min-height: 78px;
  padding: var(--sp-3);
  text-align: left;
  transition: border-color var(--transition), box-shadow var(--transition), transform 200ms ease;
}

.settings-choice:hover {
  border-color: var(--border-focus);
  transform: translateY(-1px);
}

.settings-choice.is-selected {
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}

.settings-choice strong,
.settings-choice small {
  display: block;
}

.settings-choice strong {
  font-size: var(--fs-sm);
  font-weight: 750;
}

.settings-choice small {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 3px;
}

@media (max-width: 680px) {
  .settings-choice-grid {
    grid-template-columns: 1fr;
  }
}
</style>
