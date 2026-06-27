<script setup lang="ts">
import ControlSwitch from '@/components/ControlSwitch.vue'

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
  save: []
}>()
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Router Tiers</h3>
      <p class="control-section__desc">{{ panel.routerSummary }}</p>
    </div>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">Mode</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerMode" name="setup_router_mode" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterMode', ($event.target as HTMLSelectElement).value)">
          <option value="recommended">SquillaRouter</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">Default text model</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerDefaultTier" name="setup_router_default_tier" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)">
          <option v-for="t in panel.textTiers" :key="t" :value="t">{{ panel.tierLabel(t) }}</option>
        </select>
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Router panel</span>
        <span class="control-row__desc">Choose the chat strip visualization; routing still follows the saved tiers.</span>
      </div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.routerVisualMode" name="setup_router_visual_mode" @change="emit('updateRouterVisualMode', ($event.target as HTMLSelectElement).value)">
          <option v-for="option in panel.routerVisualModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>
    </label>
    <div v-if="panel.hasSavedProvider" class="setup-tier-table" role="table">
      <div class="setup-tier-table__row is-head" role="row">
        <span>Tier</span><span>Provider</span><span>Model</span><span>Thinking</span><span>Image</span>
      </div>
      <div v-for="tier in panel.tierRows" :key="tier.name" class="setup-tier-table__row" role="row">
        <span><code>{{ tier.name }}</code></span>
        <input :value="tier.provider" :aria-label="`${tier.name} provider`" :placeholder="`${tier.name} provider`" @input="emit('updateTierField', tier.name, 'provider', ($event.target as HTMLInputElement).value)">
        <input :value="tier.model" :aria-label="`${tier.name} model`" :placeholder="`${tier.name} model`" @input="emit('updateTierField', tier.name, 'model', ($event.target as HTMLInputElement).value)">
        <select :value="tier.thinkingLevel" :aria-label="`${tier.name} thinking level`" @change="emit('updateTierField', tier.name, 'thinkingLevel', ($event.target as HTMLSelectElement).value)">
          <option v-for="v in ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']" :key="v" :value="v">{{ v || '-' }}</option>
        </select>
        <ControlSwitch :checked="tier.supportsImage" :aria-label="`${tier.name} supports image`" @change="(v) => emit('updateTierField', tier.name, 'supportsImage', v)" />
      </div>
    </div>
    <div v-else class="setup-warning">Choose a provider first to preview and save SquillaRouter tiers.</div>
    <div class="control-section__actions">
      <button class="btn btn--primary" :disabled="!panel.hasSavedProvider && !panel.routerVisualModeDirty" @click="emit('save')">Save Router</button>
    </div>
  </section>
</template>
