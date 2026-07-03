<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ControlSwitch from '@/components/ControlSwitch.vue'

const { t } = useI18n()

interface TierRow {
  name: string
  provider: string
  model: string
  thinkingLevel: string
  supportsImage: boolean
}

interface RouterPanelContract {
  routerSummary: string
  routerMode: string
  routerDefaultTier: string
  routerVisualMode: string
  routerVisualModeDirty: boolean
  routerVisualModeOptions: readonly { value: string; label: string }[]
  hasSavedProvider: boolean
  canUseOpenrouterMix: boolean
  textTiers: readonly string[]
  tierRows: readonly TierRow[]
  tierLabel: (tier: string) => string
}

defineProps<{
  panel: RouterPanelContract
}>()

const emit = defineEmits<{
  updateRouterMode: [value: string]
  updateRouterDefaultTier: [value: string]
  updateRouterVisualMode: [value: string]
  updateTierField: [name: string, key: keyof Omit<TierRow, 'name'>, value: string | boolean]
  goToSection: [value: string]
}>()
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.router.title') }}</h3>
      <p class="control-section__desc">{{ panel.routerSummary }}</p>
    </div>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.router.mode') }}</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerMode" name="setup_router_mode" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterMode', ($event.target as HTMLSelectElement).value)">
          <option value="recommended">{{ t('setup.router.modeRecommended') }}</option>
          <option v-if="panel.canUseOpenrouterMix || panel.routerMode === 'openrouter-mix'" value="openrouter-mix">{{ t('setup.router.modeOpenrouterMix') }}</option>
          <option value="disabled">{{ t('setup.router.modeDisabled') }}</option>
        </select>
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.router.defaultTextModel') }}</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerDefaultTier" name="setup_router_default_tier" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)">
          <option v-for="t in panel.textTiers" :key="t" :value="t">{{ panel.tierLabel(t) }}</option>
        </select>
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.router.panelLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.router.panelDesc') }}</span>
      </div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerVisualMode" name="setup_router_visual_mode" @change="emit('updateRouterVisualMode', ($event.target as HTMLSelectElement).value)">
          <option v-for="option in panel.routerVisualModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>
    </label>
    <div v-if="panel.hasSavedProvider" class="setup-tier-table" role="table">
      <div class="setup-tier-table__row is-head" role="row">
        <span>{{ t('setup.router.colTier') }}</span><span>{{ t('setup.router.colProvider') }}</span><span>{{ t('setup.router.colModel') }}</span><span>{{ t('setup.router.colThinking') }}</span><span>{{ t('setup.router.colImage') }}</span>
      </div>
      <div v-for="tier in panel.tierRows" :key="tier.name" class="setup-tier-table__row" role="row">
        <span class="setup-tier-table__tier">{{ panel.tierLabel(tier.name) }}</span>
        <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierProviderAria', { tier: tier.name })" :title="t('setup.router.tierProviderAria', { tier: tier.name })">{{ tier.provider || '-' }}</span>
        <input :value="tier.model" :aria-label="t('setup.router.tierModelAria', { tier: tier.name })" :placeholder="t('setup.router.tierModelAria', { tier: tier.name })" @input="emit('updateTierField', tier.name, 'model', ($event.target as HTMLInputElement).value)">
        <select :value="tier.thinkingLevel" :aria-label="t('setup.router.tierThinkingAria', { tier: tier.name })" @change="emit('updateTierField', tier.name, 'thinkingLevel', ($event.target as HTMLSelectElement).value)">
          <option v-for="v in ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']" :key="v" :value="v">{{ v || '-' }}</option>
        </select>
        <ControlSwitch :checked="tier.supportsImage" :aria-label="t('setup.router.tierImageAria', { tier: tier.name })" @change="(v) => emit('updateTierField', tier.name, 'supportsImage', v)" />
      </div>
    </div>
    <div v-else class="setup-warning">
      <span>{{ t('setup.router.providerFirst') }}</span>
      <button type="button" class="setup-warning__action" @click="emit('goToSection', 'provider')">
        {{ t('setup.provider.title') }} &rarr;
      </button>
    </div>
  </section>
</template>

<style scoped>
/* Turns the "provider first" dead-end into wayfinding: a link-styled action that
   navigates to the Provider section. Presentation only — no config change. */
.setup-warning__action {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  display: block;
  font: inherit;
  font-weight: 600;
  margin-top: var(--sp-1);
  padding: 0;
}

.setup-warning__action:hover {
  text-decoration: underline;
}
</style>
