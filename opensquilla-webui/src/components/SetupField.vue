<template>
  <label :data-name="field.name" :data-scope="scope" :data-show-when="showWhenAttr" :for="fieldId">
    <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
    <small v-if="field.description" class="setup-field-desc">{{ field.description }}</small>
    <template v-if="field.type === 'bool'">
      <input
        :id="fieldId"
        :name="fieldName"
        type="checkbox"
        :checked="fieldValue === true || fieldValue === 'true'"
        @change="onBoolChange"
      >
    </template>
    <template v-else-if="field.type === 'select'">
      <select :id="fieldId" :name="fieldName" :value="fieldValue" @change="onInputChange">
        <option v-for="choice in field.choices" :key="choice" :value="choice">{{ choice }}</option>
      </select>
    </template>
    <template v-else>
      <input
        :id="fieldId"
        :name="fieldName"
        :type="inputType"
        :value="fieldValue"
        :placeholder="placeholder"
        :data-secret="isSecret"
        @input="onInputChange"
      >
    </template>
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface FieldSpec {
  name: string
  label: string
  type?: string
  required?: boolean
  default?: string | boolean | number
  placeholder?: string
  description?: string
  secret?: boolean
  choices?: string[]
  showWhen?: Record<string, string>
}

const props = defineProps<{
  field: FieldSpec
  value: string | boolean | number
  scope: string
}>()

const emit = defineEmits<{
  (e: 'update', name: string, value: unknown): void
}>()

const rawName = computed(() => String(props.field.name || 'field'))
const fieldName = computed(() => `setup_${props.scope}_${rawName.value}`)
const fieldId = computed(() => `setup-${props.scope}-${rawName.value.replace(/[^a-zA-Z0-9_-]+/g, '-')}`)

const isSecret = computed(() => props.field.secret || props.field.type === 'password')
const inputType = computed(() => {
  if (isSecret.value) return 'password'
  if (props.field.type === 'int' || props.field.type === 'float') return 'number'
  return 'text'
})
const placeholder = computed(() => props.field.placeholder || (isSecret.value ? 'leave blank to keep current' : ''))
const showWhenAttr = computed(() => {
  if (!props.field.showWhen || Object.keys(props.field.showWhen).length === 0) return ''
  return JSON.stringify(props.field.showWhen)
})

const fieldValue = computed(() => {
  if (props.value !== undefined && props.value !== null) return props.value
  if (props.field.type === 'bool') return props.field.default === true
  return String(props.field.default || '')
})

function onInputChange(event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  emit('update', props.field.name, target.value)
}

function onBoolChange(event: Event) {
  const target = event.target as HTMLInputElement
  emit('update', props.field.name, target.checked)
}
</script>

<style scoped>
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

label > span:first-child {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

input,
select,
textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--accent);
  outline: none;
}

input[type="checkbox"] {
  width: auto;
}

.setup-field-desc {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
