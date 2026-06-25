<script setup lang="ts">
import SetupNeedList from '@/components/SetupNeedList.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'

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
  <section class="setup-panel">
    <header class="setup-panel__head">
      <h3>Capabilities</h3>
      <p>Web search &middot; Memory recall &middot; Image generation &middot; Audio</p>
    </header>
    <div class="setup-extras">
      <div class="setup-mini">
        <div class="setup-mini__head">
          <h4>Web search</h4>
          <span class="setup-badge" :class="panel.state.capabilityBadgeTone('search')">{{ panel.state.capabilityBadgeLabel('search') }}</span>
        </div>
        <p class="setup-muted">{{ panel.state.searchStatusText }}</p>
        <SetupCommandBlock
          v-if="panel.state.searchEnvCommand"
          class="setup-warning__command setup-mini__env-command"
          :command="panel.state.searchEnvCommand"
          copy-label="Copy set search key command"
          @copy="emit('copy', $event)"
        />
        <SetupNeedList :items="panel.state.searchNeeds" label="Search needs" />
        <label>
          <span>Provider</span>
          <select :value="panel.form.searchProvider" name="setup_search_provider" @change="onSearchProviderSelect">
            <option v-for="p in panel.options.searchProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
          </select>
        </label>
        <label>
          <span>Max results</span>
          <input :value="panel.form.searchMaxResults" name="setup_search_max_results" type="number" min="1" step="1" inputmode="numeric" @input="emit('updateField', 'search', 'maxResults', Number(($event.target as HTMLInputElement).value))">
        </label>
        <div v-if="panel.state.searchRequiresKey">
          <label :class="{ 'is-disabled': !panel.state.searchRequiresKey }">
            <span>API key</span>
            <input :value="panel.form.searchApiKey" name="setup_search_api_key" type="password" placeholder="leave blank to keep current" :disabled="!panel.state.searchRequiresKey" @input="emit('updateField', 'search', 'apiKey', ($event.target as HTMLInputElement).value)">
          </label>
          <label :class="{ 'is-disabled': !panel.state.searchRequiresKey }">
            <span>API key env</span>
            <input :value="panel.form.searchApiKeyEnv" name="setup_search_api_key_env" :placeholder="panel.state.searchEnvPlaceholder" :disabled="!panel.state.searchRequiresKey" @input="emit('updateField', 'search', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </label>
        </div>
        <details :open="!!panel.state.searchAdvancedOpen">
          <summary>Advanced search options</summary>
          <div class="setup-mini__advanced-body" aria-label="Search behavior">
            <label>
              <span>HTTP proxy</span>
              <input :value="panel.form.searchProxy" name="setup_search_proxy" placeholder="http://127.0.0.1:7890" @input="emit('updateField', 'search', 'proxy', ($event.target as HTMLInputElement).value)">
            </label>
            <label class="setup-check">
              <input :checked="panel.form.searchUseEnvProxy" name="setup_search_use_env_proxy" type="checkbox" @change="emit('updateField', 'search', 'useEnvProxy', ($event.target as HTMLInputElement).checked)">
              <span>Use environment proxy</span>
            </label>
            <label>
              <span>Fallback policy</span>
              <select :value="panel.form.searchFallbackPolicy" name="setup_search_fallback_policy" @change="emit('updateField', 'search', 'fallbackPolicy', ($event.target as HTMLSelectElement).value)">
                <option value="off">Off</option>
                <option value="network">Network retry</option>
              </select>
            </label>
            <label class="setup-check">
              <input :checked="panel.form.searchDiagnostics" name="setup_search_diagnostics" type="checkbox" @change="emit('updateField', 'search', 'diagnostics', ($event.target as HTMLInputElement).checked)">
              <span>Diagnostics</span>
            </label>
          </div>
        </details>
        <button :class="panel.state.capabilitySaveButtonClass('search')" @click="emit('saveSearch')">Save web search</button>
      </div>

      <div class="setup-mini">
        <div class="setup-mini__head">
          <h4>Memory embedding</h4>
          <span class="setup-badge" :class="panel.state.capabilityBadgeTone('memory_embedding')">{{ panel.state.capabilityBadgeLabel('memory_embedding') }}</span>
        </div>
        <p class="setup-muted">{{ panel.state.memoryStatusText }}</p>
        <SetupCommandBlock
          v-if="panel.state.memoryEnvCommand"
          class="setup-warning__command setup-mini__env-command"
          :command="panel.state.memoryEnvCommand"
          copy-label="Copy set memory key command"
          @copy="emit('copy', $event)"
        />
        <SetupNeedList :items="panel.state.memoryNeeds" label="Memory needs" />
        <label class="setup-check">
          <input :checked="panel.form.memoryAutoCapture" name="setup_memory_auto_capture" type="checkbox" @change="emit('updateField', 'memory', 'autoCapture', ($event.target as HTMLInputElement).checked)">
          <span>Automatic memory capture &mdash; save highlights of your conversations into long-term memory.</span>
        </label>
        <label>
          <span>Provider</span>
          <select :value="panel.form.memoryProvider" name="setup_memory_provider" @change="onMemoryProviderSelect">
            <option v-for="p in panel.options.memoryProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
          </select>
        </label>
        <label v-if="panel.state.memoryLocalControlEnabled" :class="{ 'is-disabled': !panel.state.memoryLocalControlEnabled }">
          <span>ONNX directory</span>
          <input :value="panel.form.memoryOnnxDir" name="setup_memory_onnx_dir" :placeholder="panel.state.memoryOnnxPlaceholder" :disabled="!panel.state.memoryLocalControlEnabled" @input="emit('updateField', 'memory', 'onnxDir', ($event.target as HTMLInputElement).value)">
        </label>
        <details v-if="panel.state.memoryRemoteControlEnabled || panel.state.memoryApiKeyEnabled" :open="panel.state.memoryRemoteOptionsOpen">
          <summary>{{ panel.state.memoryRemoteOptionsSummary }}</summary>
          <div class="setup-mini__advanced-body" aria-label="Memory embedding connection">
            <label :class="{ 'is-disabled': !panel.state.memoryRemoteControlEnabled }">
              <span>Model</span>
              <input :value="panel.form.memoryModel" name="setup_memory_model" :placeholder="panel.state.memoryModelPlaceholder" :disabled="!panel.state.memoryRemoteControlEnabled" @input="emit('updateField', 'memory', 'model', ($event.target as HTMLInputElement).value)">
            </label>
            <label :class="{ 'is-disabled': !panel.state.memoryApiKeyEnabled }">
              <span>{{ panel.state.memoryApiKeyLabel }}</span>
              <input :value="panel.form.memoryApiKey" name="setup_memory_api_key" type="password" :placeholder="panel.state.memoryApiKeyPlaceholder" :disabled="!panel.state.memoryApiKeyEnabled" @input="emit('updateField', 'memory', 'apiKey', ($event.target as HTMLInputElement).value)">
            </label>
            <label :class="{ 'is-disabled': !panel.state.memoryApiKeyEnabled }">
              <span>API key env</span>
              <input :value="panel.form.memoryApiKeyEnv" name="setup_memory_api_key_env" :placeholder="panel.state.memoryEnvPlaceholder" :disabled="!panel.state.memoryApiKeyEnabled" @input="emit('updateField', 'memory', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
            </label>
            <label :class="{ 'is-disabled': !panel.state.memoryRemoteControlEnabled }">
              <span>Base URL</span>
              <input :value="panel.form.memoryBaseUrl" name="setup_memory_base_url" :placeholder="panel.state.memoryBasePlaceholder" :disabled="!panel.state.memoryRemoteControlEnabled" @input="emit('updateField', 'memory', 'baseUrl', ($event.target as HTMLInputElement).value)">
            </label>
          </div>
        </details>
        <button :class="panel.state.capabilitySaveButtonClass('memory_embedding')" @click="emit('saveMemory')">Save memory embedding</button>
      </div>

      <div class="setup-mini">
        <div class="setup-mini__head">
          <h4>Image generation</h4>
          <span class="setup-badge" :class="panel.state.capabilityBadgeTone('image_generation')">{{ panel.state.capabilityBadgeLabel('image_generation') }}</span>
        </div>
        <p class="setup-muted">{{ panel.state.imageStatusText }}</p>
        <SetupCommandBlock
          v-if="panel.state.imageEnvCommand"
          class="setup-warning__command setup-mini__env-command"
          :command="panel.state.imageEnvCommand"
          copy-label="Copy set image key command"
          @copy="emit('copy', $event)"
        />
        <SetupNeedList :items="panel.state.imageNeeds" label="Image needs" />
        <div v-if="panel.form.imageEnabled">
          <label>
            <span>Provider</span>
            <select :value="panel.form.imageProvider" name="setup_image_provider" @change="onImageProviderSelect">
              <option v-for="p in panel.options.imageProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
            </select>
          </label>
          <label>
            <span>Primary model</span>
            <input :value="panel.form.imagePrimary" name="setup_image_primary" @input="emit('updateField', 'image', 'primary', ($event.target as HTMLInputElement).value)">
          </label>
          <label>
            <span>API key</span>
            <input :value="panel.form.imageApiKey" name="setup_image_api_key" type="password" placeholder="leave blank to keep current" @input="emit('updateField', 'image', 'apiKey', ($event.target as HTMLInputElement).value)">
          </label>
          <label>
            <span>API key env</span>
            <input :value="panel.form.imageApiKeyEnv" name="setup_image_api_key_env" :placeholder="panel.options.imageSpec?.envKey || 'OPENROUTER_API_KEY'" @input="emit('updateField', 'image', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </label>
          <label>
            <span>Base URL</span>
            <input :value="panel.form.imageBaseUrl" name="setup_image_base_url" :placeholder="panel.options.imageSpec?.defaultBaseUrl || 'https://api.openai.com/v1'" @input="emit('updateField', 'image', 'baseUrl', ($event.target as HTMLInputElement).value)">
          </label>
        </div>
        <label class="setup-check">
          <input :checked="panel.form.imageEnabled" name="setup_image_enabled" type="checkbox" @change="emit('updateField', 'image', 'enabled', ($event.target as HTMLInputElement).checked)">
          <span>Enabled</span>
        </label>
        <button :class="panel.state.capabilitySaveButtonClass('image_generation')" @click="emit('saveImage')">Save image generation</button>
      </div>

      <div class="setup-mini">
        <div class="setup-mini__head">
          <h4>Audio</h4>
          <span class="setup-badge" :class="panel.state.audioBadgeTone">{{ panel.state.audioBadgeLabel }}</span>
        </div>
        <p class="setup-muted">{{ panel.state.audioStatusText }}</p>
        <div v-if="panel.form.audioEnabled">
          <label>
            <span>API key</span>
            <input :value="panel.form.audioApiKey" name="setup_audio_api_key" type="password" :placeholder="panel.state.audioKeyPlaceholder" @input="emit('updateField', 'audio', 'apiKey', ($event.target as HTMLInputElement).value)">
          </label>
          <label>
            <span>API key env</span>
            <input :value="panel.form.audioApiKeyEnv" name="setup_audio_api_key_env" placeholder="ELEVENLABS_API_KEY" @input="emit('updateField', 'audio', 'apiKeyEnv', ($event.target as HTMLInputElement).value)">
          </label>
        </div>
        <label class="setup-check">
          <input :checked="panel.form.audioEnabled" name="setup_audio_enabled" type="checkbox" @change="emit('updateField', 'audio', 'enabled', ($event.target as HTMLInputElement).checked)">
          <span>Enable voice &amp; audio tools (text-to-speech and speech-to-text via ElevenLabs).</span>
        </label>
        <button class="setup-btn" @click="emit('saveAudio')">Save audio</button>
      </div>
    </div>
  </section>
</template>
