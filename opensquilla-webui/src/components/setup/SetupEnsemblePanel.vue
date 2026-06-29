<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { EnsembleMemberRow, EnsembleMemberValue, EnsembleSelectOption } from '@/composables/setup/useSetupEnsembleForm'

interface EnsemblePanelContract {
  profileId: string
  dirty: boolean
  providerOptions: readonly EnsembleSelectOption[]
  modelOptions: readonly EnsembleSelectOption[]
  proposerRows: readonly EnsembleMemberRow[]
  aggregatorRow: EnsembleMemberRow
}

defineProps<{
  panel: EnsemblePanelContract
}>()

const emit = defineEmits<{
  updateProposerField: [index: number, key: keyof EnsembleMemberValue, value: string]
  updateAggregatorField: [key: keyof EnsembleMemberValue, value: string]
  addProposer: []
  removeProposer: [index: number]
  reset: []
  save: []
}>()
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">LLM Ensemble</h3>
      <p class="control-section__desc">{{ panel.profileId }}</p>
    </div>

    <div class="setup-ensemble-table" role="table" aria-label="G8 proposer models">
      <div class="setup-ensemble-table__row is-head" role="row">
        <span>Role</span><span>Provider</span><span>Model</span><span class="setup-ensemble-table__actions-head">Actions</span>
      </div>
      <div
        v-for="row in panel.proposerRows"
        :key="row.index"
        class="setup-ensemble-table__row"
        role="row"
      >
        <span>{{ row.label }}</span>
        <select
          :value="row.provider"
          :aria-label="`${row.label} provider`"
          disabled
          @change="emit('updateProposerField', row.index, 'provider', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in panel.providerOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <select
          :value="row.model"
          :aria-label="`${row.label} model`"
          @change="emit('updateProposerField', row.index, 'model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in panel.modelOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <button
          type="button"
          class="btn btn--icon btn--ghost setup-ensemble-table__icon-btn"
          :disabled="!row.canRemove"
          :title="row.canRemove ? `Remove ${row.label}` : 'At least one proposer is required'"
          :aria-label="`Remove ${row.label}`"
          @click="emit('removeProposer', row.index)"
        >
          <Icon name="trash" :size="14" />
        </button>
      </div>
      <div class="setup-ensemble-table__footer">
        <button type="button" class="btn" @click="emit('addProposer')">
          <Icon name="plus" :size="14" />
          Add proposer
        </button>
      </div>
    </div>

    <div class="setup-ensemble-table setup-ensemble-table--single" role="table" aria-label="G8 aggregator model">
      <div class="setup-ensemble-table__row is-head" role="row">
        <span>Role</span><span>Provider</span><span>Model</span>
      </div>
      <div class="setup-ensemble-table__row" role="row">
        <span>{{ panel.aggregatorRow.label }}</span>
        <select
          :value="panel.aggregatorRow.provider"
          aria-label="Aggregator provider"
          disabled
          @change="emit('updateAggregatorField', 'provider', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in panel.providerOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <select
          :value="panel.aggregatorRow.model"
          aria-label="Aggregator model"
          @change="emit('updateAggregatorField', 'model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in panel.modelOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>
    </div>

    <div class="control-section__actions">
      <button type="button" class="btn" @click="emit('reset')">Reset</button>
      <button type="button" class="btn btn--primary" :disabled="!panel.dirty" @click="emit('save')">Save Ensemble</button>
    </div>
  </section>
</template>
