<template>
  <section
    ref="rootRef"
    tabindex="-1"
    class="composer-settings"
    role="dialog"
    aria-label="Composer settings"
    @keydown.esc.stop="$emit('close')"
  >
    <div class="composer-settings__head">
      <span>Composer settings</span>
      <button type="button" class="composer-settings__close" aria-label="Close composer settings" @click="$emit('close')">
        <Icon name="x" :size="14" />
      </button>
    </div>

    <div class="composer-settings__section">
      <span class="composer-settings__label">Execution mode</span>
      <label
        v-for="option in executionOptions"
        :key="option.value"
        class="composer-settings__radio"
        :class="{ 'is-disabled': elevatedUnavailable }"
      >
        <input
          type="radio"
          name="composer-execution-mode"
          :value="option.value"
          :checked="normalizedElevatedMode === option.value"
          :disabled="elevatedUnavailable"
          @change="$emit('setElevatedMode', option.value)"
        />
        <span>{{ option.label }}</span>
      </label>
      <span v-if="elevatedUnavailable" class="composer-settings__hint">Owner-only mode is unavailable for this browser session.</span>
    </div>

    <div class="composer-settings__section composer-settings__section--rows">
      <ControlSwitch
        label="Squilla Router"
        :caption="routerEnabled ? 'Enabled' : 'Disabled'"
        aria-label="Squilla Router"
        :checked="routerEnabled"
        :busy="routerSettingsBusy"
        @change="$emit('setRouterEnabled', $event)"
      />
      <ControlSwitch
        label="Visual effects"
        :caption="visualEffectsEnabled ? 'Router animation on' : 'Router animation off'"
        aria-label="Visual effects"
        :checked="visualEffectsEnabled"
        @change="$emit('setVisualEffectsEnabled', $event)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ControlSwitch from '@/components/ControlSwitch.vue'

const executionOptions = [
  { value: '', label: 'Off' },
  { value: 'on', label: 'Prompt for approvals' },
  { value: 'bypass', label: 'Bypass approvals' },
  { value: 'full', label: 'Full access' },
] as const

const props = defineProps<{
  elevatedMode: string
  elevatedUnavailable: boolean
  routerEnabled: boolean
  routerSettingsBusy: boolean
  visualEffectsEnabled: boolean
}>()

defineEmits<{
  close: []
  setElevatedMode: [mode: string]
  setRouterEnabled: [enabled: boolean]
  setVisualEffectsEnabled: [enabled: boolean]
}>()

const normalizedElevatedMode = computed(() => {
  return executionOptions.some(option => option.value === props.elevatedMode) ? props.elevatedMode : ''
})

// Anchored popover (mounted only while open): move focus into the panel on open
// so keyboard users land inside it and Escape — handled on the panel — closes it.
const rootRef = ref<HTMLElement | null>(null)
onMounted(() => rootRef.value?.focus())
</script>

<style scoped>
.composer-settings {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  width: min(360px, calc(100vw - 48px));
  padding: 0.75rem;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-xl);
  z-index: 30;
}

.composer-settings__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.625rem;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--text);
}

.composer-settings__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.composer-settings__close:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.composer-settings__section {
  display: grid;
  gap: 0.375rem;
  padding: 0.625rem 0;
  border-top: 1px solid var(--border);
}

.composer-settings__section:first-of-type {
  border-top: 0;
  padding-top: 0;
}

.composer-settings__section--rows {
  gap: 0.5rem;
}

.composer-settings__label {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--text-muted);
}

.composer-settings__radio {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 30px;
  padding: 0 0.25rem;
  border-radius: 6px;
  color: var(--text);
  font-size: 0.8125rem;
  cursor: pointer;
}

.composer-settings__radio:hover {
  background: var(--bg-hover);
}

.composer-settings__radio input {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin: 0;
  flex-shrink: 0;
  border: 1.5px solid var(--border-strong);
  border-radius: 999px;
  background: transparent;
  display: grid;
  place-content: center;
  transition: border-color 0.14s ease;
}

.composer-settings__radio input::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--accent);
  transform: scale(0);
  transition: transform 0.14s ease;
}

.composer-settings__radio input:checked {
  border-color: var(--accent);
}

.composer-settings__radio input:checked::before {
  transform: scale(1);
}

.composer-settings__radio input:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 2px;
}

.composer-settings__radio.is-disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.composer-settings__radio.is-disabled:hover {
  background: transparent;
}

.composer-settings__hint {
  color: var(--warn);
  font-size: 0.75rem;
  line-height: 1.35;
}

@media (max-width: 520px) {
  .composer-settings {
    left: -0.5rem;
    width: calc(100vw - 32px);
  }
}
</style>
