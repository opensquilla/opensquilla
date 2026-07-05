<script setup lang="ts">
// Ensemble settings section (Router group). Presentational panel-contract
// component: props in, events out. Beginner copy on every primary control;
// the raw config enums live in tooltips only. Saving rides the shared
// settings dirty bar (partial payloads — see useSetupEnsembleForm).
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ControlSwitch from '@/components/ControlSwitch.vue'

const { t } = useI18n()

interface EnsemblePanelContract {
  enabled: boolean
  selectionMode: string
  modelOptions: string[]
  minSuccessfulProposers: number
  allFailedPolicy: string
  showModelOptions: boolean
  showOpenrouterHint: boolean
  advancedOpen: boolean
  statusText: string
}

defineProps<{
  panel: EnsemblePanelContract
}>()

const emit = defineEmits<{
  updateEnabled: [value: boolean]
  updateSelectionMode: [value: string]
  addModelOption: [value: string]
  removeModelOption: [value: string]
  updateMinSuccessful: [value: number]
  updateAllFailedPolicy: [value: string]
}>()

// Local input buffer for the add-model field (pure UI state; the list itself
// lives in the form composable).
const newModel = ref('')

function submitModel() {
  const value = newModel.value.trim()
  if (!value) return
  emit('addModelOption', value)
  newModel.value = ''
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.ensemble.title') }}</h3>
      <p class="control-section__desc">{{ panel.statusText }}</p>
    </div>
    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.ensemble.enabledLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.ensemble.enabledDesc') }}</span>
      </div>
      <div class="control-row__control">
        <ControlSwitch
          :checked="panel.enabled"
          name="setup_ensemble_enabled"
          :aria-label="t('setup.ensemble.enabledLabel')"
          @change="(v) => emit('updateEnabled', v)"
        />
      </div>
    </label>
    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.ensemble.selectionLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.ensemble.selectionDesc') }}</span>
      </div>
      <div class="control-row__control">
        <select
          class="control-input"
          :value="panel.selectionMode"
          name="setup_ensemble_selection_mode"
          :title="t('setup.ensemble.rawValueTooltip', { value: panel.selectionMode })"
          @change="emit('updateSelectionMode', ($event.target as HTMLSelectElement).value)"
        >
          <option value="static_openrouter_b5" title="static_openrouter_b5">{{ t('setup.ensemble.selectionStatic') }}</option>
          <option value="router_dynamic" title="router_dynamic">{{ t('setup.ensemble.selectionDynamic') }}</option>
        </select>
      </div>
    </label>
    <p v-if="panel.showOpenrouterHint" class="setup-ensemble__hint" data-testid="setup-ensemble-openrouter-hint">
      {{ t('setup.ensemble.openrouterKeyHint') }}
    </p>
    <div v-if="panel.showModelOptions" class="control-row control-row--stack">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.ensemble.modelsLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.ensemble.modelsDesc') }}</span>
      </div>
      <div class="control-row__control setup-ensemble__models">
        <ul v-if="panel.modelOptions.length" class="setup-ensemble__chips" data-testid="setup-ensemble-chips">
          <li v-for="model in panel.modelOptions" :key="model" class="setup-ensemble__chip">
            <span class="setup-ensemble__chip-id">{{ model }}</span>
            <button
              type="button"
              class="setup-ensemble__chip-remove"
              :aria-label="t('setup.ensemble.removeModelAria', { model })"
              @click="emit('removeModelOption', model)"
            >&times;</button>
          </li>
        </ul>
        <div class="setup-ensemble__add">
          <input
            v-model="newModel"
            class="control-input"
            type="text"
            name="setup_ensemble_add_model"
            :placeholder="t('setup.ensemble.addModelPlaceholder')"
            :aria-label="t('setup.ensemble.modelsLabel')"
            @keydown.enter.prevent="submitModel"
          >
          <button type="button" class="btn" data-testid="setup-ensemble-add-model" @click="submitModel">
            {{ t('setup.ensemble.addModel') }}
          </button>
        </div>
      </div>
    </div>
    <p v-else class="setup-ensemble__hint" data-testid="setup-ensemble-static-hint">
      {{ t('setup.ensemble.modelsStaticHint') }}
    </p>
    <details :open="panel.advancedOpen">
      <summary class="control-row control-row--divider">{{ t('setup.ensemble.advanced') }}</summary>
      <label class="control-row">
        <div class="control-row__label-block">
          <span class="control-row__label">{{ t('setup.ensemble.minSuccessfulLabel') }}</span>
          <span class="control-row__desc">{{ t('setup.ensemble.minSuccessfulDesc') }}</span>
        </div>
        <div class="control-row__control">
          <input
            class="control-input control-input--narrow"
            :value="panel.minSuccessfulProposers"
            name="setup_ensemble_min_successful"
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            :title="t('setup.ensemble.rawValueTooltip', { value: 'min_successful_proposers' })"
            @input="emit('updateMinSuccessful', Number(($event.target as HTMLInputElement).value))"
          >
        </div>
      </label>
      <label class="control-row">
        <div class="control-row__label-block">
          <span class="control-row__label">{{ t('setup.ensemble.allFailedLabel') }}</span>
        </div>
        <div class="control-row__control">
          <select
            class="control-input"
            :value="panel.allFailedPolicy"
            name="setup_ensemble_all_failed_policy"
            :title="t('setup.ensemble.rawValueTooltip', { value: panel.allFailedPolicy })"
            @change="emit('updateAllFailedPolicy', ($event.target as HTMLSelectElement).value)"
          >
            <option value="fallback_single" title="fallback_single">{{ t('setup.ensemble.allFailedFallback') }}</option>
            <option value="error" title="error">{{ t('setup.ensemble.allFailedError') }}</option>
          </select>
        </div>
      </label>
    </details>
  </section>
</template>

<style scoped>
.setup-ensemble__hint {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.4;
  margin: 0 0 var(--sp-3);
}

.setup-ensemble__models {
  display: grid;
  gap: var(--sp-2);
}

.setup-ensemble__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  list-style: none;
  margin: 0;
  padding: 0;
}

.setup-ensemble__chip {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  display: inline-flex;
  gap: var(--sp-1);
  padding: 2px var(--sp-1) 2px var(--sp-2);
}

.setup-ensemble__chip-id {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

.setup-ensemble__chip-remove {
  align-items: center;
  background: none;
  border: none;
  border-radius: var(--radius-full);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-sm);
  height: 18px;
  justify-content: center;
  line-height: 1;
  padding: 0;
  width: 18px;
}

.setup-ensemble__chip-remove:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.setup-ensemble__add {
  display: flex;
  gap: var(--sp-2);
}

.setup-ensemble__add .control-input {
  flex: 1;
}
</style>
