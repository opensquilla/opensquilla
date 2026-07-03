<template>
  <section
    ref="rootRef"
    tabindex="-1"
    class="composer-model-routing"
    role="dialog"
    :aria-label="t('chat.composer.modelRouting')"
    :aria-busy="busy ? 'true' : 'false'"
    @keydown.esc.stop="$emit('close')"
  >
    <div class="composer-model-routing__head">
      <span>{{ t('chat.composer.modelRouting') }}</span>
      <button type="button" class="composer-model-routing__close" :aria-label="t('chat.closeComposerSettings')" @click="$emit('close')">
        <Icon name="x" :size="14" />
      </button>
    </div>

    <div class="composer-model-routing__list" role="radiogroup" :aria-label="t('chat.composer.modelRouting')">
      <button
        v-for="option in modelRoutingOptions"
        :key="option.value"
        type="button"
        class="composer-model-routing__option"
        :class="{ 'is-active': selectedMode === option.value }"
        :disabled="busy"
        role="radio"
        :aria-checked="selectedMode === option.value ? 'true' : 'false'"
        @click="selectMode(option.value)"
      >
        <span class="composer-model-routing__option-main">
          <span class="composer-model-routing__option-label">{{ option.label }}</span>
          <Icon v-if="selectedMode === option.value" name="check" :size="14" />
        </span>
        <span class="composer-model-routing__option-desc">{{ option.description }}</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { ModelRoutingMode } from '@/types/modelRouting'
import { normalizeModelRoutingMode } from '@/types/modelRouting'

const { t } = useI18n()

const props = defineProps<{
  modelRoutingMode: ModelRoutingMode
  busy: boolean
}>()

const emit = defineEmits<{
  close: []
  setModelRoutingMode: [mode: ModelRoutingMode]
}>()

const modelRoutingOptions = computed(() => [
  {
    value: 'off',
    label: t('chat.composer.modelRoutingOff'),
    description: t('chat.composer.modelRoutingOffDesc'),
  },
  {
    value: 'squilla_router',
    label: t('chat.composer.modelRoutingSquillaRouter'),
    description: t('chat.composer.modelRoutingSquillaRouterDesc'),
  },
  {
    value: 'llm_ensemble',
    label: t('chat.composer.modelRoutingEnsemble'),
    description: t('chat.composer.modelRoutingEnsembleDesc'),
  },
] satisfies Array<{ value: ModelRoutingMode; label: string; description: string }>)

const selectedMode = computed(() => normalizeModelRoutingMode(props.modelRoutingMode))

function selectMode(mode: ModelRoutingMode) {
  if (props.busy) return
  emit('setModelRoutingMode', mode)
  emit('close')
}

const rootRef = ref<HTMLElement | null>(null)
onMounted(() => rootRef.value?.focus())
</script>

<style scoped>
.composer-model-routing {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  width: min(360px, calc(100vw - 48px));
  padding: 0.75rem;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-xl);
  z-index: 30;
}

.composer-model-routing__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.625rem;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--text);
}

.composer-model-routing__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.composer-model-routing__close:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.composer-model-routing__list {
  display: grid;
  gap: 0.375rem;
}

.composer-model-routing__option {
  display: grid;
  gap: 0.25rem;
  width: 100%;
  min-height: 58px;
  padding: 0.625rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.composer-model-routing__option:hover {
  background: var(--bg-hover);
}

.composer-model-routing__option:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 2px;
}

.composer-model-routing__option.is-active {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-surface));
}

.composer-model-routing__option:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.composer-model-routing__option:disabled:hover {
  background: transparent;
}

.composer-model-routing__option-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.composer-model-routing__option-label {
  font-size: 0.8125rem;
  font-weight: 700;
}

.composer-model-routing__option-desc {
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.35;
}

@media (max-width: 520px) {
  .composer-model-routing {
    left: -2.75rem;
    width: calc(100vw - 32px);
  }
}
</style>
