<template>
  <section
    ref="rootRef"
    tabindex="-1"
    class="composer-settings"
    role="dialog"
    :aria-label="t('chat.composerSettings')"
    @keydown.esc.stop="$emit('close')"
  >
    <div class="composer-settings__head">
      <span>{{ t('chat.composerSettings') }}</span>
      <button type="button" class="composer-settings__close" :aria-label="t('chat.closeComposerSettings')" @click="$emit('close')">
        <Icon name="x" :size="14" />
      </button>
    </div>

    <div class="composer-settings__section composer-settings__section--rows">
      <ControlSwitch
        label="Squilla Router"
        :caption="routerEnabled ? t('chat.composer.enabled') : t('chat.composer.disabled')"
        aria-label="Squilla Router"
        :checked="routerEnabled"
        :busy="routerSettingsBusy"
        @change="$emit('setRouterEnabled', $event)"
      />
      <ControlSwitch
        label="Visual effects"
        :caption="visualEffectsEnabled ? t('chat.composer.routerAnimationOn') : t('chat.composer.routerAnimationOff')"
        aria-label="Visual effects"
        :checked="visualEffectsEnabled"
        @change="$emit('setVisualEffectsEnabled', $event)"
      />
      <ControlSwitch
        label="Coding mode"
        :caption="codingModeEnabled ? t('chat.composer.enabled') : t('chat.composer.disabled')"
        aria-label="Coding mode"
        :checked="codingModeEnabled"
        :busy="codingModeSettingsBusy"
        @change="$emit('setCodingModeEnabled', $event)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ControlSwitch from '@/components/ControlSwitch.vue'

const { t } = useI18n()

defineProps<{
  routerEnabled: boolean
  routerSettingsBusy: boolean
  visualEffectsEnabled: boolean
  codingModeEnabled: boolean
  codingModeSettingsBusy: boolean
}>()

defineEmits<{
  close: []
  setRouterEnabled: [enabled: boolean]
  setVisualEffectsEnabled: [enabled: boolean]
  setCodingModeEnabled: [enabled: boolean]
}>()

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

@media (max-width: 520px) {
  .composer-settings {
    left: -0.5rem;
    width: calc(100vw - 32px);
  }
}
</style>
