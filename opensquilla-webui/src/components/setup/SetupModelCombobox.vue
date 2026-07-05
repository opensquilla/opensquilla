<script setup lang="ts">
// Model combobox for the provider "model" field: the plain text input stays
// the primary control (free text ALWAYS works — discovery is an accelerator,
// never a gate), with an optional dropdown of live-discovered models layered
// on top. Presentational only: props in, events out (panel-contract pattern).
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DiscoveredModel } from '@/composables/setup/useSetupProviderForm'

const { t } = useI18n()

interface FieldSpec {
  name: string
  label: string
  required?: boolean
  placeholder?: string
  description?: string
  [key: string]: unknown
}

const props = defineProps<{
  field: FieldSpec
  value: string
  models: DiscoveredModel[]
  modelSource: string
  // Cell mode drops the outer control-row + label chrome so the combobox can
  // live inside a table cell (tier table); the field label becomes the input's
  // aria-label. Default (false) renders the full settings-row layout unchanged.
  cell?: boolean
}>()

const emit = defineEmits<{
  update: [value: string]
}>()

const MAX_ROWS = 40

const open = ref(false)
const activeIndex = ref(-1)

const fieldId = computed(() => `setup-provider-${String(props.field.name || 'model')}`)
const fieldName = computed(() => `setup_provider_${String(props.field.name || 'model')}`)

const query = computed(() => String(props.value || '').trim().toLowerCase())

const matches = computed(() => {
  if (!query.value) return props.models
  return props.models.filter(model =>
    model.id.toLowerCase().includes(query.value) || model.name.toLowerCase().includes(query.value),
  )
})

const visibleModels = computed(() => matches.value.slice(0, MAX_ROWS))
const truncatedCount = computed(() => Math.max(0, matches.value.length - visibleModels.value.length))

// The escape hatch: whatever was typed is always usable as-is. Shown whenever
// there is typed text that is not an exact discovered id.
const showFreeTextRow = computed(() => {
  const typed = String(props.value || '').trim()
  if (!typed) return false
  return !props.models.some(model => model.id === typed)
})

const optionCount = computed(() => visibleModels.value.length + (showFreeTextRow.value ? 1 : 0))

// Muted provenance footer (progressive disclosure): where the list and the
// per-model metadata came from, once, instead of per-row badges.
const provenance = computed(() => {
  const sources = Array.from(new Set(props.models.map(model => model.capabilitySource).filter(Boolean)))
  return t('setup.provider.modelProvenance', { sources: sources.join(', ') })
})

function compactTokens(count: number | null): string {
  if (count === null || !Number.isFinite(count) || count <= 0) return ''
  if (count >= 1_000_000) {
    const millions = Math.round((count / 1_000_000) * 10) / 10
    return `${millions % 1 === 0 ? millions.toFixed(0) : millions}M`
  }
  if (count >= 1000) return `${Math.round(count / 1000)}k`
  return String(count)
}

function rowMeta(model: DiscoveredModel): string {
  const parts: string[] = []
  const ctx = compactTokens(model.contextWindow)
  if (ctx) parts.push(ctx)
  parts.push(...model.capabilities.filter(cap => cap !== 'chat').slice(0, 3))
  return parts.join(' · ')
}

function onInput(event: Event) {
  emit('update', (event.target as HTMLInputElement).value)
  open.value = true
  activeIndex.value = -1
}

function onFocus() {
  open.value = true
  activeIndex.value = -1
}

function close() {
  open.value = false
  activeIndex.value = -1
}

function selectModel(id: string) {
  emit('update', id)
  close()
}

function selectAt(index: number) {
  if (index < 0 || index >= optionCount.value) return
  if (index < visibleModels.value.length) selectModel(visibleModels.value[index].id)
  else close() // free-text row: the typed value is already the field value
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    close()
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) {
      open.value = true
      return
    }
    if (!optionCount.value) return
    const delta = event.key === 'ArrowDown' ? 1 : -1
    activeIndex.value = (activeIndex.value + delta + optionCount.value) % optionCount.value
    return
  }
  if (event.key === 'Enter' && open.value && activeIndex.value >= 0) {
    event.preventDefault()
    selectAt(activeIndex.value)
  }
}
</script>

<template>
  <div :class="cell ? 'setup-model-combobox--cellwrap' : 'control-row control-row--stack'" :data-name="cell ? undefined : field.name" :data-scope="cell ? undefined : 'provider'">
    <div v-if="!cell" class="control-row__label-block">
      <label class="control-row__label" :for="fieldId">{{ field.label }}{{ field.required ? ' *' : '' }}</label>
      <span v-if="field.description" class="control-row__desc">{{ field.description }}</span>
    </div>
    <div class="setup-model-combobox" :class="cell ? undefined : 'control-row__control'">
      <input
        :id="fieldId"
        :class="cell ? undefined : 'control-input'"
        :name="fieldName"
        type="text"
        role="combobox"
        aria-autocomplete="list"
        :aria-expanded="open ? 'true' : 'false'"
        :aria-controls="`${fieldId}-listbox`"
        :aria-label="cell ? field.label : undefined"
        autocomplete="off"
        :value="value"
        :placeholder="field.placeholder || ''"
        @input="onInput"
        @focus="onFocus"
        @blur="close"
        @keydown="onKeydown"
      >
      <div
        v-if="open"
        :id="`${fieldId}-listbox`"
        class="setup-model-combobox__list"
        role="listbox"
        :aria-label="t('setup.provider.modelListLabel')"
        @mousedown.prevent
      >
        <button
          v-for="(model, index) in visibleModels"
          :key="model.id"
          type="button"
          class="setup-model-combobox__row"
          :class="{ 'is-active': index === activeIndex }"
          role="option"
          :aria-selected="model.id === value ? 'true' : 'false'"
          @mousedown.prevent
          @click="selectModel(model.id)"
        >
          <span class="setup-model-combobox__id">{{ model.id }}</span>
          <span v-if="rowMeta(model)" class="setup-model-combobox__meta">{{ rowMeta(model) }}</span>
        </button>
        <button
          v-if="showFreeTextRow"
          type="button"
          class="setup-model-combobox__row setup-model-combobox__row--freetext"
          :class="{ 'is-active': activeIndex === visibleModels.length }"
          role="option"
          aria-selected="false"
          @mousedown.prevent
          @click="close()"
        >
          <span class="setup-model-combobox__id">{{ t('setup.provider.modelUseTyped', { value: String(value || '').trim() }) }}</span>
        </button>
        <div v-if="!visibleModels.length && !showFreeTextRow" class="setup-model-combobox__footer">
          {{ t('setup.provider.modelNoMatches') }}
        </div>
        <div v-if="truncatedCount" class="setup-model-combobox__footer">
          {{ t('setup.provider.modelListTruncated', { shown: visibleModels.length, total: matches.length }) }}
        </div>
        <div class="setup-model-combobox__footer">{{ provenance }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-model-combobox {
  position: relative;
}

/* Cell mode: the wrapper is a grid/table cell — the input fills it and the
   dropdown anchors to the cell. No label chrome. */
.setup-model-combobox--cellwrap {
  min-width: 0;
}

.setup-model-combobox--cellwrap .setup-model-combobox input {
  box-sizing: border-box;
  width: 100%;
}

.setup-model-combobox__list {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  left: 0;
  max-height: 280px;
  overflow-y: auto;
  position: absolute;
  right: 0;
  top: calc(100% + var(--sp-1));
  z-index: 30;
}

.setup-model-combobox__row {
  align-items: baseline;
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  display: flex;
  font: inherit;
  gap: var(--sp-2);
  justify-content: space-between;
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
}

.setup-model-combobox__row:hover,
.setup-model-combobox__row.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.setup-model-combobox__row--freetext {
  border-top: 1px solid var(--border);
  color: var(--text-muted);
}

.setup-model-combobox__id {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

.setup-model-combobox__meta {
  color: var(--text-dim);
  flex-shrink: 0;
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.setup-model-combobox__footer {
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  font-size: var(--fs-xs);
  padding: var(--sp-1) var(--sp-3);
}
</style>
