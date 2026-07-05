<script setup lang="ts">
// Routing template card for the Provider panel. Provider setup may offer a
// template, but Model Routing remains the only place where active tiers are
// reviewed or edited. The template can be applied from here once; details stay
// collapsed until the user wants to inspect the seed rows.
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SetupTierTable from '@/components/setup/SetupTierTable.vue'
import type { SetupTierRow } from '@/composables/setup/useSetupRouterForm'

const { t } = useI18n()

interface PresetCardContract {
  presetLabel: string
  presetDescription: string
  synthesized: boolean
  tierRows: SetupTierRow[]
  tierLabel: (tier: string) => string
  routerMode: string
  routerCustomized: boolean
}

const props = defineProps<{
  panel: PresetCardContract
}>()

const emit = defineEmits<{
  apply: []
  goToSection: [value: string]
}>()

const expanded = ref(false)

// Synthesized presets are honest about their provenance right in the summary.
const summaryLabel = computed(() =>
  props.panel.synthesized ? t('setup.preset.synthesizedLabel') : props.panel.presetLabel)

// Human names for the non-recommended router modes shown in the customized
// summary. Unknown modes fall back to the raw value rather than hiding it.
const MODE_KEYS: Record<string, string> = {
  custom: 'setup.preset.modeCustom',
  'openrouter-mix': 'setup.preset.modeCustom',
  disabled: 'setup.preset.modeDisabled',
  recommended: 'setup.preset.modeRecommended',
}

const customizedModeLabel = computed(() => {
  const key = MODE_KEYS[props.panel.routerMode]
  return key ? t(key) : props.panel.routerMode
})
</script>

<template>
  <div class="setup-preset-card" data-testid="setup-preset-card">
    <!-- Router already configured beyond defaults (or has unsaved edits):
         reflect the active routing state; never offer to overwrite it here. -->
    <div v-if="panel.routerCustomized" class="setup-preset-card__summary">
      <span class="setup-preset-card__text">{{ t('setup.preset.customizedSummary', { label: customizedModeLabel }) }}</span>
      <span class="setup-preset-card__desc">{{ t('setup.preset.customizedDesc') }}</span>
      <button
        type="button"
        class="setup-preset-card__link"
        data-testid="setup-preset-router-link"
        @click="emit('goToSection', 'modelStrategy')"
      >{{ t('setup.preset.viewInRouter') }}</button>
    </div>
    <template v-else>
      <div class="setup-preset-card__summary">
        <div class="setup-preset-card__summary-copy">
          <span class="setup-preset-card__text">{{ t('setup.preset.summary', { label: summaryLabel }) }}</span>
          <span class="setup-preset-card__desc">{{ t('setup.preset.desc') }}</span>
        </div>
        <div class="setup-preset-card__summary-actions">
          <button
            type="button"
            class="setup-preset-card__link"
            :aria-expanded="expanded ? 'true' : 'false'"
            data-testid="setup-preset-toggle"
            @click="expanded = !expanded"
          >{{ expanded ? t('setup.preset.hide') : t('setup.preset.customize') }}</button>
          <button
            type="button"
            class="btn btn--primary"
            data-testid="setup-preset-apply"
            @click="emit('apply')"
          >{{ t('setup.preset.apply') }}</button>
        </div>
      </div>
      <div v-if="expanded" class="setup-preset-card__body">
        <p class="setup-preset-card__desc">
          <span v-if="panel.synthesized" class="control-pill is-muted setup-preset-card__badge" data-testid="setup-preset-synthesized-badge">{{ t('setup.preset.synthesizedBadge') }}</span>
          {{ panel.presetDescription }}
        </p>
        <SetupTierTable :rows="panel.tierRows" :tier-label="panel.tierLabel" readonly />
      </div>
    </template>
  </div>
</template>

<style scoped>
.setup-preset-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: grid;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
}

.setup-preset-card__summary {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: space-between;
}

.setup-preset-card__summary-copy {
  display: grid;
  gap: var(--sp-1);
  min-width: min(100%, 24rem);
}

.setup-preset-card__summary-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.setup-preset-card__text {
  color: var(--text);
  font-size: var(--fs-sm);
}

.setup-preset-card__link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-sm);
  font-weight: 600;
  padding: 0;
}

.setup-preset-card__link:hover {
  text-decoration: underline;
}

.setup-preset-card__body {
  display: grid;
  gap: var(--sp-2);
}

.setup-preset-card__desc {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.4;
  margin: 0;
}

.setup-preset-card__badge {
  margin-right: var(--sp-2);
}

/* The shared table carries a bottom margin for the Router layout; the card's
   grid gap already spaces it. */
.setup-preset-card__body :deep(.setup-tier-table) {
  margin-bottom: 0;
}
</style>
