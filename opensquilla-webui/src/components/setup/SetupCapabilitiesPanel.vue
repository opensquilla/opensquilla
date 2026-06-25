<script setup lang="ts">
import SetupNeedList from '@/components/SetupNeedList.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'
import ControlSwitch from '@/components/ControlSwitch.vue'

interface ProviderOption {
  providerId: string
  label: string
}

interface ProviderSpec {
  providerId?: string
  envKey?: string
  defaultBaseUrl?: string
  [key: string]: unknown
}

interface CapabilitiesPanelContract {
  form: {
    searchProvider: string
    searchMaxResults: number
    searchApiKey: string
    searchApiKeyEnv: string
    searchProxy: string
    searchUseEnvProxy: boolean
    searchFallbackPolicy: string
    searchDiagnostics: boolean
    memoryProvider: string
    memoryModel: string
    memoryApiKey: string
    memoryApiKeyEnv: string
    memoryBaseUrl: string
    memoryOnnxDir: string
    imageProvider: string
    imagePrimary: string
    imageApiKey: string
    imageApiKeyEnv: string
    imageBaseUrl: string
    imageEnabled: boolean
    memoryAutoCapture: boolean
    audioEnabled: boolean
    audioApiKey: string
    audioApiKeyEnv: string
  }
  options: {
    searchProviders: ProviderOption[]
    memoryProviders: ProviderOption[]
    imageProviders: ProviderOption[]
    imageSpec: ProviderSpec | null
  }
  state: {
    searchRequiresKey: boolean
    searchEnvPlaceholder: string
    searchAdvancedOpen: boolean
    searchNeeds: string[]
    searchEnvCommand: string
    searchStatusText: string
    memoryLocalControlEnabled: boolean
    memoryRemoteControlEnabled: boolean
    memoryApiKeyEnabled: boolean
    memoryRemoteOptionsOpen: boolean
    memoryRemoteOptionsSummary: string
    memoryModelPlaceholder: string
    memoryBasePlaceholder: string
    memoryOnnxPlaceholder: string
    memoryApiKeyLabel: string
    memoryApiKeyPlaceholder: string
    memoryEnvPlaceholder: string
    memoryNeeds: string[]
    memoryStatusText: string
    memoryEnvCommand: string
    imageNeeds: string[]
    imageStatusText: string
    imageEnvCommand: string
    capabilityBadgeTone: (name: string) => string
    capabilityBadgeLabel: (name: string) => string
    capabilitySaveButtonClass: (name: string) => string
    audioStatusText: string
    audioBadgeTone: string
    audioBadgeLabel: string
    audioKeyPlaceholder: string
  }
}

defineProps<{
  panel: CapabilitiesPanelContract
}>()

const emit = defineEmits<{
  updateField: [group: 'search' | 'memory' | 'image' | 'audio', key: string, value: string | number | boolean]
  searchProviderChange: []
  memoryProviderChange: []
  imageProviderChange: []
  saveSearch: []
  saveMemory: []
  saveImage: []
  saveAudio: []
  copy: [command: string]
}>()

function onSearchProviderSelect(event: Event) {
  emit('updateField', 'search', 'provider', (event.target as HTMLSelectElement).value)
  emit('searchProviderChange')
}

function onMemoryProviderSelect(event: Event) {
  emit('updateField', 'memory', 'provider', (event.target as HTMLSelectElement).value)
  emit('memoryProviderChange')
}

function onImageProviderSelect(event: Event) {
  emit('updateField', 'image', 'provider', (event.target as HTMLSelectElement).value)
  emit('imageProviderChange')
}
</script>

<template>
  <div class="setup-capabilities">
    <!-- Web search -->
    <section class="control-section">
      <div class="control-section__head">
        <h3 class="control-section__title">Web search</h3>
        <span class="control-pill control-section__status" :class="panel.state.capabilityBadgeTone('search')">{{ panel.state.capabilityBadgeLabel('search') }}</span>
        <p class="control-section__desc">{{ panel.state.searchStatusText }}</p>
      </div>
      <SetupCommandBlock
        v-if="panel.state.searchEnvCommand"
        class="setup-warning__command setup-mini__env-command"
        :command="panel.state.searchEnvCommand"
        copy-label="Copy set search key command"
        @copy="emit('copy', $event)"
      />
      <SetupNeedList :items="panel.state.searchNeeds" label="Search needs" />
      <label class="control-row">
        <div class="control-row__label-block"><span class="control-row__label">Credential provider</span></div>
        <div class="control-row__control">
          <select class="control-input" :value="panel.form.searchProvider" name="setup_search_provider" @change="onSearchProviderSelect">
            <option v-for="p in panel.options.searchProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
          </select>
        </div>
      </label>
      <label class="control-row">
        <div class="control-row__label-block"><span class="control-row__label">Max results</span></div>
        <div class="control-row__control">
          <input class="control-input control-input--narrow" :value="panel.form.searchMaxResults" name="setup_search_max_results" type="number" min="1" step="1" inputmode="numeric" @input="emit('updateField', 'search', 'maxResults', Number(($event.target as HTMLInputElement).value))">
        </div>
      </label>
      <template v-if="panel.state.searchRequiresKey">
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.searchApiKey" name="setup_search_api_key" type="password" placeholder="leave blank to keep current" @input="emit('updateField', 'search', 'apiKey', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key env</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.searchApiKeyEnv" name="setup_search_api_key_env" :placeholder="panel.state.searchEnvPlaceholder" @input="emit('updateField', 'search', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
      </template>
      <details :open="!!panel.state.searchAdvancedOpen">
        <summary class="control-row control-row--divider">Advanced search options</summary>
        <label class="control-row control-row--stack">
          <div class="control-row__label-block"><span class="control-row__label">HTTP proxy</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.searchProxy" name="setup_search_proxy" placeholder="http://127.0.0.1:7890" @input="emit('updateField', 'search', 'proxy', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Use environment proxy</span></div>
          <div class="control-row__control">
            <ControlSwitch :checked="panel.form.searchUseEnvProxy" name="setup_search_use_env_proxy" @change="(v) => emit('updateField', 'search', 'useEnvProxy', v)" />
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Fallback policy</span></div>
          <div class="control-row__control">
            <select class="control-input" :value="panel.form.searchFallbackPolicy" name="setup_search_fallback_policy" @change="emit('updateField', 'search', 'fallbackPolicy', ($event.target as HTMLSelectElement).value)">
              <option value="off">Off</option>
              <option value="network">Network retry</option>
            </select>
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Diagnostics</span></div>
          <div class="control-row__control">
            <ControlSwitch :checked="panel.form.searchDiagnostics" name="setup_search_diagnostics" @change="(v) => emit('updateField', 'search', 'diagnostics', v)" />
          </div>
        </label>
      </details>
      <div class="control-section__actions">
        <button :class="panel.state.capabilitySaveButtonClass('search')" @click="emit('saveSearch')">Save web search</button>
      </div>
    </section>

    <!-- Memory embedding -->
    <section class="control-section">
      <div class="control-section__head">
        <h3 class="control-section__title">Memory embedding</h3>
        <span class="control-pill control-section__status" :class="panel.state.capabilityBadgeTone('memory_embedding')">{{ panel.state.capabilityBadgeLabel('memory_embedding') }}</span>
        <p class="control-section__desc">{{ panel.state.memoryStatusText }}</p>
      </div>
      <SetupCommandBlock
        v-if="panel.state.memoryEnvCommand"
        class="setup-warning__command setup-mini__env-command"
        :command="panel.state.memoryEnvCommand"
        copy-label="Copy set memory key command"
        @copy="emit('copy', $event)"
      />
      <SetupNeedList :items="panel.state.memoryNeeds" label="Memory needs" />
      <label class="control-row">
        <div class="control-row__label-block">
          <span class="control-row__label">Automatic memory capture</span>
          <span class="control-row__desc">Save highlights of your conversations into long-term memory.</span>
        </div>
        <div class="control-row__control">
          <ControlSwitch :checked="panel.form.memoryAutoCapture" name="setup_memory_auto_capture" @change="(v) => emit('updateField', 'memory', 'autoCapture', v)" />
        </div>
      </label>
      <label class="control-row">
        <div class="control-row__label-block"><span class="control-row__label">Provider</span></div>
        <div class="control-row__control">
          <select class="control-input" :value="panel.form.memoryProvider" name="setup_memory_provider" @change="onMemoryProviderSelect">
            <option v-for="p in panel.options.memoryProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
          </select>
        </div>
      </label>
      <label v-if="panel.state.memoryLocalControlEnabled" class="control-row control-row--stack">
        <div class="control-row__label-block"><span class="control-row__label">ONNX directory</span></div>
        <div class="control-row__control">
          <input class="control-input" :value="panel.form.memoryOnnxDir" name="setup_memory_onnx_dir" :placeholder="panel.state.memoryOnnxPlaceholder" @input="emit('updateField', 'memory', 'onnxDir', ($event.target as HTMLInputElement).value)">
        </div>
      </label>
      <details v-if="panel.state.memoryRemoteControlEnabled || panel.state.memoryApiKeyEnabled" :open="panel.state.memoryRemoteOptionsOpen">
        <summary class="control-row control-row--divider">{{ panel.state.memoryRemoteOptionsSummary }}</summary>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Model</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.memoryModel" name="setup_memory_model" :placeholder="panel.state.memoryModelPlaceholder" :disabled="!panel.state.memoryRemoteControlEnabled" @input="emit('updateField', 'memory', 'model', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">{{ panel.state.memoryApiKeyLabel }}</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.memoryApiKey" name="setup_memory_api_key" type="password" :placeholder="panel.state.memoryApiKeyPlaceholder" :disabled="!panel.state.memoryApiKeyEnabled" @input="emit('updateField', 'memory', 'apiKey', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key env</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.memoryApiKeyEnv" name="setup_memory_api_key_env" :placeholder="panel.state.memoryEnvPlaceholder" :disabled="!panel.state.memoryApiKeyEnabled" @input="emit('updateField', 'memory', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row control-row--stack">
          <div class="control-row__label-block"><span class="control-row__label">Base URL</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.memoryBaseUrl" name="setup_memory_base_url" :placeholder="panel.state.memoryBasePlaceholder" :disabled="!panel.state.memoryRemoteControlEnabled" @input="emit('updateField', 'memory', 'baseUrl', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
      </details>
      <div class="control-section__actions">
        <button :class="panel.state.capabilitySaveButtonClass('memory_embedding')" @click="emit('saveMemory')">Save memory embedding</button>
      </div>
    </section>

    <!-- Image generation -->
    <section class="control-section">
      <div class="control-section__head">
        <h3 class="control-section__title">Image generation</h3>
        <span class="control-pill control-section__status" :class="panel.state.capabilityBadgeTone('image_generation')">{{ panel.state.capabilityBadgeLabel('image_generation') }}</span>
        <p class="control-section__desc">{{ panel.state.imageStatusText }}</p>
      </div>
      <SetupCommandBlock
        v-if="panel.state.imageEnvCommand"
        class="setup-warning__command setup-mini__env-command"
        :command="panel.state.imageEnvCommand"
        copy-label="Copy set image key command"
        @copy="emit('copy', $event)"
      />
      <SetupNeedList :items="panel.state.imageNeeds" label="Image needs" />
      <label class="control-row">
        <div class="control-row__label-block"><span class="control-row__label">Enabled</span></div>
        <div class="control-row__control">
          <ControlSwitch :checked="panel.form.imageEnabled" name="setup_image_enabled" @change="(v) => emit('updateField', 'image', 'enabled', v)" />
        </div>
      </label>
      <template v-if="panel.form.imageEnabled">
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Provider</span></div>
          <div class="control-row__control">
            <select class="control-input" :value="panel.form.imageProvider" name="setup_image_provider" @change="onImageProviderSelect">
              <option v-for="p in panel.options.imageProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
            </select>
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">Primary model</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.imagePrimary" name="setup_image_primary" @input="emit('updateField', 'image', 'primary', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.imageApiKey" name="setup_image_api_key" type="password" placeholder="leave blank to keep current" @input="emit('updateField', 'image', 'apiKey', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key env</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.imageApiKeyEnv" name="setup_image_api_key_env" :placeholder="panel.options.imageSpec?.envKey || 'OPENROUTER_API_KEY'" @input="emit('updateField', 'image', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row control-row--stack">
          <div class="control-row__label-block"><span class="control-row__label">Base URL</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.imageBaseUrl" name="setup_image_base_url" :placeholder="panel.options.imageSpec?.defaultBaseUrl || 'https://api.example.com/v1'" @input="emit('updateField', 'image', 'baseUrl', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
      </template>
      <div class="control-section__actions">
        <button :class="panel.state.capabilitySaveButtonClass('image_generation')" @click="emit('saveImage')">Save image generation</button>
      </div>
    </section>

    <!-- Audio -->
    <section class="control-section">
      <div class="control-section__head">
        <h3 class="control-section__title">Audio</h3>
        <span class="control-pill control-section__status" :class="panel.state.audioBadgeTone">{{ panel.state.audioBadgeLabel }}</span>
        <p class="control-section__desc">{{ panel.state.audioStatusText }}</p>
      </div>
      <label class="control-row">
        <div class="control-row__label-block">
          <span class="control-row__label">Enable voice &amp; audio tools</span>
          <span class="control-row__desc">Text-to-speech and speech-to-text.</span>
        </div>
        <div class="control-row__control">
          <ControlSwitch :checked="panel.form.audioEnabled" name="setup_audio_enabled" @change="(v) => emit('updateField', 'audio', 'enabled', v)" />
        </div>
      </label>
      <template v-if="panel.form.audioEnabled">
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.audioApiKey" name="setup_audio_api_key" type="password" :placeholder="panel.state.audioKeyPlaceholder" @input="emit('updateField', 'audio', 'apiKey', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
        <label class="control-row">
          <div class="control-row__label-block"><span class="control-row__label">API key env</span></div>
          <div class="control-row__control">
            <input class="control-input" :value="panel.form.audioApiKeyEnv" name="setup_audio_api_key_env" placeholder="AUDIO_PROVIDER_API_KEY" @input="emit('updateField', 'audio', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </div>
        </label>
      </template>
      <div class="control-section__actions">
        <button class="btn" @click="emit('saveAudio')">Save audio</button>
      </div>
    </section>
  </div>
</template>
