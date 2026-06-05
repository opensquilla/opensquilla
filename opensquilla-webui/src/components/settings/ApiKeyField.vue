<template>
  <label class="settings-field">
    <span>{{ label }}</span>
    <input
      v-model="model"
      type="password"
      autocomplete="off"
      :placeholder="placeholder"
    />
  </label>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  label?: string
  placeholder?: string
}>(), {
  label: 'API key',
  placeholder: 'sk-...',
})

const model = defineModel<string>({ required: true })
</script>

<style scoped>
.settings-field {
  color: var(--text-muted);
  display: grid;
  font-size: var(--fs-xs);
  font-weight: 750;
  gap: 7px;
}

.settings-field input {
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

.settings-field input:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
}
</style>
