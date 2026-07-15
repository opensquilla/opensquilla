<script setup lang="ts">
// The one tier table, extracted from the Router panel so the provider preset
// card can preview preset tiers with the identical component. Presentational
// only: props in, events out — no RPC, no form state.
//
// Three render modes per cell:
//   • default    — the stable model input stays in free-text mode;
//   • combobox   — that same input gains a provider-scoped catalog only when
//                  a verified live listing exists (no remount on async arrival);
//   • readonly   — preset preview: no editable controls at all.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ControlSwitch from '@/components/ControlSwitch.vue'
import SetupModelCombobox from '@/components/setup/SetupModelCombobox.vue'
import type { SetupTierRow } from '@/composables/setup/useSetupRouterForm'
import type {
  DiscoveredModelCatalog,
  DiscoveredModelsByProvider,
} from '@/composables/setup/useSetupProviderForm'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  rows: readonly SetupTierRow[]
  tierLabel: (tier: string) => string
  disabled?: boolean
  readonly?: boolean
  // Provider-scoped live catalogs. A tier only receives the catalog belonging
  // to its own normalized provider id, so mixed-provider routes stay isolated.
  modelsByProvider?: DiscoveredModelsByProvider
}>(), {
  disabled: false,
  readonly: false,
  modelsByProvider: () => ({}),
})

const emit = defineEmits<{
  updateTierField: [name: string, key: 'model' | 'thinkingLevel' | 'supportsImage', value: string | boolean]
}>()

const THINKING_LEVELS = ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']
const EMPTY_CATALOG: DiscoveredModelCatalog = { models: [], source: 'none' }

function catalogFor(row: SetupTierRow): DiscoveredModelCatalog {
  const provider = row.provider.trim().toLowerCase()
  return props.modelsByProvider[provider] || EMPTY_CATALOG
}

function hasLiveCatalog(row: SetupTierRow): boolean {
  if (props.readonly || props.disabled) return false
  const catalog = catalogFor(row)
  return catalog.source === 'live' && catalog.models.length > 0
}

// The combobox dropdown is absolutely positioned; the table's rounded-corner
// overflow clip would cut it off, so overflow opens up only when a combobox
// is actually rendered.
const hasCombobox = computed(() => props.rows.some(row => hasLiveCatalog(row)))
</script>

<template>
  <div
    class="setup-tier-table"
    :class="{ 'setup-tier-table--open': hasCombobox }"
    role="table"
    :aria-disabled="disabled ? 'true' : undefined"
  >
    <div class="setup-tier-table__row is-head" role="row">
      <span>{{ t('setup.router.colTier') }}</span><span>{{ t('setup.router.colProvider') }}</span><span>{{ t('setup.router.colModel') }}</span><span>{{ t('setup.router.colThinking') }}</span><span>{{ t('setup.router.colImage') }}</span>
    </div>
    <div v-for="tier in rows" :key="tier.name" class="setup-tier-table__row" role="row">
      <span class="setup-tier-table__tier">{{ tierLabel(tier.name) }}</span>
      <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierProviderAria', { tier: tier.name })" :title="t('setup.router.tierProviderAria', { tier: tier.name })">{{ tier.provider || '-' }}</span>
      <template v-if="readonly">
        <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierModelAria', { tier: tier.name })" :title="tier.model || undefined">{{ tier.model || '-' }}</span>
        <span class="setup-tier-table__readonly" :aria-label="t('setup.router.tierThinkingAria', { tier: tier.name })">{{ tier.thinkingLevel || '-' }}</span>
        <ControlSwitch :checked="tier.supportsImage" :disabled="true" :aria-label="t('setup.router.tierImageAria', { tier: tier.name })" />
      </template>
      <template v-else>
        <SetupModelCombobox
          cell
          :field="{ name: `tier_${tier.name}_model`, label: t('setup.router.tierModelAria', { tier: tier.name }), placeholder: t('setup.router.tierModelAria', { tier: tier.name }) }"
          :value="tier.model"
          :models="catalogFor(tier).models"
          :model-source="catalogFor(tier).source"
          :disabled="disabled"
          @update="(val) => emit('updateTierField', tier.name, 'model', val)"
        />
        <select :value="tier.thinkingLevel" :aria-label="t('setup.router.tierThinkingAria', { tier: tier.name })" :disabled="disabled" @change="emit('updateTierField', tier.name, 'thinkingLevel', ($event.target as HTMLSelectElement).value)">
          <option v-for="v in THINKING_LEVELS" :key="v" :value="v">{{ v || '-' }}</option>
        </select>
        <ControlSwitch :checked="tier.supportsImage" :disabled="disabled" :aria-label="t('setup.router.tierImageAria', { tier: tier.name })" @change="(v) => emit('updateTierField', tier.name, 'supportsImage', v)" />
      </template>
    </div>
  </div>
</template>

<style scoped>
/* Let the combobox dropdown escape the table's rounded-corner clip; the head
   row keeps its own rounding so the corners still look clipped. */
.setup-tier-table--open {
  overflow: visible;
}

.setup-tier-table--open .setup-tier-table__row.is-head {
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}
</style>
