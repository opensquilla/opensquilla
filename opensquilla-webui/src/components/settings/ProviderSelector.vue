<template>
  <label class="settings-field">
    <span>{{ label }}</span>
    <select v-model="model">
      <option value="openrouter">OpenRouter</option>
      <option value="openai">OpenAI</option>
      <option value="anthropic">Anthropic</option>
    </select>
  </label>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  label?: string
}>(), {
  label: 'Router backend',
})

const model = defineModel<'openrouter' | 'openai' | 'anthropic'>({ required: true })
</script>

<style scoped>
.settings-field {
  color: var(--text-muted);
  display: grid;
  font-size: var(--fs-xs);
  font-weight: 750;
  gap: 7px;
}

.settings-field select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  min-height: 40px;
  outline: none;
  padding: 0 var(--sp-3);
}

.settings-field select:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
}
</style>
