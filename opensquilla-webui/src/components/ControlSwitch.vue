<script setup lang="ts">
import { computed } from 'vue'

// The one toggle-switch primitive for the control UI. Renders a native
// <input type="checkbox"> (so it keeps form semantics, name/:checked, native
// Space toggle, and test selectors) upgraded with role="switch" + aria-checked
// for AT parity with what used to be a hand-rolled <button role="switch"> in
// the composer. The visual track/thumb comes from the global `.control-switch`
// rule in styles/control-visual-system.css, so every adopter is pixel-identical.
//
// Drive it with `:checked` + `@change`, or with `v-model:checked`. (A plain
// `modelValue` prop is avoided on purpose: Vue casts an absent Boolean prop to
// false, which makes a `checked`/`modelValue` dual-source ambiguous.)
//
// Two layouts:
//   • bare toggle (default) — for settings rows that supply their own label.
//   • labeled row (pass `label`) — reproduces the composer's 42px title+caption
//     row, including the `busy` (in-flight) affordance.
const props = withDefaults(defineProps<{
  checked?: boolean
  disabled?: boolean
  busy?: boolean
  label?: string
  caption?: string
  ariaLabel?: string
  name?: string
  id?: string
}>(), { checked: false, disabled: false, busy: false })

const emit = defineEmits<{ change: [boolean]; 'update:checked': [boolean] }>()

const inert = computed(() => props.disabled || props.busy)

function setValue(value: boolean) {
  emit('change', value)
  emit('update:checked', value)
}

function onChange(event: Event) {
  setValue((event.target as HTMLInputElement).checked)
}

// Native checkboxes toggle on Space only; the composer's <button> also toggled
// on Enter. Preserve that so the migration is behaviour-neutral for keyboard
// users.
function onEnter(event: KeyboardEvent) {
  if (inert.value) return
  event.preventDefault()
  setValue(!props.checked)
}
</script>

<template>
  <label v-if="label" class="control-switch-row" :class="{ 'is-busy': busy }">
    <span class="control-switch-row__text">
      <strong>{{ label }}</strong>
      <small v-if="caption">{{ caption }}</small>
    </span>
    <input
      :id="id"
      class="control-switch"
      type="checkbox"
      role="switch"
      :name="name"
      :checked="checked"
      :aria-checked="checked ? 'true' : 'false'"
      :disabled="inert"
      :aria-busy="busy || undefined"
      :aria-label="ariaLabel"
      @change="onChange"
      @keydown.enter="onEnter"
    >
  </label>
  <input
    v-else
    :id="id"
    class="control-switch"
    type="checkbox"
    role="switch"
    :name="name"
    :checked="checked"
    :aria-checked="checked ? 'true' : 'false'"
    :disabled="inert"
    :aria-busy="busy || undefined"
    :aria-label="ariaLabel"
    @change="onChange"
    @keydown.enter="onEnter"
  >
</template>

<style scoped>
/* Labeled-row chrome (composer parity). The track/thumb itself is the global
   `.control-switch` rule, so it is not redefined here. */
.control-switch-row {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  cursor: pointer;
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
  min-height: 42px;
  padding: 0.5rem 0.625rem;
  text-align: left;
  width: 100%;
}

.control-switch-row:hover {
  background: var(--bg-surface);
  border-color: var(--border-focus);
}

.control-switch-row.is-busy {
  cursor: wait;
  opacity: 0.62;
}

/* The row owns the dimmed busy look; don't let the disabled input dim again. */
.control-switch-row.is-busy .control-switch:disabled {
  opacity: 1;
}

.control-switch-row__text strong {
  display: block;
  font-size: 0.8125rem;
}

.control-switch-row__text small {
  color: var(--text-muted);
  display: block;
  font-size: 0.6875rem;
  margin-top: 1px;
}
</style>
