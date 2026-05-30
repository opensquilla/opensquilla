<template>
  <section class="setup">
    <header class="setup__head">
      <div>
        <p class="setup__kicker">OpenSquilla setup</p>
        <h2>{{ hasSetupAction ? 'Action needed' : 'Ready to run' }}</h2>
      </div>
      <div class="setup__head-aside">
        <button type="button" class="setup__exit" aria-label="Exit setup and return to Overview" @click="router.push('/overview')">
          <span aria-hidden="true">&larr;</span><span>Exit setup</span>
        </button>
        <div class="setup__status" :class="hasSetupAction ? 'is-warn' : 'is-ok'">
          {{ hasSetupAction ? 'Action needed' : 'Ready' }}
        </div>
        <ul v-if="onboardingReasons.length > 0" class="setup-reasons" aria-label="Setup actions needed">
          <li v-for="(reason, i) in onboardingReasons" :key="i">{{ reason }}</li>
        </ul>
      </div>
    </header>

    <nav class="setup-stepper" aria-label="Setup steps">
      <button
        v-for="(s, idx) in STEPS"
        :key="s.id"
        class="setup-stepper__item"
        :class="{ 'is-active': step === s.id }"
        :aria-label="`${s.label}: ${stepStatus(s.id).label}`"
        @click="setStep(s.id)"
      >
        <span class="setup-stepper__num">{{ idx + 1 }}</span>
        <span class="setup-stepper__label">{{ s.label }}</span>
        <small class="setup-stepper__state" :class="stepStatus(s.id).tone">{{ stepStatus(s.id).label }}</small>
      </button>
    </nav>

    <div class="setup__body">
      <!-- Provider step -->
      <section v-if="step === 'provider'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Provider</h3>
          <p>{{ providerSummary }}</p>
        </header>
        <div class="setup-form">
          <label>
            <span>Provider</span>
            <select v-model="providerSelected" name="setup_provider" @change="onProviderChange">
              <option value="" disabled :selected="!providerSelected">Choose a provider</option>
              <option v-for="p in runtimeProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
            </select>
          </label>
          <div class="setup-provider-meta">
            <span>SquillaRouter tiers</span>
            <strong class="setup-provider-meta__badge" :class="routerSupportTone">{{ routerSupportText }}</strong>
          </div>
          <SetupNeedList :items="providerNeeds" label="Provider needs" />
          <div class="setup-provider-fields">
            <SetupField
              v-for="field in providerCoreFields"
              :key="field.name"
              :field="field"
              :value="providerFieldValue(field)"
              scope="provider"
              @update="(name, val) => providerFieldValues[name] = val"
            />
          </div>
          <details v-if="providerAdvancedFields.length > 0" :open="providerAdvancedOpen">
            <summary>Advanced provider connection</summary>
            <div class="setup-mini__advanced-body" aria-label="Provider connection">
              <SetupField
                v-for="field in providerAdvancedFields"
                :key="field.name"
                :field="field"
                :value="providerFieldValue(field)"
                scope="provider"
                @update="(name, val) => providerFieldValues[name] = val"
              />
            </div>
          </details>
          <div v-if="providerEnvMissing" class="setup-warning">
            <div>{{ providerEnvKey }} is not visible to this gateway process. Set it before starting or restarting the gateway, or paste an API key instead.</div>
            <div v-if="providerEnvCommand" class="setup-warning__command">
              <code>{{ providerEnvCommand }}</code>
              <button class="setup-cli__copy" type="button" :title="'Copy set provider key command'" :aria-label="'Copy set provider key command'" @click="copyCommand(providerEnvCommand)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
          </div>
          <div class="setup-actions">
            <button class="setup-btn setup-btn--primary" :disabled="!providerSelected" @click="saveProvider">Save Provider</button>
            <button class="setup-btn" :disabled="!providerSelected" @click="setStep('router')">Next</button>
          </div>
        </div>
      </section>

      <!-- Router step -->
      <section v-else-if="step === 'router'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Router Tiers</h3>
          <p>{{ routerSummary }}</p>
        </header>
        <div class="setup-router-toolbar">
          <label>
            <span>Mode</span>
            <select v-model="routerMode" name="setup_router_mode" :disabled="!hasSavedProvider">
              <option value="recommended">SquillaRouter</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <label>
            <span>Default text model</span>
            <select v-model="routerDefaultTier" name="setup_router_default_tier" :disabled="!hasSavedProvider">
              <option v-for="t in TEXT_TIERS" :key="t" :value="t">{{ tierLabel(t) }}</option>
            </select>
          </label>
        </div>
        <div v-if="hasSavedProvider" class="setup-tier-table" role="table">
          <div class="setup-tier-table__row is-head" role="row">
            <span>Tier</span><span>Provider</span><span>Model</span><span>Thinking</span><span>Image</span>
          </div>
          <div v-for="[name] in tierEntries" :key="name" class="setup-tier-table__row" role="row">
            <span><code>{{ name }}</code></span>
            <input v-model="tierValues[name].provider" :aria-label="`${name} provider`" :placeholder="`${name} provider`">
            <input v-model="tierValues[name].model" :aria-label="`${name} model`" :placeholder="`${name} model`">
            <select v-model="tierValues[name].thinkingLevel" :aria-label="`${name} thinking level`">
              <option v-for="v in ['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh']" :key="v" :value="v">{{ v || '-' }}</option>
            </select>
            <input v-model="tierValues[name].supportsImage" type="checkbox" :aria-label="`${name} supports image`">
          </div>
        </div>
        <div v-else class="setup-warning">Choose a provider first to preview and save SquillaRouter tiers.</div>
        <div class="setup-actions">
          <button class="setup-btn" @click="setStep('provider')">Back</button>
          <button class="setup-btn setup-btn--primary" :disabled="!hasSavedProvider" @click="saveRouter">Save Router</button>
          <button class="setup-btn" @click="setStep('channels')">Next</button>
        </div>
      </section>

      <!-- Channels step -->
      <section v-else-if="step === 'channels'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Channels</h3>
          <p>{{ channelRuntimeRows.length }} configured</p>
        </header>
        <div class="setup-channel-grid">
          <div class="setup-form">
            <label>
              <span>Channel type</span>
              <select v-model="channelType" name="setup_channel_type" @change="onChannelTypeChange">
                <option v-for="c in catalogChannels" :key="c.type" :value="c.type">{{ c.label }}</option>
              </select>
            </label>
            <SetupNeedList :items="channelSpec?.whatYouNeed" label="Channel needs" />
            <div class="setup-channel-fields">
              <SetupField
                v-for="field in channelSpecFields"
                :key="field.name"
                :field="field"
                :value="String(channelFieldValues[field.name] ?? field.default ?? '')"
                scope="channel"
                @update="(name, val) => channelFieldValues[name] = val"
              />
            </div>
            <div class="setup-actions">
              <button class="setup-btn setup-btn--primary" @click="saveChannel">Save Channel</button>
            </div>
          </div>
          <div class="setup-runtime">
            <h4>Runtime status</h4>
            <template v-if="channelRuntimeRows.length > 0">
              <div v-for="row in channelRuntimeRows" :key="row.name" class="setup-runtime__row" :class="row.connected === true ? 'is-ok' : 'is-warn'">
                <span>{{ row.name }}</span>
                <span>{{ row.type || '' }}</span>
                <strong>{{ row.connected === true ? 'Connected' : (row.status === 'stopped' ? 'Action needed' : row.status || 'connecting') }}</strong>
              </div>
            </template>
            <p v-else class="setup-muted">No channels configured.</p>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" @click="setStep('router')">Back</button>
          <button class="setup-btn" @click="setStep('extras')">Next</button>
        </div>
      </section>

      <!-- Extras step -->
      <section v-else-if="step === 'extras'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Capability Center</h3>
          <p>Web search &middot; Memory recall &middot; Image generation</p>
        </header>
        <div class="setup-extras">
          <!-- Search -->
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Web search</h4>
              <span class="setup-badge" :class="capabilityBadgeTone('search')">{{ capabilityBadgeLabel('search') }}</span>
            </div>
            <p class="setup-muted">{{ searchStatusText() }}</p>
            <div v-if="searchEnvCommand" class="setup-warning__command setup-mini__env-command">
              <code>{{ searchEnvCommand }}</code>
              <button class="setup-cli__copy" type="button" :title="'Copy set search key command'" :aria-label="'Copy set search key command'" @click="copyCommand(searchEnvCommand)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
            <SetupNeedList :items="searchNeeds" label="Search needs" />
            <label>
              <span>Provider</span>
              <select v-model="searchProvider" name="setup_search_provider" @change="onSearchProviderChange">
                <option v-for="p in searchProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
              </select>
            </label>
            <label>
              <span>Max results</span>
              <input v-model.number="searchMaxResults" name="setup_search_max_results" type="number" min="1" step="1" inputmode="numeric">
            </label>
            <div v-if="searchRequiresKey">
              <label :class="{ 'is-disabled': !searchRequiresKey }">
                <span>API key</span>
                <input v-model="searchApiKey" name="setup_search_api_key" type="password" placeholder="leave blank to keep current" :disabled="!searchRequiresKey">
              </label>
              <label :class="{ 'is-disabled': !searchRequiresKey }">
                <span>API key env</span>
                <input v-model="searchApiKeyEnv" name="setup_search_api_key_env" :placeholder="searchEnvPlaceholder" :disabled="!searchRequiresKey">
              </label>
            </div>
            <details :open="!!searchAdvancedOpen">
              <summary>Advanced search options</summary>
              <div class="setup-mini__advanced-body" aria-label="Search behavior">
                <label>
                  <span>HTTP proxy</span>
                  <input v-model="searchProxy" name="setup_search_proxy" placeholder="http://127.0.0.1:7890">
                </label>
                <label class="setup-check">
                  <input v-model="searchUseEnvProxy" name="setup_search_use_env_proxy" type="checkbox">
                  <span>Use environment proxy</span>
                </label>
                <label>
                  <span>Fallback policy</span>
                  <select v-model="searchFallbackPolicy" name="setup_search_fallback_policy">
                    <option value="off">Off</option>
                    <option value="network">Network retry</option>
                  </select>
                </label>
                <label class="setup-check">
                  <input v-model="searchDiagnostics" name="setup_search_diagnostics" type="checkbox">
                  <span>Diagnostics</span>
                </label>
              </div>
            </details>
            <button :class="capabilitySaveButtonClass('search')" @click="saveSearch">Save web search</button>
          </div>

          <!-- Memory -->
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Memory embedding</h4>
              <span class="setup-badge" :class="capabilityBadgeTone('memory_embedding')">{{ capabilityBadgeLabel('memory_embedding') }}</span>
            </div>
            <p class="setup-muted">{{ memoryStatusText }}</p>
            <div v-if="memoryEnvCommand" class="setup-warning__command setup-mini__env-command">
              <code>{{ memoryEnvCommand }}</code>
              <button class="setup-cli__copy" type="button" :title="'Copy set memory key command'" :aria-label="'Copy set memory key command'" @click="copyCommand(memoryEnvCommand)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
            <SetupNeedList :items="memoryNeeds" label="Memory needs" />
            <label>
              <span>Provider</span>
              <select v-model="memoryProvider" name="setup_memory_provider" @change="onMemoryProviderChange">
                <option v-for="p in memoryProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
              </select>
            </label>
            <label v-if="memoryLocalControlEnabled" :class="{ 'is-disabled': !memoryLocalControlEnabled }">
              <span>ONNX directory</span>
              <input v-model="memoryOnnxDir" name="setup_memory_onnx_dir" :placeholder="memoryOnnxPlaceholder" :disabled="!memoryLocalControlEnabled">
            </label>
            <details v-if="memoryRemoteControlEnabled || memoryApiKeyEnabled" :open="memoryRemoteOptionsOpen">
              <summary>{{ memoryRemoteOptionsSummary }}</summary>
              <div class="setup-mini__advanced-body" aria-label="Memory embedding connection">
                <label :class="{ 'is-disabled': !memoryRemoteControlEnabled }">
                  <span>Model</span>
                  <input v-model="memoryModel" name="setup_memory_model" :placeholder="memoryModelPlaceholder" :disabled="!memoryRemoteControlEnabled">
                </label>
                <label :class="{ 'is-disabled': !memoryApiKeyEnabled }">
                  <span>{{ memoryApiKeyLabel }}</span>
                  <input v-model="memoryApiKey" name="setup_memory_api_key" type="password" :placeholder="memoryApiKeyPlaceholder" :disabled="!memoryApiKeyEnabled">
                </label>
                <label :class="{ 'is-disabled': !memoryApiKeyEnabled }">
                  <span>API key env</span>
                  <input v-model="memoryApiKeyEnv" name="setup_memory_api_key_env" :placeholder="memoryEnvPlaceholder" :disabled="!memoryApiKeyEnabled">
                </label>
                <label :class="{ 'is-disabled': !memoryRemoteControlEnabled }">
                  <span>Base URL</span>
                  <input v-model="memoryBaseUrl" name="setup_memory_base_url" :placeholder="memoryBasePlaceholder" :disabled="!memoryRemoteControlEnabled">
                </label>
              </div>
            </details>
            <button :class="capabilitySaveButtonClass('memory_embedding')" @click="saveMemory">Save memory embedding</button>
          </div>

          <!-- Image -->
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Image generation</h4>
              <span class="setup-badge" :class="capabilityBadgeTone('image_generation')">{{ capabilityBadgeLabel('image_generation') }}</span>
            </div>
            <p class="setup-muted">{{ imageStatusText }}</p>
            <div v-if="imageEnvCommand" class="setup-warning__command setup-mini__env-command">
              <code>{{ imageEnvCommand }}</code>
              <button class="setup-cli__copy" type="button" :title="'Copy set image key command'" :aria-label="'Copy set image key command'" @click="copyCommand(imageEnvCommand)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
            <SetupNeedList :items="imageNeeds" label="Image needs" />
            <div v-if="imageEnabled">
              <label>
                <span>Provider</span>
                <select v-model="imageProvider" name="setup_image_provider" @change="onImageProviderChange">
                  <option v-for="p in imageProviders" :key="p.providerId" :value="p.providerId">{{ p.label }}</option>
                </select>
              </label>
              <label>
                <span>Primary model</span>
                <input v-model="imagePrimary" name="setup_image_primary">
              </label>
              <label>
                <span>API key</span>
                <input v-model="imageApiKey" name="setup_image_api_key" type="password" placeholder="leave blank to keep current">
              </label>
              <label>
                <span>API key env</span>
                <input v-model="imageApiKeyEnv" name="setup_image_api_key_env" :placeholder="imageSpec?.envKey || 'OPENROUTER_API_KEY'">
              </label>
              <label>
                <span>Base URL</span>
                <input v-model="imageBaseUrl" name="setup_image_base_url" :placeholder="imageSpec?.defaultBaseUrl || 'https://api.openai.com/v1'">
              </label>
            </div>
            <label class="setup-check">
              <input v-model="imageEnabled" name="setup_image_enabled" type="checkbox">
              <span>Enabled</span>
            </label>
            <button :class="capabilitySaveButtonClass('image_generation')" @click="saveImage">Save image generation</button>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" @click="setStep('channels')">Back</button>
          <button class="setup-btn" @click="setStep('finish')">Next</button>
        </div>
      </section>

      <!-- Finish step -->
      <section v-else-if="step === 'finish'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Finish</h3>
          <p>{{ status.configPath || '' }}</p>
        </header>
        <div class="setup-cli">
          <section v-if="fixCommands.length > 0" class="setup-cli__group" aria-label="Fix now">
            <div class="setup-cli__group-head"><h4>Fix now</h4></div>
            <div v-for="cmd in fixCommands" :key="cmd.label" class="setup-cli__row">
              <span class="setup-cli__label">{{ cmd.label }}</span>
              <code>{{ cmd.command }}</code>
              <button class="setup-cli__copy" type="button" :title="`Copy ${cmd.label} command`" :aria-label="`Copy ${cmd.label} command`" @click="copyCommand(cmd.command)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
          </section>
          <section class="setup-cli__group" aria-label="CLI handoff">
            <div class="setup-cli__group-head"><h4>CLI handoff</h4></div>
            <div v-for="cmd in handoffCommands" :key="cmd.label" class="setup-cli__row">
              <span class="setup-cli__label">{{ cmd.label }}</span>
              <code>{{ cmd.command }}</code>
              <button class="setup-cli__copy" type="button" :title="`Copy ${cmd.label} command`" :aria-label="`Copy ${cmd.label} command`" @click="copyCommand(cmd.command)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
          </section>
          <section class="setup-cli__group" aria-label="CLI recipes">
            <div class="setup-cli__group-head"><h4>CLI recipes</h4></div>
            <div v-for="cmd in recipeCommands" :key="cmd.label" class="setup-cli__row">
              <span class="setup-cli__label">{{ cmd.label }}</span>
              <code>{{ cmd.command }}</code>
              <button class="setup-cli__copy" type="button" :title="`Copy ${cmd.label} command`" :aria-label="`Copy ${cmd.label} command`" @click="copyCommand(cmd.command)">
                <Icon name="copy" :size="14" />
              </button>
            </div>
          </section>
        </div>
        <div class="setup-summary">
          <div><span>Provider</span><strong>{{ providerSummary }}</strong></div>
          <div><span>Model</span><strong>{{ modelSummary }}</strong></div>
          <div v-if="providerProxy"><span>Proxy</span><strong>{{ providerProxy }}</strong></div>
          <div><span>Router</span><strong>{{ routerSummary }}</strong></div>
          <div><span>Channels</span><strong>{{ String(status.channelCount || 0) }}</strong></div>
        </div>
        <div v-if="readinessEntries.length > 0" class="setup-readiness" aria-label="Onboarding readiness">
          <div v-if="requiredReadiness.length > 0" class="setup-readiness__group">
            <h4>Required setup</h4>
            <div v-for="[name, detail] in requiredReadiness" :key="name" class="setup-readiness__row" :class="readinessTone(detail, name)">
              <span>{{ detail.label || name }}</span>
              <strong>{{ readinessStatusLabel(detail, name) }}</strong>
              <small>{{ detail.required ? 'Required' : 'Optional' }}</small>
              <button v-if="setupStepForSection(name, detail)" type="button" class="setup-readiness__action" :aria-label="readinessActionAriaLabel(detail, name)" :title="readinessActionAriaLabel(detail, name)" @click="setStep(setupStepForSection(name, detail)!)">
                {{ readinessActionLabel(detail, name) }}
              </button>
              <em v-if="detail.detail" class="setup-readiness__detail">{{ detail.detail }}</em>
            </div>
          </div>
          <div v-if="optionalReadiness.length > 0" class="setup-readiness__group">
            <h4>Optional capabilities</h4>
            <div v-for="[name, detail] in optionalReadiness" :key="name" class="setup-readiness__row" :class="readinessTone(detail, name)">
              <span>{{ detail.label || name }}</span>
              <strong>{{ readinessStatusLabel(detail, name) }}</strong>
              <small>{{ detail.required ? 'Required' : 'Optional' }}</small>
              <button v-if="setupStepForSection(name, detail)" type="button" class="setup-readiness__action" :aria-label="readinessActionAriaLabel(detail, name)" :title="readinessActionAriaLabel(detail, name)" @click="setStep(setupStepForSection(name, detail)!)">
                {{ readinessActionLabel(detail, name) }}
              </button>
              <em v-if="detail.detail" class="setup-readiness__detail">{{ detail.detail }}</em>
            </div>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" @click="setStep('extras')">Back</button>
          <button class="setup-btn" @click="loadData">Refresh</button>
          <button class="setup-btn setup-btn--primary" @click="router.push('/overview')">Open Overview</button>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import SetupField from '@/components/SetupField.vue'
import SetupNeedList from '@/components/SetupNeedList.vue'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = [
  { id: 'provider', label: 'Provider' },
  { id: 'router', label: 'Router Tiers' },
  { id: 'channels', label: 'Channels' },
  { id: 'extras', label: 'Capabilities' },
  { id: 'finish', label: 'Finish' },
] as const

const TEXT_TIERS = ['t0', 't1', 't2', 't3'] as const

const TIER_LABELS: Record<string, string> = {
  t0: 'Fast/simple (t0)',
  t1: 'Balanced default (t1)',
  t2: 'Stronger reasoning (t2)',
  t3: 'Max quality (t3)',
}

const READINESS_LABELS: Record<string, string> = {
  ok: 'Ready',
  optional: 'Optional',
  missing: 'Missing',
  degraded: 'Needs action',
  unknown: 'Check',
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderSpec {
  providerId: string
  label: string
  runtimeSupported?: boolean
  routerSupported?: boolean
  fields?: FieldSpec[]
  whatYouNeed?: string[]
  envKey?: string
  requiresApiKey?: boolean
  defaultBaseUrl?: string
  defaultModel?: string
}

interface FieldSpec {
  name: string
  label: string
  type?: string
  required?: boolean
  default?: string | boolean | number
  placeholder?: string
  description?: string
  secret?: boolean
  choices?: string[]
  showWhen?: Record<string, string>
}

interface ChannelSpec {
  type: string
  label: string
  fields?: FieldSpec[]
  whatYouNeed?: string[]
}

interface ChannelStatusRow {
  name: string
  type?: string
  connected?: boolean
  status?: string
  configured?: boolean
}

interface TierConfig {
  provider?: string
  model?: string
  thinkingLevel?: string
  thinking_level?: string
  supportsImage?: boolean
  supports_image?: boolean
}

interface SectionDetail {
  status?: string
  blocking?: boolean
  actionRequired?: boolean
  required?: boolean
  label?: string
  detail?: string
}

interface OnboardingStatus {
  needsOnboarding?: boolean
  hasConfig?: boolean
  llmSource?: string
  sectionDetails?: Record<string, SectionDetail>
  envRecoveryCommands?: Array<{ section?: string; command?: string; label?: string }>
  configPath?: string
  channelCount?: number
  searchConfigured?: boolean
  searchSource?: string
  searchEnvKey?: string
  imageGenerationEnabled?: boolean
  imageGenerationConfigured?: boolean
  imageGenerationSource?: string
  imageGenerationEnvKey?: string
  imageGenerationProvider?: string
  imageGenerationPrimary?: string
  memoryEmbeddingConfigured?: boolean
  memoryEmbeddingSource?: string
  memoryEmbeddingEnvKey?: string
  memoryEmbeddingProvider?: string
}

interface OnboardingCatalog {
  providers?: ProviderSpec[]
  routerProfiles?: {
    profiles?: Array<{ providerId: string; tiers?: Record<string, TierConfig> }>
    defaultTier?: string
  }
  channels?: ChannelSpec[]
  searchProviders?: ProviderSpec[]
  imageGenerationProviders?: ProviderSpec[]
  memoryEmbeddingProviders?: ProviderSpec[]
}

interface ConfigData {
  llm?: {
    provider?: string
    model?: string
    base_url?: string
    proxy?: string
    api_key_env?: string
    api_key?: string
    [key: string]: unknown
  }
  squilla_router?: {
    enabled?: boolean
    default_tier?: string
    tiers?: Record<string, TierConfig>
  }
  search_provider?: string
  search_api_key_env?: string
  search_max_results?: number
  search_proxy?: string
  search_use_env_proxy?: boolean
  search_fallback_policy?: string
  search_diagnostics?: boolean
  memory?: {
    embedding?: {
      provider?: string
      mode?: string
      remote?: {
        model?: string
        api_key?: string
        api_key_env?: string
        base_url?: string
      }
      local?: { onnx_dir?: string }
      ollama?: { model?: string; base_url?: string }
    }
  }
  image_generation?: {
    providers?: Record<string, { api_key_env?: string; base_url?: string }>
  }
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const router = useRouter()

const catalog = ref<OnboardingCatalog>({})
const status = ref<OnboardingStatus>({})
const config = ref<ConfigData>({})
const channelStatus = ref<{ channels: ChannelStatusRow[] }>({ channels: [] })
const step = ref('provider')
const hasAutoSelectedStep = ref(false)

// Provider
const providerSelected = ref('')
const providerFieldValues = ref<Record<string, unknown>>({})

// Router
const routerMode = ref('recommended')
const routerDefaultTier = ref('t1')
const tierValues = ref<Record<string, { provider: string; model: string; thinkingLevel: string; supportsImage: boolean }>>({})

// Channels
const channelType = ref('')
const channelFieldValues = ref<Record<string, unknown>>({})

// Search
const searchProvider = ref('duckduckgo')
const searchMaxResults = ref(5)
const searchApiKey = ref('')
const searchApiKeyEnv = ref('')
const searchProxy = ref('')
const searchUseEnvProxy = ref(false)
const searchFallbackPolicy = ref('off')
const searchDiagnostics = ref(false)

// Memory
const memoryProvider = ref('auto')
const memoryModel = ref('')
const memoryApiKey = ref('')
const memoryApiKeyEnv = ref('')
const memoryBaseUrl = ref('')
const memoryOnnxDir = ref('')

// Image
const imageProvider = ref('openrouter')
const imagePrimary = ref('')
const imageApiKey = ref('')
const imageApiKeyEnv = ref('')
const imageBaseUrl = ref('')
const imageEnabled = ref(true)

let pollTimer: ReturnType<typeof setInterval> | null = null

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(async () => {
  await loadData()
  selectInitialStep()
  startChannelPolling()
})

onUnmounted(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    const [cat, st, cfg, chStatus] = await Promise.all([
      rpc.call<OnboardingCatalog>('onboarding.catalog'),
      rpc.call<OnboardingStatus>('onboarding.status'),
      rpc.call<ConfigData>('config.get'),
      rpc.call<{ channels: ChannelStatusRow[] }>('channels.status').catch(() => ({ channels: [] })),
    ])
    catalog.value = cat || {}
    status.value = st || {}
    config.value = cfg || {}
    channelStatus.value = chStatus || { channels: [] }

    // Initialize form values from config
    initProviderFromConfig()
    initRouterFromConfig()
    initSearchFromConfig()
    initMemoryFromConfig()
    initImageFromConfig()
    initChannelsFromConfig()
  } catch (err) {
    console.warn('Failed to load setup catalog: ' + (err instanceof Error ? err.message : String(err)))
  }
}

function initProviderFromConfig() {
  const current = config.value.llm || {}
  const hasSaved = Boolean(current.provider) && status.value.hasConfig !== false
  if (hasSaved && current.provider) {
    providerSelected.value = current.provider
    // Pre-fill known field values
    const spec = runtimeProviders.value.find(p => p.providerId === current.provider)
    if (spec && spec.fields) {
      spec.fields.forEach(f => {
        const val = current[f.name as keyof typeof current]
        if (val !== undefined) providerFieldValues.value[f.name] = val
      })
    }
  }
}

function initRouterFromConfig() {
  const router = config.value.squilla_router || {}
  routerMode.value = router.enabled === false ? 'disabled' : 'recommended'
  routerDefaultTier.value = router.default_tier || 't1'

  // Initialize tier values
  const profile = routerProfiles.value.find(p => p.providerId === currentProvider.value)
  const tiers = Object.assign({}, profile?.tiers || {}, router.tiers || {})
  const newTiers: Record<string, { provider: string; model: string; thinkingLevel: string; supportsImage: boolean }> = {}
  Object.entries(tiers).forEach(([name, tier]) => {
    newTiers[name] = {
      provider: tier.provider || '',
      model: tier.model || '',
      thinkingLevel: tier.thinkingLevel || tier.thinking_level || '',
      supportsImage: tier.supportsImage || tier.supports_image || false,
    }
  })
  tierValues.value = newTiers
}

function initSearchFromConfig() {
  const cfg = config.value
  searchProvider.value = cfg.search_provider || searchProviders.value.find(p => p.providerId === 'duckduckgo')?.providerId || searchProviders.value[0]?.providerId || 'duckduckgo'
  searchMaxResults.value = cfg.search_max_results || 5
  searchApiKeyEnv.value = cfg.search_api_key_env || ''
  searchProxy.value = cfg.search_proxy || ''
  searchUseEnvProxy.value = cfg.search_use_env_proxy === true
  searchFallbackPolicy.value = cfg.search_fallback_policy || 'off'
  searchDiagnostics.value = cfg.search_diagnostics === true
}

function initMemoryFromConfig() {
  const current = config.value.memory?.embedding || {}
  const effective = current.provider || current.mode || 'auto'
  memoryProvider.value = effective
  const remote = current.remote || {}
  memoryModel.value = remote.model || ''
  memoryApiKeyEnv.value = remote.api_key_env || ''
  memoryBaseUrl.value = remote.base_url || ''
  const local = current.local || {}
  memoryOnnxDir.value = local.onnx_dir || ''
}

function initImageFromConfig() {
  const cfg = config.value
  const imageConfig = cfg.image_generation || {}
  const selected = status.value.imageGenerationProvider || (status.value.imageGenerationPrimary || '').split('/')[0] || imageProviders.value[0]?.providerId || 'openrouter'
  imageProvider.value = selected
  imagePrimary.value = status.value.imageGenerationPrimary || ''
  const providerConfig = (imageConfig.providers || {})[selected] || {}
  imageApiKeyEnv.value = providerConfig.api_key_env || ''
  imageBaseUrl.value = providerConfig.base_url || ''
  imageEnabled.value = status.value.imageGenerationEnabled !== false
}

function initChannelsFromConfig() {
  const channels = catalog.value.channels || []
  if (channels.length > 0 && !channelType.value) {
    channelType.value = channels[0].type
  }
}

async function loadChannelStatus() {
  try {
    channelStatus.value = await rpc.call<{ channels: ChannelStatusRow[] }>('channels.status')
  } catch {
    channelStatus.value = { channels: [] }
  }
}

function startChannelPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    if (step.value !== 'channels') return
    await loadChannelStatus()
  }, 5000)
}

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const currentProvider = computed(() => (config.value.llm || {}).provider || '')
const hasSavedProvider = computed(() => Boolean(currentProvider.value) && status.value.hasConfig !== false)

const runtimeProviders = computed(() => (catalog.value.providers || []).filter(p => p.runtimeSupported))
const catalogChannels = computed(() => catalog.value.channels || [])
const searchProviders = computed(() => (catalog.value.searchProviders || []).filter(p => p.runtimeSupported))
const imageProviders = computed(() => (catalog.value.imageGenerationProviders || []).filter(p => p.runtimeSupported))
const memoryProviders = computed(() => catalog.value.memoryEmbeddingProviders || [])
const routerProfiles = computed(() => catalog.value.routerProfiles?.profiles || [])

const providerSpec = computed(() => runtimeProviders.value.find(p => p.providerId === providerSelected.value) || null)
const providerFields = computed(() => providerSpec.value?.fields || [])
const providerCoreFields = computed(() => providerFields.value.filter(f => !isProviderAdvancedField(f)))
const providerAdvancedFields = computed(() => providerFields.value.filter(f => isProviderAdvancedField(f)))

const providerSummary = computed(() => {
  if (!hasSavedProvider.value) return 'not configured'
  const spec = runtimeProviders.value.find(p => p.providerId === currentProvider.value)
  return spec?.label || currentProvider.value
})

const routerSupportText = computed(() => {
  if (!providerSpec.value) return 'choose provider'
  return providerSpec.value.routerSupported === true ? 'SquillaRouter ready' : 'Direct only'
})

const routerSupportTone = computed(() => {
  if (!providerSpec.value) return 'is-neutral'
  return providerSpec.value.routerSupported === true ? 'is-ready' : 'is-direct'
})

const providerNeeds = computed(() => {
  if (!providerSpec.value) return ['Choose a provider to see required fields.']
  return providerSpec.value.whatYouNeed || []
})

const providerAdvancedOpen = computed(() => {
  return providerAdvancedFields.value.some(f => {
    if (f.required) return true
    const val = String(providerFieldValues.value[f.name] || '').trim()
    const def = String(f.default || '').trim()
    if (def) return val !== def
    return val.length > 0
  })
})

const providerEnvMissing = computed(() => status.value.llmSource === 'missing_env')
const providerEnvKey = computed(() => (config.value.llm || {}).api_key_env || 'the selected API key environment variable')
const providerEnvCommand = computed(() => envRecoveryCommand('llm'))
const searchEnvCommand = computed(() => envRecoveryCommand('search'))
const memoryEnvCommand = computed(() => envRecoveryCommand('memory_embedding'))
const imageEnvCommand = computed(() => envRecoveryCommand('image_generation'))

const routerSummary = computed(() => {
  if (!hasSavedProvider.value) return 'choose a provider first'
  return routerMode.value === 'disabled' ? 'disabled' : 'SquillaRouter'
})

const tierEntries = computed(() => {
  return Object.entries(tierValues.value).filter(([name]) => TEXT_TIERS.includes(name as typeof TEXT_TIERS[number]) || name === 'image_model')
})

const channelSpec = computed(() => catalogChannels.value.find(c => c.type === channelType.value) || null)
const channelSpecFields = computed(() => channelSpec.value?.fields || [])
const channelRuntimeRows = computed(() => (channelStatus.value.channels || []).filter(row => row.configured !== false))

const modelSummary = computed(() => {
  if (!hasSavedProvider.value) return 'not configured'
  return (config.value.llm || {}).model || 'SquillaRouter defaults'
})

const providerProxy = computed(() => {
  if (!hasSavedProvider.value) return ''
  return ((config.value.llm || {}).proxy || '').trim()
})

const searchSpec = computed(() => searchProviders.value.find(p => p.providerId === searchProvider.value) || searchProviders.value[0] || null)
const searchRequiresKey = computed(() => searchSpec.value?.requiresApiKey === true)
const searchEnvPlaceholder = computed(() => searchRequiresKey.value ? (searchSpec.value?.envKey || 'SEARCH_API_KEY') : 'not required for this provider')
const searchAdvancedOpen = computed(() => searchProxy.value || searchUseEnvProxy.value || searchFallbackPolicy.value !== 'off' || searchDiagnostics.value)
const searchNeeds = computed(() => credentialNeedList(searchSpec.value?.whatYouNeed, searchApiKeyEnv.value || searchSpec.value?.envKey))

const memorySpec = computed(() => memoryProviders.value.find(p => p.providerId === memoryProvider.value) || memoryProviders.value[0] || null)
const memoryRemoteControlEnabled = computed(() => ['auto', 'openai', 'openai-compatible', 'ollama'].includes(memoryProvider.value))
const memoryApiKeyEnabled = computed(() => memoryProvider.value === 'auto' || memorySpec.value?.requiresApiKey === true)
const memoryLocalControlEnabled = computed(() => memoryProvider.value === 'local')
const memoryRemoteOptionsOpen = computed(() => memoryProvider.value !== 'auto' || Boolean(memoryModel.value || memoryApiKey.value || memoryApiKeyEnv.value || memoryBaseUrl.value))
const memoryRemoteOptionsSummary = computed(() => memoryProvider.value === 'auto' ? 'Remote fallback options' : 'Connection options')
const memoryModelPlaceholder = computed(() => memoryProvider.value === 'ollama' ? 'nomic-embed-text' : (memoryRemoteControlEnabled.value ? 'text-embedding-3-small' : 'not used by this provider'))
const memoryBasePlaceholder = computed(() => memoryProvider.value === 'ollama' ? 'http://localhost:11434' : (memoryRemoteControlEnabled.value ? 'https://api.openai.com/v1' : 'not used by this provider'))
const memoryOnnxPlaceholder = computed(() => memoryLocalControlEnabled.value ? 'models/bge-onnx' : 'only for bundled local provider')
const memoryApiKeyLabel = computed(() => memoryProvider.value === 'auto' ? 'Fallback API key' : 'API key')
const memoryApiKeyPlaceholder = computed(() => memoryApiKeyEnabled.value ? 'leave blank to keep current' : 'not required for this provider')
const memoryEnvPlaceholder = computed(() => memorySpec.value?.envKey || 'OPENAI_API_KEY')
const memoryNeeds = computed(() => memoryNeedList(memorySpec.value, memoryProvider.value, memoryApiKeyEnv.value || memorySpec.value?.envKey))
const memoryStatusText = computed(() => _memoryEmbeddingStatusText(memoryProvider.value))

const imageSpec = computed(() => imageProviders.value.find(p => p.providerId === imageProvider.value) || imageProviders.value[0] || null)
const imageNeeds = computed(() => {
  if (!imageEnabled.value) return ['No key required while image generation is disabled.']
  return credentialNeedList(imageSpec.value?.whatYouNeed, imageApiKeyEnv.value || imageSpec.value?.envKey)
})
const imageStatusText = computed(() => _imageGenerationStatusText())

const hasSetupAction = computed(() => {
  if (status.value.needsOnboarding) return true
  const details = status.value.sectionDetails || {}
  return Object.values(details).some(detail => (
    detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'
  ))
})

const onboardingReasons = computed(() => {
  if (!hasSetupAction.value) return []
  const reasons: string[] = []
  const llm = config.value.llm || {}
  if (providerEnvMissing.value) {
    reasons.push(`${providerEnvKey.value} is not visible`)
  } else if (!llm.provider || !llm.model) {
    reasons.push('Connect a model provider')
  }
  const details = status.value.sectionDetails || {}
  Object.entries(details).forEach(([name, detail]) => {
    if (!detail.blocking && !detail.actionRequired) return
    if ((name === 'llm' || name === 'provider') && detail.status === 'missing') {
      if (!reasons.includes('Connect a model provider')) reasons.push('Connect a model provider')
      return
    }
    if ((name === 'llm' || name === 'provider') && reasons.length) return
    const reason = setupActionReason(name, detail)
    if (!reasons.includes(reason)) reasons.push(reason)
  })
  return reasons.length ? reasons : ['Review setup sections for pending actions']
})

const configCliArg = computed(() => {
  const path = status.value.configPath
  return path ? ` --config ${shellArg(path)}` : ''
})

const envRecoveryCommands = computed(() => {
  const cmds = Array.isArray(status.value.envRecoveryCommands) ? status.value.envRecoveryCommands : []
  return cmds
    .filter(entry => entry && entry.command)
    .map(entry => ({ label: entry.label || 'Set environment key', command: entry.command || '' }))
})

const fixCommands = computed(() => {
  if (!envRecoveryCommands.value.length) return []
  return [
    ...envRecoveryCommands.value,
    { label: 'Restart gateway after env fix', command: `opensquilla gateway restart${configCliArg.value}` },
  ]
})

const handoffCommands = computed(() => [
  { label: 'Guided CLI', command: `opensquilla onboard --if-needed${configCliArg.value}` },
  { label: 'Check status', command: `opensquilla onboard status${configCliArg.value}` },
])

const recipeCommands = computed(() => [
  { label: 'Provider options', command: `opensquilla onboard catalog providers${configCliArg.value}` },
  { label: 'Router tiers', command: `opensquilla onboard catalog router${configCliArg.value}` },
  { label: 'Search options', command: `opensquilla onboard catalog search${configCliArg.value}` },
  { label: 'Channel options', command: `opensquilla onboard catalog channels${configCliArg.value}` },
  { label: 'Image options', command: `opensquilla onboard catalog image${configCliArg.value}` },
  { label: 'Memory options', command: `opensquilla onboard catalog memory${configCliArg.value}` },
])

const readinessEntries = computed(() => Object.entries(status.value.sectionDetails || {}))
const requiredReadiness = computed(() => readinessEntries.value.filter(([, d]) => d.required))
const optionalReadiness = computed(() => readinessEntries.value.filter(([, d]) => !d.required))

// ---------------------------------------------------------------------------
// Step logic
// ---------------------------------------------------------------------------

function selectInitialStep() {
  if (hasAutoSelectedStep.value) return
  step.value = initialStepFromStatus()
  hasAutoSelectedStep.value = true
}

function initialStepFromStatus(): string {
  const details = status.value.sectionDetails || {}
  const sectionSteps: [string, string][] = [
    ['llm', 'provider'],
    ['router', 'router'],
    ['channels', 'channels'],
    ['search', 'extras'],
    ['image_generation', 'extras'],
    ['memory_embedding', 'extras'],
  ]
  const entry = sectionSteps.find(([section]) => {
    const detail = details[section] || {}
    return detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'
  })
  if (entry) return entry[1]
  if (status.value.needsOnboarding === false) return 'finish'
  return 'provider'
}

function setStep(newStep: string) {
  if (!newStep || newStep === step.value) return
  step.value = newStep
}

function stepStatus(stepId: string): { label: string; tone: string } {
  const currentProvider = (config.value.llm || {}).provider || ''
  const hasSavedProvider = Boolean(currentProvider) && status.value.hasConfig !== false
  if (stepId === 'provider') {
    if (providerEnvMissing.value) return { label: 'Needs action', tone: 'is-warn' }
    return detailStepStatus((status.value.sectionDetails || {}).llm || (status.value.sectionDetails || {}).provider)
  }
  if (stepId === 'router' && !hasSavedProvider) {
    return { label: 'Provider first', tone: 'is-muted' }
  }
  if (stepId === 'router') return detailStepStatus((status.value.sectionDetails || {}).router)
  if (stepId === 'channels') return detailStepStatus((status.value.sectionDetails || {}).channels)
  if (stepId === 'extras') {
    return aggregateStepStatus(['search', 'image_generation', 'memory_embedding'])
  }
  if (stepId === 'finish') {
    return hasSetupAction.value
      ? { label: 'Review', tone: 'is-warn' }
      : { label: 'Ready', tone: 'is-ok' }
  }
  return { label: 'Review', tone: 'is-muted' }
}

function detailStepStatus(detail?: SectionDetail): { label: string; tone: string } {
  if (!detail) return { label: 'Review', tone: 'is-muted' }
  if (stepDetailNeedsAction(detail)) return { label: 'Needs action', tone: 'is-warn' }
  if (detail.status === 'ok') return { label: 'Ready', tone: 'is-ok' }
  return { label: READINESS_LABELS[detail.status || ''] || 'Optional', tone: 'is-muted' }
}

function aggregateStepStatus(sectionNames: string[]): { label: string; tone: string } {
  const details = status.value.sectionDetails || {}
  const entries = sectionNames.map(name => details[name]).filter(Boolean) as SectionDetail[]
  if (entries.some(detail => stepDetailNeedsAction(detail))) {
    return { label: 'Needs action', tone: 'is-warn' }
  }
  if (entries.length && entries.every(detail => detail.status === 'ok')) {
    return { label: 'Ready', tone: 'is-ok' }
  }
  return { label: 'Optional', tone: 'is-muted' }
}

function stepDetailNeedsAction(detail: SectionDetail): boolean {
  return Boolean(detail && (detail.blocking || detail.actionRequired || detail.status === 'missing' || detail.status === 'degraded'))
}

function setupActionReason(name: string, detail: SectionDetail): string {
  const missingEnvPrefix = 'env key not visible: '
  const detailText = String(detail.detail || '')
  if (detailText.startsWith(missingEnvPrefix)) {
    const envKey = detailText.slice(missingEnvPrefix.length).trim()
    if (envKey) return `${envKey} is not visible`
  }
  return `${detail.label || name} setup needed`
}

// ---------------------------------------------------------------------------
// Provider helpers
// ---------------------------------------------------------------------------

function isProviderAdvancedField(field: FieldSpec): boolean {
  if (['base_url', 'proxy'].includes(field.name)) return true
  if (field.name === 'model') {
    return providerSpec.value?.routerSupported === true && field.required !== true
  }
  return false
}

function providerFieldValue(field: FieldSpec): string {
  const name = field.name
  const current = config.value.llm || {}
  if (providerFieldValues.value[name] !== undefined) {
    return String(providerFieldValues.value[name] || '')
  }
  if (name === 'model') return String(current.model || field.default || '')
  if (name === 'base_url') return String(current.base_url || field.default || '')
  if (name === 'proxy') return String(current.proxy || '')
  if (name === 'api_key_env') return String(current.api_key_env || (current.api_key ? '' : field.default || ''))
  return ''
}

function onProviderChange() {
  providerFieldValues.value = {}
  const spec = providerSpec.value
  if (spec && spec.fields) {
    spec.fields.forEach(f => {
      providerFieldValues.value[f.name] = f.default ?? ''
    })
  }
}

function envRecoveryCommand(section: string): string {
  const commands = Array.isArray(status.value.envRecoveryCommands) ? status.value.envRecoveryCommands : []
  const entry = commands.find(e => e && e.section === section && e.command)
  return entry ? (entry.command ?? '') : ''
}

// ---------------------------------------------------------------------------
// Channel helpers
// ---------------------------------------------------------------------------

function onChannelTypeChange() {
  channelFieldValues.value = {}
  const spec = channelSpec.value
  if (spec && spec.fields) {
    spec.fields.forEach(f => {
      channelFieldValues.value[f.name] = f.default ?? ''
    })
  }
}

// ---------------------------------------------------------------------------
// Search / Memory / Image helpers
// ---------------------------------------------------------------------------

function onSearchProviderChange() {
  const spec = searchSpec.value
  if (spec && spec.requiresApiKey) {
    searchApiKeyEnv.value = spec.envKey || ''
  } else {
    searchApiKeyEnv.value = ''
    searchApiKey.value = ''
  }
}

function onMemoryProviderChange() {
  const spec = memorySpec.value
  if (memoryApiKeyEnabled.value && spec) {
    if (!memoryApiKeyEnv.value) memoryApiKeyEnv.value = spec.envKey || ''
  }
}

function onImageProviderChange() {
  const spec = imageSpec.value
  if (spec) {
    imageApiKeyEnv.value = spec.requiresApiKey ? (spec.envKey || '') : ''
    if (!imagePrimary.value) imagePrimary.value = spec.defaultModel || ''
    if (!imageBaseUrl.value) imageBaseUrl.value = spec.defaultBaseUrl || ''
  }
}

function credentialNeedList(items: string[] | undefined, envKey: string | undefined): string[] {
  const key = String(envKey || '').trim()
  if (!key) return items || []
  return (items || []).map(item => {
    if (/API key via [A-Z0-9_]+ or a one-time paste\./.test(item)) {
      return `API key via ${key} or a one-time paste.`
    }
    if (/Remote embedding API key or [A-Z0-9_]+ reference\./.test(item)) {
      return `Remote embedding API key or ${key} reference.`
    }
    return item
  })
}

function memoryNeedList(spec: ProviderSpec | null, providerId: string, envKey: string | undefined): string[] {
  const items = (spec?.whatYouNeed || []).filter(Boolean)
  if (providerId === 'auto' && !String(envKey || '').trim()) {
    return items.filter(item => !/remote fallback credentials/i.test(item))
  }
  return spec?.requiresApiKey ? credentialNeedList(items, envKey || spec.envKey) : items
}

// ---------------------------------------------------------------------------
// Status text helpers
// ---------------------------------------------------------------------------

function searchStatusText(): string {
  if (!config.value.search_provider) {
    return 'Web search is off until a provider is selected.'
  }
  if (status.value.searchConfigured === true) {
    return 'Web search is ready for new turns.'
  }
  if (status.value.searchSource === 'missing_env') {
    return _missingEnvStatusText('Web search', status.value.searchEnvKey, 'Web search is selected but still needs a visible provider key.')
  }
  return 'Web search is selected but still needs a visible provider key.'
}

function _imageGenerationStatusText(): string {
  if (status.value.imageGenerationEnabled === false) {
    return 'Image generation is hidden from agents until this capability is enabled.'
  }
  if (status.value.imageGenerationConfigured === true) {
    if (status.value.imageGenerationSource === 'llm_fallback') {
      return 'Image generation will be available in new turns using the same provider key.'
    }
    return 'Image generation will be available in new turns once the gateway has the visible key.'
  }
  if (status.value.imageGenerationSource === 'missing_env') {
    return _missingEnvStatusText('Image generation', status.value.imageGenerationEnvKey, 'Image generation is enabled but still needs a visible provider key before agents can use it.')
  }
  return 'Image generation is enabled but still needs a visible provider key before agents can use it.'
}

function _memoryEmbeddingStatusText(providerId = ''): string {
  const current = config.value.memory?.embedding || {}
  const savedProvider = current.provider || current.mode || status.value.memoryEmbeddingProvider || 'auto'
  const provider = providerId || savedProvider
  if (provider === 'none') {
    return 'Keyword search stays available; embeddings are disabled.'
  }
  if (provider === 'local') {
    return 'Uses local BGE embeddings; no remote key is needed.'
  }
  if (provider === 'ollama') {
    return 'Uses your Ollama server; no API key is needed.'
  }
  if (provider === 'auto') {
    return 'Local-first memory search; optional remote fallback can be configured.'
  }
  if (provider === savedProvider && status.value.memoryEmbeddingConfigured === true) {
    return 'Remote memory embeddings are configured for new turns.'
  }
  if (provider === savedProvider && status.value.memoryEmbeddingSource === 'missing_env') {
    return _missingEnvStatusText('Remote memory embeddings', status.value.memoryEmbeddingEnvKey, 'Remote memory embeddings need a visible provider key before they can run.')
  }
  return 'Remote memory embeddings need a visible provider key before they can run.'
}

function _missingEnvStatusText(capability: string, envKey: string | undefined, fallback: string): string {
  const key = String(envKey || '').trim()
  if (!key) return fallback
  return `${capability} is selected, but $${key} is not visible to the gateway.`
}

// ---------------------------------------------------------------------------
// Readiness helpers
// ---------------------------------------------------------------------------

function capabilityBadgeTone(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return _readinessTone(detail, name)
}

function capabilityBadgeLabel(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return _readinessStatusLabel(detail, name)
}

function capabilitySaveButtonClass(name: string): string {
  const detail = (status.value.sectionDetails || {})[name] || {}
  return detail.blocking || detail.actionRequired
    ? 'setup-btn setup-btn--primary'
    : 'setup-btn'
}

function _readinessTone(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'is-warn'
  if (detail.blocking || detail.actionRequired) return 'is-warn'
  if (detail.status === 'ok') return 'is-ok'
  return 'is-muted'
}

function _readinessStatusLabel(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'Provider first'
  if (detail.blocking || detail.actionRequired) return 'Needs action'
  return READINESS_LABELS[detail.status || ''] || 'Optional'
}

function _routerNeedsProvider(detail: SectionDetail, name: string): boolean {
  return name === 'router' && detail.status === 'ok' && detail.detail === 'uses SquillaRouter after provider setup'
}

function readinessTone(detail: SectionDetail, name: string): string {
  return _readinessTone(detail, name)
}

function readinessStatusLabel(detail: SectionDetail, name: string): string {
  return _readinessStatusLabel(detail, name)
}

function readinessActionLabel(detail: SectionDetail, name: string): string {
  if (_routerNeedsProvider(detail, name)) return 'Choose provider'
  if (detail.blocking || detail.actionRequired) return 'Fix'
  if (detail.status === 'ok') return 'Review'
  return 'Configure'
}

function readinessActionAriaLabel(detail: SectionDetail, name: string): string {
  const label = detail.label || name.replace(/_/g, ' ')
  if (_routerNeedsProvider(detail, name)) return `Choose provider for ${label}`
  return `${readinessActionLabel(detail, name)} ${label}`
}

function setupStepForSection(name: string, detail: SectionDetail = {}): string | null {
  if (_routerNeedsProvider(detail, name)) return 'provider'
  if (name === 'llm' || name === 'provider') return 'provider'
  if (name === 'router') return 'router'
  if (name === 'channels') return 'channels'
  if (name === 'search' || name === 'image_generation' || name === 'memory_embedding') return 'extras'
  return null
}

// ---------------------------------------------------------------------------
// Save actions
// ---------------------------------------------------------------------------

async function saveProvider() {
  if (!providerSelected.value) {
    console.warn('Choose a provider before saving.')
    return
  }
  try {
    const payload: Record<string, unknown> = { providerId: providerSelected.value }
    Object.entries(providerFieldValues.value).forEach(([k, v]) => {
      if (v !== '' && v !== undefined) payload[camel(k)] = v
    })
    await rpc.call('onboarding.provider.configure', payload)
    await loadData()
    if (providerEnvMissing.value) {
      console.warn(`${providerEnvKey.value} is not visible to this gateway process.`)
      step.value = 'provider'
      return
    }
    console.warn('Provider saved.')
    step.value = 'router'
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveRouter() {
  if (!hasSavedProvider.value) {
    console.warn('Choose a provider before saving router tiers.')
    return
  }
  const tiers: Record<string, Record<string, unknown>> = {}
  Object.entries(tierValues.value).forEach(([name, tier]) => {
    tiers[name] = {
      provider: tier.provider,
      model: tier.model,
      thinkingLevel: tier.thinkingLevel,
      supportsImage: tier.supportsImage,
    }
  })
  try {
    await rpc.call('onboarding.router.configure', {
      mode: routerMode.value,
      defaultTier: routerDefaultTier.value,
      tiers,
    })
    console.warn('Router saved.')
    await loadData()
    step.value = 'channels'
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveChannel() {
  const entry: Record<string, unknown> = { type: channelType.value }
  Object.entries(channelFieldValues.value).forEach(([k, v]) => {
    if (v !== '' && v !== undefined) entry[k] = v
  })
  try {
    await rpc.call('onboarding.channel.probe', { entry })
    await rpc.call('onboarding.channel.upsert', { entry })
    console.warn('Channel saved. Restart required.')
    await loadChannelStatus()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveSearch() {
  const params: Record<string, unknown> = { providerId: searchProvider.value }
  if (searchApiKey.value) params.apiKey = searchApiKey.value
  if (searchApiKeyEnv.value) params.apiKeyEnv = searchApiKeyEnv.value
  params.maxResults = searchMaxResults.value
  if (searchProxy.value) params.proxy = searchProxy.value
  params.useEnvProxy = searchUseEnvProxy.value
  params.fallbackPolicy = searchFallbackPolicy.value
  params.diagnostics = searchDiagnostics.value
  try {
    await rpc.call('onboarding.search.configure', params)
    console.warn('Search saved.')
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveMemory() {
  const params: Record<string, unknown> = { providerId: memoryProvider.value }
  if (memoryModel.value) params.model = memoryModel.value
  if (memoryApiKey.value) params.apiKey = memoryApiKey.value
  if (memoryApiKeyEnv.value) params.apiKeyEnv = memoryApiKeyEnv.value
  if (memoryBaseUrl.value) params.baseUrl = memoryBaseUrl.value
  if (memoryOnnxDir.value) params.onnxDir = memoryOnnxDir.value
  try {
    const res = await rpc.call<{ entry?: { remote?: { api_key_env?: string; api_key?: string } }; restartRequired?: boolean }>('onboarding.memory_embedding.configure', params)
    const remote = res?.entry?.remote || {}
    if (!_toastEnvReferenceSave('Memory embedding', remote.api_key_env, '', remote.api_key ?? '', res?.restartRequired)) {
      console.warn('Memory embedding saved. Restart required.')
    }
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

async function saveImage() {
  const params: Record<string, unknown> = { providerId: imageProvider.value }
  params.enabled = imageEnabled.value
  if (imagePrimary.value) params.primary = imagePrimary.value
  if (imageApiKey.value) params.apiKey = imageApiKey.value
  if (imageApiKeyEnv.value) params.apiKeyEnv = imageApiKeyEnv.value
  if (imageBaseUrl.value) params.baseUrl = imageBaseUrl.value
  try {
    const res = await rpc.call<{ entry?: { api_key_env?: string; api_key_source?: string; api_key?: string }; restartRequired?: boolean }>('onboarding.imageGeneration.configure', params)
    const entry = res?.entry || {}
    if (!_toastEnvReferenceSave('Image generation', entry.api_key_env, entry.api_key_source, entry.api_key, res?.restartRequired)) {
      console.warn('Image generation saved.')
    }
    await loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

function _toastEnvReferenceSave(
  surface: string,
  envKey: string | undefined,
  keySource = '',
  hasInlineKey = '',
  restartRequired = false,
): boolean {
  const key = String(envKey || '').trim()
  if (!key || hasInlineKey) return false
  if (keySource === 'missing_env' || restartRequired) {
    console.warn(`${surface} saved $${key}. Start or restart the gateway with that variable set.`)
    return true
  }
  console.warn(`${surface} saved $${key} reference. Keep it set for gateway restarts.`)
  return true
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function tierLabel(tier: string): string {
  return TIER_LABELS[tier] || tier || 'Balanced default (t1)'
}

function camel(name: string): string {
  return String(name || '').replace(/_([a-z])/g, (_, c) => c.toUpperCase())
}

function shellArg(value: string): string {
  const text = String(value || '')
  if (/^[A-Za-z0-9_@%+=:,./~-]+$/.test(text)) return text
  return `'${text.replace(/'/g, `'\''`)}'`
}

async function copyCommand(command: string) {
  if (!command) return
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(command)
    } else {
      const ta = document.createElement('textarea')
      ta.value = command
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (!ok) throw new Error('Copy command failed')
    }
    console.warn('Copied command')
  } catch (err) {
    console.warn('Copy failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}
</script>

<style scoped>
.setup {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.setup__head {
  align-items: flex-start;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.setup__head h2 {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  margin: var(--sp-2) 0 0;
}

.setup__kicker {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  margin: 0;
  text-transform: uppercase;
}

.setup__head-aside {
  align-items: flex-end;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.setup__exit {
  align-items: center;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-sm);
  gap: 6px;
  padding: 6px 12px;
}

.setup__exit:hover {
  border-color: var(--accent);
  color: var(--text);
}

.setup__status {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 12px;
  text-transform: uppercase;
}

.setup__status.is-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup__status.is-warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.setup-reasons {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  list-style: none;
  margin: 0;
  padding: 0;
  text-align: right;
}

.setup-reasons li::before {
  color: var(--warn);
  content: "\2022";
  margin-right: 6px;
}

/* Stepper */
.setup-stepper {
  display: flex;
  gap: 2px;
}

.setup-stepper__item {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-3);
}

.setup-stepper__item.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
  color: var(--text);
}

.setup-stepper__num {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 50%;
  display: flex;
  font-size: 12px;
  font-weight: 600;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.setup-stepper__item.is-active .setup-stepper__num {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.setup-stepper__label {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.setup-stepper__state {
  font-size: 10px;
}

.setup-stepper__state.is-ok { color: var(--ok); }
.setup-stepper__state.is-warn { color: var(--warn); }
.setup-stepper__state.is-muted { color: var(--text-dim); }

/* Panel */
.setup-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.setup-panel__head {
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--sp-4);
  padding-bottom: var(--sp-3);
}

.setup-panel__head h3 {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-1);
}

.setup-panel__head p {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
}

/* Form */
.setup-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.setup-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.setup-form label > span:first-child {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.setup-form input,
.setup-form select,
.setup-form textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

.setup-form input:focus,
.setup-form select:focus,
.setup-form textarea:focus {
  border-color: var(--accent);
  outline: none;
}

.setup-form input:disabled,
.setup-form select:disabled {
  opacity: 0.5;
}

.setup-check {
  align-items: center;
  flex-direction: row !important;
  gap: 8px !important;
}

.setup-check input {
  width: auto;
}

/* Provider meta */
.setup-provider-meta {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
}

.setup-provider-meta span {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

.setup-provider-meta__badge {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
}

.setup-provider-meta__badge.is-ready {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup-provider-meta__badge.is-direct {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

.setup-provider-meta__badge.is-neutral {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

/* Provider fields */
.setup-provider-fields {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* Warning */
.setup-warning {
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--border));
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  padding: var(--sp-3);
}

.setup-warning__command {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}

.setup-warning__command code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 4px 8px;
}

/* Actions */
.setup-actions {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}

.setup-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 8px 16px;
}

.setup-btn:hover {
  border-color: var(--accent);
}

.setup-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.setup-btn--primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.setup-btn--primary:hover {
  background: color-mix(in srgb, var(--accent) 90%, #000);
}

/* Router toolbar */
.setup-router-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

/* Tier table */
.setup-tier-table {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  margin-bottom: var(--sp-4);
  overflow: hidden;
}

.setup-tier-table__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 80px 1fr 1fr 120px 60px;
  padding: 8px 12px;
}

.setup-tier-table__row.is-head {
  background: var(--bg-elevated);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-tier-table__row:last-child {
  border-bottom: none;
}

.setup-tier-table__row input,
.setup-tier-table__row select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 12px;
  padding: 4px 8px;
}

/* Channel grid */
.setup-channel-grid {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: 1fr 280px;
  margin-bottom: var(--sp-4);
}

.setup-runtime {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
}

.setup-runtime h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.setup-runtime__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  justify-content: space-between;
  padding: 6px 0;
}

.setup-runtime__row.is-ok strong {
  color: var(--ok);
}

.setup-runtime__row.is-warn strong {
  color: var(--warn);
}

.setup-muted {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

/* Extras */
.setup-extras {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.setup-mini {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
}

.setup-mini__head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.setup-mini__head h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0;
}

.setup-badge {
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
}

.setup-badge.is-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup-badge.is-warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.setup-badge.is-muted {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

.setup-mini__advanced-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.setup-mini__env-command {
  margin-bottom: var(--sp-2);
}

/* CLI */
.setup-cli {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.setup-cli__group {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.setup-cli__group-head {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: var(--sp-3) var(--sp-4);
}

.setup-cli__group-head h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0;
}

.setup-cli__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  padding: 8px 12px;
}

.setup-cli__row:last-child {
  border-bottom: none;
}

.setup-cli__label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  min-width: 100px;
  text-transform: uppercase;
}

.setup-cli__row code {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.setup-cli__copy {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 28px;
  justify-content: center;
  width: 28px;
}

.setup-cli__copy:hover {
  background: var(--bg);
  border-color: var(--border);
  color: var(--text);
}

/* Summary */
.setup-summary {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  margin-bottom: var(--sp-4);
}

.setup-summary > div {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-3);
}

.setup-summary span {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-summary strong {
  color: var(--text);
  font-size: var(--fs-sm);
}

/* Readiness */
.setup-readiness {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.setup-readiness__group h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.setup-readiness__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 1fr auto auto auto;
  padding: 8px 0;
}

.setup-readiness__row.is-ok strong { color: var(--ok); }
.setup-readiness__row.is-warn strong { color: var(--warn); }
.setup-readiness__row.is-muted strong { color: var(--text-dim); }

.setup-readiness__row span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.setup-readiness__row strong {
  font-size: var(--fs-sm);
}

.setup-readiness__row small {
  color: var(--text-dim);
  font-size: 10px;
}

.setup-readiness__action {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 8px;
}

.setup-readiness__action:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.setup-readiness__detail {
  color: var(--text-dim);
  font-size: 11px;
  font-style: normal;
  grid-column: 1 / -1;
}

/* Need list */
.setup-need-list {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--fs-sm);
  padding: var(--sp-3);
}

.setup-need-list span {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-need-list ul {
  color: var(--text-muted);
  list-style: none;
  margin: var(--sp-1) 0 0;
  padding: 0;
}

.setup-need-list li::before {
  color: var(--accent);
  content: "\2022";
  margin-right: 6px;
}

/* Responsive */
@media (max-width: 980px) {
  .setup-extras {
    grid-template-columns: 1fr;
  }

  .setup-channel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .setup-stepper {
    flex-wrap: wrap;
  }

  .setup-stepper__item {
    flex: 1 1 100px;
  }

  .setup-tier-table__row {
    grid-template-columns: 60px 1fr 1fr 100px 50px;
  }
}
</style>
