<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ControlSwitch from '@/components/ControlSwitch.vue'
import type { RouterConfigDisabledReason } from '@/composables/setup/useSetupRouterForm'

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
  ensembleProfileActive: boolean
  routerMode: string
  routerModeChoice: string
  routerConfigDisabled: boolean
  routerConfigDisabledReason: RouterConfigDisabledReason
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
    <div v-if="panel.ensembleProfileActive" class="setup-router-profile-note">
      <span class="setup-router-profile-note__title">{{ t('setup.router.ensembleProfileTitle') }}</span>
      <span class="setup-router-profile-note__desc">{{ t('setup.router.ensembleProfileDesc') }}</span>
    </div>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.router.mode') }}</span></div>
      <div class="control-row__control">
        <select
          class="control-input"
          :value="panel.routerModeChoice"
          name="setup_router_mode"
          :disabled="!panel.hasSavedProvider"
          @change="emit('updateRouterMode', ($event.target as HTMLSelectElement).value)"
        >
          <option value="recommended">{{ t('setup.router.modeModelRouting') }}</option>
          <option value="disabled">{{ t('setup.router.modeSingleModel') }}</option>
          <option
            v-if="panel.routerModeChoice === 'openrouter-mix' && panel.canUseOpenrouterMix"
            value="openrouter-mix"
          >{{ t('setup.router.modeOpenrouterMix') }}</option>
        </select>
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.router.defaultTextModel') }}</span></div>
      <div class="control-row__control">
        <select
          class="control-input"
          :value="panel.routerDefaultTier"
          name="setup_router_default_tier"
          :disabled="!panel.hasSavedProvider || panel.routerConfigDisabled"
          @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)"
        >
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
        <select
          class="control-input"
          :value="panel.routerVisualMode"
          name="setup_router_visual_mode"
          :disabled="panel.routerConfigDisabled"
          @change="emit('updateRouterVisualMode', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in panel.routerVisualModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>
    </label>
    <div
      v-if="panel.hasSavedProvider"
      class="setup-tier-table-wrap"
      :class="{ 'is-disabled': panel.routerConfigDisabled }"
    >
      <p v-if="panel.routerConfigDisabled" class="setup-tier-table-wrap__note">
        {{
          panel.routerConfigDisabledReason === 'ensemble'
            ? t('setup.router.routingEnsembleReadOnlyHint')
            : t('setup.router.routingDisabledHint')
        }}
      </p>
      <div class="setup-tier-table" role="table" :aria-disabled="panel.routerConfigDisabled ? 'true' : undefined">
        <div class="setup-tier-table__row is-head" role="row">
          <span>{{ t('setup.router.colTier') }}</span><span>{{ t('setup.router.colProvider') }}</span><span>{{ t('setup.router.colModel') }}</span><span>{{ t('setup.router.colThinking') }}</span><span>{{ t('setup.router.colImage') }}</span>
        </div>
        <div v-for="tier in panel.tierRows" :key="tier.name" class="setup-tier-table__row" role="row">
          <span class="setup-tier-table__tier">{{ panel.tierLabel(tier.name) }}</span>
          <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierProviderAria', { tier: tier.name })" :title="t('setup.router.tierProviderAria', { tier: tier.name })">{{ tier.provider || '-' }}</span>
          <input :value="tier.model" :aria-label="t('setup.router.tierModelAria', { tier: tier.name })" :placeholder="t('setup.router.tierModelAria', { tier: tier.name })" :disabled="panel.routerConfigDisabled" @input="emit('updateTierField', tier.name, 'model', ($event.target as HTMLInputElement).value)">
          <select :value="tier.thinkingLevel" :aria-label="t('setup.router.tierThinkingAria', { tier: tier.name })" :disabled="panel.routerConfigDisabled" @change="emit('updateTierField', tier.name, 'thinkingLevel', ($event.target as HTMLSelectElement).value)">
            <option v-for="v in ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']" :key="v" :value="v">{{ v || '-' }}</option>
          </select>
          <ControlSwitch :checked="tier.supportsImage" :disabled="panel.routerConfigDisabled" :aria-label="t('setup.router.tierImageAria', { tier: tier.name })" @change="(v) => emit('updateTierField', tier.name, 'supportsImage', v)" />
        </div>
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

.setup-router-profile-note {
  display: grid;
  gap: 0.25rem;
  margin-bottom: var(--sp-3);
  padding: 0.75rem;
  border: 1px solid color-mix(in srgb, var(--accent) 34%, var(--border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.setup-router-profile-note__title {
  color: var(--text);
  font-size: 0.8125rem;
  font-weight: 700;
}

.setup-router-profile-note__desc {
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.35;
}

.setup-tier-table-wrap {
  display: grid;
  gap: 0.5rem;
}

.setup-tier-table-wrap.is-disabled {
  opacity: 0.72;
}

.setup-tier-table-wrap__note {
  color: var(--text-muted);
  font-size: 0.8125rem;
  margin: 0;
}
</style>
