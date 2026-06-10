<template>
  <section class="composer-settings" role="dialog" aria-label="Composer settings">
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
      <button
        type="button"
        class="composer-settings__switch"
        role="switch"
        aria-label="Squilla Router"
        :aria-checked="routerEnabled ? 'true' : 'false'"
        :disabled="routerSettingsBusy"
        @click="$emit('setRouterEnabled', !routerEnabled)"
      >
        <span>
          <strong>Squilla Router</strong>
          <small>{{ routerEnabled ? 'Enabled' : 'Disabled' }}</small>
        </span>
        <span class="composer-settings__switch-track" aria-hidden="true">
          <span class="composer-settings__switch-thumb" />
        </span>
      </button>

      <button
        type="button"
        class="composer-settings__switch"
        role="switch"
        aria-label="Visual effects"
        :aria-checked="visualEffectsEnabled ? 'true' : 'false'"
        @click="$emit('setVisualEffectsEnabled', !visualEffectsEnabled)"
      >
        <span>
          <strong>Visual effects</strong>
          <small>{{ visualEffectsEnabled ? 'Router animation on' : 'Router animation off' }}</small>
        </span>
        <span class="composer-settings__switch-track" aria-hidden="true">
          <span class="composer-settings__switch-thumb" />
        </span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'

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
</script>

<style scoped>
.composer-settings {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  width: min(360px, calc(100vw - 48px));
  padding: 0.75rem;
  border: 1px solid rgba(32, 39, 34, 0.14);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 18px 46px rgba(31, 35, 40, 0.16);
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
  color: #202722;
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
  color: #6b716a;
  cursor: pointer;
}

.composer-settings__close:hover {
  background: #f5f5f5;
  color: #202722;
}

.composer-settings__section {
  display: grid;
  gap: 0.375rem;
  padding: 0.625rem 0;
  border-top: 1px solid #ececef;
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
  color: #5f655f;
}

.composer-settings__radio {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 28px;
  color: #303034;
  font-size: 0.8125rem;
  cursor: pointer;
}

.composer-settings__radio input {
  margin: 0;
  accent-color: #202722;
}

.composer-settings__radio.is-disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.composer-settings__hint {
  color: #8a5a00;
  font-size: 0.75rem;
  line-height: 1.35;
}

.composer-settings__switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  width: 100%;
  min-height: 42px;
  padding: 0.5rem 0.625rem;
  border: 1px solid #e2e2e6;
  border-radius: 8px;
  background: #fbfbfc;
  color: #202722;
  text-align: left;
  cursor: pointer;
}

.composer-settings__switch:hover {
  border-color: #c9c9d1;
  background: #fff;
}

.composer-settings__switch:disabled {
  cursor: wait;
  opacity: 0.62;
}

.composer-settings__switch strong,
.composer-settings__switch small {
  display: block;
}

.composer-settings__switch strong {
  font-size: 0.8125rem;
}

.composer-settings__switch small {
  margin-top: 1px;
  color: #70776f;
  font-size: 0.6875rem;
}

.composer-settings__switch-track {
  position: relative;
  display: inline-flex;
  width: 36px;
  height: 20px;
  border-radius: 999px;
  background: #d6d6da;
  flex-shrink: 0;
  transition: background 0.16s ease;
}

.composer-settings__switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.22);
  transition: transform 0.16s ease;
}

.composer-settings__switch[aria-checked="true"] .composer-settings__switch-track {
  background: #202722;
}

.composer-settings__switch[aria-checked="true"] .composer-settings__switch-thumb {
  transform: translateX(16px);
}

@media (max-width: 520px) {
  .composer-settings {
    left: -0.5rem;
    width: calc(100vw - 32px);
  }
}
</style>
