<script setup lang="ts">
// Model combobox for the provider "model" field: the plain text input stays
// the primary control (free text ALWAYS works — discovery is an accelerator,
// never a gate), with an optional dropdown of live-discovered models layered
// on top. Presentational only: props in, events out (panel-contract pattern).
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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

// Dropdown geometry: the listbox is teleported to <body> because both hosts
// live inside the settings dialog's scrolling panels, which clip an in-flow
// absolute dropdown. Position is computed from the input's viewport rect.
const DROPDOWN_MAX_HEIGHT = 280
const DROPDOWN_MIN_WIDTH = 260
const DROPDOWN_GAP = 4
const DROPDOWN_MARGIN = 8

const open = ref(false)
const activeIndex = ref(-1)
const inputEl = ref<HTMLInputElement | null>(null)
const listStyle = ref<Record<string, string>>({})
// A saved model id must not hide the rest of the discovered list: opening the
// dropdown (focus / arrow keys) always shows every model, and the query filter
// only kicks in once the user edits the text during this open.
const typedSinceOpen = ref(false)

const fieldId = computed(() => `setup-provider-${String(props.field.name || 'model')}`)
const fieldName = computed(() => `setup_provider_${String(props.field.name || 'model')}`)

const query = computed(() => String(props.value || '').trim().toLowerCase())

// The discovered id exactly matching the field's current value, if any.
const selectedId = computed(() => {
  const typed = String(props.value || '').trim()
  return typed && props.models.some(model => model.id === typed) ? typed : ''
})

const matches = computed(() => {
  if (!query.value || !typedSinceOpen.value) {
    // Full-list mode: pin the current model first so it stays rendered and
    // findable even when the list is longer than the MAX_ROWS window.
    const idx = selectedId.value ? props.models.findIndex(m => m.id === selectedId.value) : -1
    if (idx <= 0) return props.models
    return [props.models[idx], ...props.models.slice(0, idx), ...props.models.slice(idx + 1)]
  }
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
  return !selectedId.value
})

const optionCount = computed(() => visibleModels.value.length + (showFreeTextRow.value ? 1 : 0))

// Muted provenance footer (progressive disclosure): where the list and the
// per-model metadata came from, once, instead of per-row badges. Empty (and
// hidden) unless the list really is live and at least one row names a source —
// the copy asserts "live list from the provider".
const provenance = computed(() => {
  if (props.modelSource !== 'live') return ''
  const sources = Array.from(new Set(props.models.map(model => model.capabilitySource).filter(Boolean)))
  if (!sources.length) return ''
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
  typedSinceOpen.value = true
  activeIndex.value = -1
}

// The single way to open in full-list mode; every open path that is not a
// text edit must go through it so the filter never leaks across opens.
function openList() {
  open.value = true
  typedSinceOpen.value = false
  activeIndex.value = -1
}

function onClick() {
  // Reopen on click for a still-focused input (row click / Escape keep DOM
  // focus, so no new `focus` event will fire). Never touch an open list —
  // caret moves while editing must not clear an in-progress filter.
  if (!open.value) openList()
}

function close() {
  open.value = false
  typedSinceOpen.value = false
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

// Anchor the teleported listbox to the input: below by default, flipped above
// when the space under the input is too short, clamped to the viewport.
function updateListPosition() {
  const input = inputEl.value
  if (!input) return
  const rect = input.getBoundingClientRect()
  const viewportW = window.innerWidth
  const viewportH = window.innerHeight
  const spaceBelow = viewportH - rect.bottom - DROPDOWN_GAP - DROPDOWN_MARGIN
  const spaceAbove = rect.top - DROPDOWN_GAP - DROPDOWN_MARGIN
  const openUp = spaceBelow < DROPDOWN_MAX_HEIGHT && spaceAbove > spaceBelow
  const maxHeight = Math.max(120, Math.min(DROPDOWN_MAX_HEIGHT, openUp ? spaceAbove : spaceBelow))
  const width = Math.min(Math.max(rect.width, DROPDOWN_MIN_WIDTH), viewportW - 2 * DROPDOWN_MARGIN)
  const left = Math.min(Math.max(rect.left, DROPDOWN_MARGIN), viewportW - width - DROPDOWN_MARGIN)
  listStyle.value = {
    left: `${left}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
    top: openUp ? 'auto' : `${rect.bottom + DROPDOWN_GAP}px`,
    bottom: openUp ? `${viewportH - rect.top + DROPDOWN_GAP}px` : 'auto',
  }
}

watch(open, isOpen => {
  if (isOpen) {
    updateListPosition()
    // Capture-phase scroll also catches the settings panel's inner scrolling,
    // which never bubbles to window.
    window.addEventListener('scroll', updateListPosition, { capture: true, passive: true })
    window.addEventListener('resize', updateListPosition)
  } else {
    window.removeEventListener('scroll', updateListPosition, { capture: true })
    window.removeEventListener('resize', updateListPosition)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', updateListPosition, { capture: true })
  window.removeEventListener('resize', updateListPosition)
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    // Consume Escape only when it dismisses the list; a closed combobox lets
    // it bubble so enclosing dialogs keep their Escape-to-close behavior.
    if (open.value) {
      event.preventDefault()
      event.stopPropagation()
      close()
    }
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) {
      openList()
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
        ref="inputEl"
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
        @focus="openList"
        @click="onClick"
        @blur="close"
        @keydown="onKeydown"
      >
      <Teleport to="body">
        <div
          v-if="open"
          :id="`${fieldId}-listbox`"
          class="setup-model-combobox__list"
          :style="listStyle"
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
            :aria-selected="model.id === selectedId ? 'true' : 'false'"
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
          <div v-if="provenance" class="setup-model-combobox__footer">{{ provenance }}</div>
        </div>
      </Teleport>
    </div>
  </div>
</template>

<style scoped>
/* Cell mode: the wrapper is a grid/table cell — the input fills it. No label
   chrome. The dropdown is teleported to <body>, so the cell never clips it. */
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
  overflow-y: auto;
  /* Teleported to <body>; left/top/bottom/width/max-height come from the
     inline style computed off the input's viewport rect. Sits above the
     settings dialog (z-index 300). */
  position: fixed;
  z-index: 400;
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

/* The row matching the field's current value, visible when the full list is
   shown over a saved model id. */
.setup-model-combobox__row[aria-selected='true'] .setup-model-combobox__id {
  color: var(--accent);
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
