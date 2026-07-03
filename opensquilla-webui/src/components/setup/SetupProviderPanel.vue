<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'

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
  providerAdvancedOpen: boolean
  providerEnvMissing: boolean
  providerEnvKey: string
  providerEnvCommand: string
  llmTimeoutSeconds: number
  providerFieldValue: (field: FieldSpec) => string
}

defineProps<{
  panel: ProviderPanelContract
}>()

const emit = defineEmits<{
  updateProviderSelected: [value: string]
  providerChange: []
  updateProviderField: [name: string, value: unknown]
  updateLlmTimeout: [value: number]
  copy: [command: string]
  goToSection: [value: string]
}>()

function onProviderSelect(event: Event) {
  emit('updateProviderSelected', (event.target as HTMLSelectElement).value)
  emit('providerChange')
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
    <div class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">{{ t('setup.provider.routerTiers') }}</span></div>
      <div class="control-row__control control-row__control--stack">
        <strong class="control-pill" :class="panel.routerSupportTone">{{ panel.routerSupportText }}</strong>
        <button
          v-if="panel.canConfigureRouter"
          type="button"
          class="setup-inline-link"
          @click="emit('goToSection', 'router')"
        >{{ t('setup.provider.configureRouter') }}</button>
      </div>
    </div>
    <SetupField
      v-for="field in panel.providerCoreFields"
      :key="field.name"
      :field="field"
      :value="panel.providerFieldValue(field)"
      scope="provider"
      :stack="!['bool', 'select', 'int', 'float'].includes(field.type || '')"
      @update="(name, val) => emit('updateProviderField', name, val)"
    />
    <details :open="panel.providerAdvancedOpen">
      <summary class="control-row control-row--divider">{{ t('setup.provider.advanced') }}</summary>
      <SetupField
        v-for="field in panel.providerAdvancedFields"
        :key="field.name"
        :field="field"
        :value="panel.providerFieldValue(field)"
        scope="provider"
        @update="(name, val) => emit('updateProviderField', name, val)"
      />
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
/* Stack the router-support pill above a wayfinding link into the Router section
   (shown only when this provider actually supports router tiers). */
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
</style>
