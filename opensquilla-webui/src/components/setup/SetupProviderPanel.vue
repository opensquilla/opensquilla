<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'
import SetupProviderCredentialCard from '@/components/setup/SetupProviderCredentialCard.vue'
import SetupModelCombobox from '@/components/setup/SetupModelCombobox.vue'
import type { ConnectionState, ProviderCredentialPanelState } from '@/composables/setup/useSetupProviderForm'
import type { SetupTierRow } from '@/composables/setup/useSetupRouterForm'

const { t } = useI18n()

interface ProviderOption {
  providerId: string
  label: string
}

interface FieldSpec {
  name: string
  label: string
  type?: string
  default?: string | boolean | number
  [key: string]: unknown
}

interface ProviderPanelContract {
  providerSummary: string
  providerSelected: string
  runtimeProviders: ProviderOption[]
  routerSupportTone: string
  routerSupportText: string
  canConfigureRouter: boolean
  providerNeeds: string[]
  providerCoreFields: FieldSpec[]
  providerAdvancedFields: FieldSpec[]
  credentialPanel: ProviderCredentialPanelState | null
  providerAdvancedOpen: boolean
  providerEnvMissing: boolean
  providerEnvKey: string
  providerEnvCommand: string
  llmTimeoutSeconds: number
  connection: ConnectionState
  providerFieldValue: (field: FieldSpec) => string
}

interface PresetCardContract {
  hasPreset: boolean
  presetLabel: string
  presetDescription: string
  synthesized: boolean
  tierRows: SetupTierRow[]
  tierLabel: (tier: string) => string
  routerMode: string
  routerCustomized: boolean
}

const props = defineProps<{
  panel: ProviderPanelContract
  // Optional routing-preset card contract (absent on older gateways whose
  // catalog carries no presets — the card simply doesn't render).
  preset?: PresetCardContract | null
}>()

const emit = defineEmits<{
  updateProviderSelected: [value: string]
  providerChange: []
  updateProviderField: [name: string, value: unknown]
  updateLlmTimeout: [value: number]
  probeConnection: []
  applyPreset: []
  copy: [command: string]
  goToSection: [value: string]
}>()

function onProviderSelect(event: Event) {
  emit('updateProviderSelected', (event.target as HTMLSelectElement).value)
  emit('providerChange')
}

function useCombobox(field: FieldSpec): boolean {
  // The discovered-model combobox only ever replaces the model field, and only
  // when discovery actually returned models — otherwise the plain free-text
  // field renders untouched (free text always works).
  return field.name === 'model' && props.panel.connection.models.length > 0
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.provider.title') }}</h3>
      <p class="control-section__desc">{{ panel.providerSummary }}</p>
    </div>
    <SetupNeedList :items="panel.providerNeeds" :label="t('setup.provider.needs')" />
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.provider.title') }}</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.providerSelected" name="setup_provider" @change="onProviderSelect">
          <option value="" disabled :selected="!panel.providerSelected">{{ t('setup.provider.choose') }}</option>
          <option v-for="p in panel.runtimeProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
        </select>
      </div>
    </label>
    <div v-if="panel.canConfigureRouter" class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.provider.routerTiers') }}</span>
        <span class="control-row__desc">{{ t('setup.provider.routingDesc') }}</span>
      </div>
      <div class="control-row__control control-row__control--stack">
        <button
          type="button"
          class="setup-inline-link"
          @click="emit('goToSection', 'modelStrategy')"
        >{{ t('setup.provider.configureRouter') }}</button>
      </div>
    </div>
    <template v-for="field in panel.providerCoreFields" :key="field.name">
      <SetupModelCombobox
        v-if="useCombobox(field)"
        :field="field"
        :value="panel.providerFieldValue(field)"
        :models="panel.connection.models"
        :model-source="panel.connection.modelSource"
        @update="(val) => emit('updateProviderField', 'model', val)"
      />
      <SetupField
        v-else
        :field="field"
        :value="panel.providerFieldValue(field)"
        scope="provider"
        :stack="!['bool', 'select', 'int', 'float'].includes(field.type || '')"
        @update="(name, val) => emit('updateProviderField', name, val)"
      />
    </template>
    <SetupProviderCredentialCard
      v-if="panel.credentialPanel"
      :panel="panel.credentialPanel"
      @reveal="panel.credentialPanel.onReveal?.()"
      @replace="panel.credentialPanel.onReplace?.()"
      @cancel-replace="panel.credentialPanel.onCancelReplace?.()"
      @test-connection="emit('probeConnection')"
      @update-field="(name, value) => emit('updateProviderField', name, value)"
    />
    <details :open="panel.providerAdvancedOpen">
      <summary class="control-row control-row--divider">{{ t('setup.provider.advanced') }}</summary>
      <template v-for="field in panel.providerAdvancedFields" :key="field.name">
        <SetupModelCombobox
          v-if="useCombobox(field)"
          :field="field"
          :value="panel.providerFieldValue(field)"
          :models="panel.connection.models"
          :model-source="panel.connection.modelSource"
          @update="(val) => emit('updateProviderField', 'model', val)"
        />
        <SetupField
          v-else
          :field="field"
          :value="panel.providerFieldValue(field)"
          scope="provider"
          @update="(name, val) => emit('updateProviderField', name, val)"
        />
      </template>
      <label class="control-row">
        <div class="control-row__label-block">
          <span class="control-row__label">{{ t('setup.provider.timeoutLabel') }}</span>
          <span class="control-row__desc">{{ t('setup.provider.timeoutDesc') }}</span>
        </div>
        <div class="control-row__control">
          <input
            class="control-input control-input--narrow"
            :value="panel.llmTimeoutSeconds"
            name="setup_provider_request_timeout"
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            @input="emit('updateLlmTimeout', Number(($event.target as HTMLInputElement).value))"
          >
        </div>
      </label>
    </details>
    <div v-if="panel.providerEnvMissing" class="setup-warning">
      <div>{{ t('setup.provider.envMissing', { envKey: panel.providerEnvKey }) }}</div>
      <SetupCommandBlock
        v-if="panel.providerEnvCommand"
        class="setup-warning__command"
        :command="panel.providerEnvCommand"
        :copy-label="t('setup.provider.copyKeyCommand')"
        @copy="emit('copy', $event)"
      />
    </div>
  </section>
</template>

<style scoped>
/* Stack the router-support pill above a wayfinding link into Model Routing
   (shown only when this provider actually supports model tiers). */
.control-row__control--stack {
  align-items: flex-start;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.setup-inline-link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  padding: 0;
}

.setup-inline-link:hover {
  text-decoration: underline;
}

/* Test-connection row: button + status pill side by side; the pill can wrap
   under the button on narrow widths. */
.setup-connection__actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.setup-connection__actions .btn {
  align-items: center;
  display: inline-flex;
  gap: var(--sp-2);
}

.setup-connection__spinner {
  animation: setup-connection-spin var(--dur-pulse) linear infinite;
  border: 2px solid color-mix(in srgb, currentColor 30%, transparent);
  border-radius: var(--radius-full);
  border-top-color: currentColor;
  display: inline-block;
  height: 12px;
  width: 12px;
}

@keyframes setup-connection-spin {
  to { transform: rotate(360deg); }
}

.setup-connection__hint {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
</style>
