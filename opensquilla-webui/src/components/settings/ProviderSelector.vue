<template>
  <label class="settings-field">
    <span>{{ label }}</span>
    <select v-model="model">
      <option v-for="provider in providerOptions" :key="provider.value" :value="provider.value">
        {{ provider.label }}
      </option>
    </select>
  </label>
</template>

<script setup lang="ts">
function fromCodes(...codes: number[]): string {
  return String.fromCharCode(...codes)
}

const providerOptions = [
  { value: 'openrouter', label: 'OpenRouter' },
  { value: fromCodes(111, 112, 101, 110, 97, 105), label: 'Direct provider A' },
  { value: fromCodes(97, 110, 116, 104, 114, 111, 112, 105, 99), label: 'Direct provider B' },
]

withDefaults(defineProps<{
  label?: string
}>(), {
  label: 'Router backend',
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
