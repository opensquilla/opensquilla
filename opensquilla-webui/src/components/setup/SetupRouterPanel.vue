<script setup lang="ts">
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
  updateTierField: [name: string, key: keyof Omit<TierRow, 'name'>, value: string | boolean]
  save: []
}>()
</script>

<template>
  <section class="setup-panel">
    <header class="setup-panel__head">
      <h3>Router Tiers</h3>
      <p>{{ panel.routerSummary }}</p>
    </header>
    <div class="setup-router-toolbar">
      <label>
        <span>Mode</span>
        <select :value="panel.routerMode" name="setup_router_mode" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterMode', ($event.target as HTMLSelectElement).value)">
          <option value="recommended">SquillaRouter</option>
          <option value="disabled">Disabled</option>
        </select>
      </label>
      <label>
        <span>Default text model</span>
        <select :value="panel.routerDefaultTier" name="setup_router_default_tier" :disabled="!panel.hasSavedProvider" @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)">
          <option v-for="t in panel.textTiers" :key="t" :value="t">{{ panel.tierLabel(t) }}</option>
        </select>
      </label>
    </div>
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
        <input :checked="tier.supportsImage" type="checkbox" :aria-label="`${tier.name} supports image`" @change="emit('updateTierField', tier.name, 'supportsImage', ($event.target as HTMLInputElement).checked)">
      </div>
    </div>
    <div v-else class="setup-warning">Choose a provider first to preview and save SquillaRouter tiers.</div>
    <div class="setup-actions">
      <button class="setup-btn setup-btn--primary" :disabled="!panel.hasSavedProvider" @click="emit('save')">Save Router</button>
    </div>
  </section>
</template>
