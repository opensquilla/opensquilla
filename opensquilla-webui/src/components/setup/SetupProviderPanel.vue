<script setup lang="ts">
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'

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
  save: []
}>()

function onProviderSelect(event: Event) {
  emit('updateProviderSelected', (event.target as HTMLSelectElement).value)
  emit('providerChange')
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Provider</h3>
      <p class="control-section__desc">{{ panel.providerSummary }}</p>
    </div>
    <SetupNeedList :items="panel.providerNeeds" label="Provider needs" />
    <label class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">Provider</span></div>
      <div class="control-row__control">
        <select class="control-input" :value="panel.providerSelected" name="setup_provider" @change="onProviderSelect">
          <option value="" disabled :selected="!panel.providerSelected">Choose a provider</option>
          <option v-for="p in panel.runtimeProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
        </select>
      </div>
    </label>
    <div class="control-row">
      <div class="control-row__label-block"><span class="control-row__label">SquillaRouter tiers</span></div>
      <div class="control-row__control">
        <strong class="control-pill" :class="panel.routerSupportTone">{{ panel.routerSupportText }}</strong>
      </div>
    </div>
    <SetupField
      v-for="field in panel.providerCoreFields"
      :key="field.name"
      :field="field"
      :value="panel.providerFieldValue(field)"
      scope="provider"
      @update="(name, val) => emit('updateProviderField', name, val)"
    />
    <details :open="panel.providerAdvancedOpen">
      <summary class="control-row control-row--divider">Advanced provider options</summary>
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
          <span class="control-row__label">Request timeout (seconds)</span>
          <span class="control-row__desc">How long to wait for a single model response before timing out &mdash; raise this for slow local models (Ollama, vLLM, LM Studio).</span>
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
      <div>{{ panel.providerEnvKey }} is not visible to this gateway process. Set it before starting or restarting the gateway, or paste an API key instead.</div>
      <SetupCommandBlock
        v-if="panel.providerEnvCommand"
        class="setup-warning__command"
        :command="panel.providerEnvCommand"
        copy-label="Copy set provider key command"
        @copy="emit('copy', $event)"
      />
    </div>
    <div class="control-section__actions">
      <button class="btn btn--primary" :disabled="!panel.providerSelected" @click="emit('save')">Save Provider</button>
    </div>
  </section>
</template>
