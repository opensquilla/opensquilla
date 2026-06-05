<template>
  <section class="control-stage desktop-settings">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <h1 class="control-stage__title">Settings</h1>
        <p class="control-stage__subtitle">Local desktop runtime, router access, and search keys.</p>
      </div>
      <div class="control-stage__actions">
        <button class="btn btn--ghost" :disabled="loading" @click="loadSettings">
          <Icon name="refresh" :size="16" />
          Refresh
        </button>
        <button class="btn btn--primary desktop-settings__save" :disabled="saving || loading || !canManageDesktopSettings" @click="saveSettings">
          <Icon name="save" :size="16" />
          Save
        </button>
      </div>
    </header>

    <div v-if="!canManageDesktopSettings" class="desktop-settings__notice">
      Desktop settings are available only inside the OpenSquilla desktop app.
    </div>

    <div v-else class="desktop-settings__layout">
      <section class="desktop-panel desktop-panel--runtime">
        <header class="desktop-panel__head">
          <span class="desktop-panel__icon"><Icon name="monitor" :size="17" /></span>
          <div>
            <h2>Local runtime</h2>
            <p>The desktop app owns the gateway and serves the same Control UI locally.</p>
          </div>
        </header>
        <div class="desktop-settings__runtime-grid">
          <GatewayStatusBlock label="Gateway" :value="gatewayStatus" :hint="gatewayUrl" />
          <GatewayStatusBlock label="Runtime" value="Local" hint="Desktop-owned process" />
        </div>
      </section>

      <section class="desktop-panel">
        <header class="desktop-panel__head">
          <span class="desktop-panel__icon"><Icon name="agents" :size="17" /></span>
          <div>
            <h2>Router access</h2>
            <p>One key gives the agent router model access.</p>
          </div>
        </header>
        <div class="desktop-settings__fields">
          <ProviderSelector v-model="form.provider" @update:model-value="applyProviderDefaults" />
          <ApiKeyField
            v-model="form.apiKey"
            :placeholder="apiKeyConfigured ? 'Saved key will be kept' : 'sk-...'"
          />
          <details class="desktop-settings__advanced">
            <summary>Advanced endpoint</summary>
            <label class="desktop-field">
              <span>Base URL</span>
              <input v-model="form.baseUrl" autocomplete="off" />
            </label>
          </details>
        </div>
      </section>

      <section class="desktop-panel">
        <header class="desktop-panel__head">
          <span class="desktop-panel__icon"><Icon name="search" :size="17" /></span>
          <div>
            <h2>Search</h2>
            <p>Choose the web search engine available to agents.</p>
          </div>
        </header>
        <SearchProviderSelector v-model="form.searchProvider" />
        <ApiKeyField
          v-if="form.searchProvider === 'brave'"
          v-model="form.searchApiKey"
          label="Search API key"
          :placeholder="searchApiKeyConfigured ? 'Saved key will be kept' : 'BRAVE_SEARCH_API_KEY'"
        />
      </section>

      <aside class="desktop-settings__status">
        <div class="control-stat control-stat--static control-stat--accent">
          <span class="control-stat__label">Router key</span>
          <span class="control-stat__value">{{ apiKeyConfigured ? 'Set' : 'Missing' }}</span>
          <span class="control-stat__hint">{{ routerProviderLabel }}</span>
        </div>
        <div class="control-stat control-stat--static">
          <span class="control-stat__label">Search</span>
          <span class="control-stat__value">{{ searchStatusLabel }}</span>
          <span class="control-stat__hint">{{ searchHint }}</span>
        </div>
        <div class="control-stat control-stat--static">
          <span class="control-stat__label">Gateway log</span>
          <span class="control-stat__value">{{ gatewayLogLabel }}</span>
          <span class="control-stat__hint">{{ gatewayLogHint }}</span>
        </div>
        <button class="btn btn--ghost desktop-settings__reset" :disabled="saving" @click="resetSettings">
          Reset saved setup
        </button>
      </aside>

      <p v-if="error" class="desktop-settings__message desktop-settings__message--error">{{ error }}</p>
      <p v-else-if="saved" class="desktop-settings__message desktop-settings__message--saved">Saved. Restart the desktop app to apply runtime changes.</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef } from 'vue'
import Icon from '@/components/Icon.vue'
import ApiKeyField from '@/components/settings/ApiKeyField.vue'
import GatewayStatusBlock from '@/components/settings/GatewayStatusBlock.vue'
import ProviderSelector from '@/components/settings/ProviderSelector.vue'
import SearchProviderSelector from '@/components/settings/SearchProviderSelector.vue'
import { usePlatform, type GatewayStatus } from '@/platform'

type ProviderId = 'openrouter' | 'openai' | 'anthropic'
type SearchProviderId = 'duckduckgo' | 'brave'

const providerDefaults: Record<ProviderId, { model: string; baseUrl: string; label: string }> = {
  openrouter: { model: 'deepseek/deepseek-v4-pro', baseUrl: 'https://openrouter.ai/api/v1', label: 'OpenRouter' },
  openai: { model: 'gpt-4.1', baseUrl: 'https://api.openai.com/v1', label: 'OpenAI' },
  anthropic: { model: 'claude-sonnet-4-5', baseUrl: 'https://api.anthropic.com/v1', label: 'Anthropic' },
}

const platform = usePlatform()
const desktopSettings = platform.settings
const canManageDesktopSettings = platform.capabilities.canManageLocalApiKeys && Boolean(
  desktopSettings.getDesktopSettings &&
  desktopSettings.saveDesktopSettings &&
  desktopSettings.resetDesktopSettings
)
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const apiKeyConfigured = ref(false)
const searchApiKeyConfigured = ref(false)
const gateway = shallowRef<GatewayStatus | null>(null)
const form = reactive({
  provider: 'openrouter' as ProviderId,
  apiKey: '',
  model: providerDefaults.openrouter.model,
  baseUrl: providerDefaults.openrouter.baseUrl,
  searchProvider: 'duckduckgo' as SearchProviderId,
  searchApiKey: '',
})

const gatewayStatus = computed(() => gateway.value?.status || 'unknown')
const gatewayUrl = computed(() => gateway.value?.url || 'No active gateway')
const gatewayLogLabel = computed(() => gateway.value?.logPath ? 'Available' : 'Unavailable')
const gatewayLogHint = computed(() => gateway.value?.logPath || 'No local log path')
const routerProviderLabel = computed(() => providerDefaults[form.provider].label)
const searchStatusLabel = computed(() => {
  if (form.searchProvider === 'duckduckgo') return 'Ready'
  return searchApiKeyConfigured.value ? 'Set' : 'Missing'
})
const searchHint = computed(() => {
  return form.searchProvider === 'duckduckgo' ? 'DuckDuckGo' : 'Brave Search'
})

function providerId(value: string): ProviderId {
  if (value === 'openai' || value === 'anthropic') return value
  return 'openrouter'
}

function searchProviderId(value: string): SearchProviderId {
  return value === 'brave' ? 'brave' : 'duckduckgo'
}

function applyProviderDefaults(): void {
  const defaults = providerDefaults[providerId(form.provider)]
  form.model = defaults.model
  form.baseUrl = defaults.baseUrl
}

async function loadSettings(): Promise<void> {
  if (!canManageDesktopSettings || !desktopSettings.getDesktopSettings) {
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    const settings = await desktopSettings.getDesktopSettings()
    form.provider = providerId(settings.provider)
    form.model = settings.model
    form.baseUrl = settings.baseUrl
    form.searchProvider = searchProviderId(settings.searchProvider)
    form.apiKey = ''
    form.searchApiKey = ''
    apiKeyConfigured.value = settings.apiKeyConfigured
    searchApiKeyConfigured.value = settings.searchApiKeyConfigured
    gateway.value = settings.gateway
  } catch (nextError) {
    error.value = nextError instanceof Error ? nextError.message : String(nextError)
  } finally {
    loading.value = false
  }
}

async function saveSettings(): Promise<void> {
  if (!canManageDesktopSettings || !desktopSettings.saveDesktopSettings) return
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const settings = await desktopSettings.saveDesktopSettings({
      provider: form.provider,
      model: form.model,
      baseUrl: form.baseUrl,
      apiKey: form.apiKey,
      searchProvider: form.searchProvider,
      searchApiKey: form.searchApiKey,
    })
    form.apiKey = ''
    form.searchApiKey = ''
    apiKeyConfigured.value = settings.apiKeyConfigured
    searchApiKeyConfigured.value = settings.searchApiKeyConfigured
    gateway.value = settings.gateway
    saved.value = true
  } catch (nextError) {
    error.value = nextError instanceof Error ? nextError.message : String(nextError)
  } finally {
    saving.value = false
  }
}

async function resetSettings(): Promise<void> {
  if (!canManageDesktopSettings || !desktopSettings.resetDesktopSettings) return
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await desktopSettings.resetDesktopSettings()
    await loadSettings()
  } catch (nextError) {
    error.value = nextError instanceof Error ? nextError.message : String(nextError)
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.desktop-settings__layout {
  align-items: start;
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
}

.desktop-panel,
.desktop-settings__notice {
  animation: control-fade-up 360ms ease both;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: grid;
  gap: var(--sp-4);
  padding: var(--sp-4);
}

.desktop-panel--runtime {
  grid-column: 1;
}

.desktop-panel__head {
  align-items: flex-start;
  display: flex;
  gap: var(--sp-3);
}

.desktop-panel__head h2 {
  font-size: 1rem;
  font-weight: 760;
  margin: 0;
}

.desktop-panel__head p {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin: 4px 0 0;
}

.desktop-panel__icon {
  align-items: center;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  display: inline-flex;
  height: 34px;
  justify-content: center;
  width: 34px;
}

.desktop-settings__runtime-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.desktop-settings__fields {
  display: grid;
  gap: var(--sp-3);
}

.desktop-field {
  color: var(--text-muted);
  display: grid;
  font-size: var(--fs-xs);
  font-weight: 750;
  gap: 7px;
}

.desktop-field input,
.desktop-field select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  min-height: 40px;
  outline: none;
  padding: 0 var(--sp-3);
}

.desktop-field input:focus,
.desktop-field select:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
}

.desktop-settings__advanced {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--sp-3);
}

.desktop-settings__advanced summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-xs);
  font-weight: 750;
}

.desktop-settings__advanced .desktop-field {
  margin-top: var(--sp-3);
}

.desktop-settings__status {
  display: grid;
  gap: var(--sp-3);
  grid-column: 2;
  grid-row: 1 / span 3;
}

.desktop-settings__reset {
  justify-content: center;
  width: 100%;
}

.desktop-settings__message {
  grid-column: 1 / -1;
  font-size: var(--fs-sm);
  margin: 0;
}

.desktop-settings__message--error {
  color: var(--danger);
}

.desktop-settings__message--saved {
  color: var(--success);
}

.desktop-settings__save {
  box-shadow: 0 10px 24px color-mix(in srgb, var(--accent) 22%, transparent);
}

@media (max-width: 980px) {
  .desktop-settings__layout,
  .desktop-settings__status,
  .desktop-panel--runtime {
    grid-column: auto;
    grid-row: auto;
  }

  .desktop-settings__layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .desktop-settings__runtime-grid {
    grid-template-columns: 1fr;
  }
}
</style>
