<script setup lang="ts">
import ControlSwitch from '@/components/ControlSwitch.vue'
import type { EnsembleMemberRow, EnsembleMemberValue, EnsembleSelectOption } from '@/composables/setup/useSetupEnsembleForm'

interface EnsemblePanelContract {
  enabled: boolean
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
  updateEnabled: [value: boolean]
  updateProposerField: [index: number, key: keyof EnsembleMemberValue, value: string]
  updateAggregatorField: [key: keyof EnsembleMemberValue, value: string]
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

    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Enable ensemble</span>
        <span class="control-row__desc">Runs the G8 proposers before the aggregator answers.</span>
      </div>
      <div class="control-row__control">
        <ControlSwitch
          :checked="panel.enabled"
          aria-label="Enable LLM Ensemble"
          @change="emit('updateEnabled', $event)"
        />
      </div>
    </label>

    <div class="setup-ensemble-table" role="table" aria-label="G8 proposer models">
      <div class="setup-ensemble-table__row is-head" role="row">
        <span>Role</span><span>Provider</span><span>Model</span>
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
