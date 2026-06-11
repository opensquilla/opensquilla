<template>
  <div class="cfg-panel">
    <!-- Section rail: drives the form view; hidden while editing raw YAML -->
    <nav
      v-show="mode === 'form'"
      class="cfg-rail"
      role="tablist"
      aria-label="Config sections"
      aria-orientation="vertical"
    >
      <button
        v-for="t in TABS"
        :key="t.id"
        class="cfg-rail-tab"
        :class="{ 'is-active': activeTab === t.id }"
        type="button"
        role="tab"
        :aria-selected="activeTab === t.id ? 'true' : 'false'"
        :aria-controls="'cfg-tab-' + t.id"
        @click="activeTab = t.id"
      >{{ t.label }}</button>
    </nav>

    <div class="cfg-main">
      <div class="cfg-toolbar">
        <div class="cfg-mode-toggle" role="group" aria-label="Editor mode">
          <button
            class="cfg-mode-btn"
            :class="{ 'is-active': mode === 'form' }"
            type="button"
            @click="setMode('form')"
          >Form</button>
          <button
            class="cfg-mode-btn"
            :class="{ 'is-active': mode === 'yaml' }"
            type="button"
            @click="setMode('yaml')"
          >YAML</button>
        </div>
        <label v-show="mode === 'form'" class="cfg-search-wrap" for="cfg-search">
          <span class="cfg-search-icon" aria-hidden="true">
            <Icon name="search" :size="14" />
          </span>
          <input
            id="cfg-search"
            v-model="searchText"
            class="cfg-search-input"
            type="search"
            placeholder="Search keys & values…"
            autocomplete="off"
          >
        </label>
        <span class="cfg-toolbar__spacer"></span>
        <button class="cfg-btn cfg-btn--ghost" type="button" title="Open guided setup" @click="emit('open-setup')">
          <Icon name="config" :size="16" />
          <span>Guided setup</span>
        </button>
        <button class="cfg-btn cfg-btn--ghost" type="button" title="Reload config" @click="reload">
          <Icon name="refresh" :size="16" />
          <span>Reload</span>
        </button>
        <button class="cfg-btn cfg-btn--ghost" type="button" title="Save config" @click="save">
          <Icon name="check" :size="16" />
          <span>Save</span>
        </button>
      </div>

      <div class="cfg-scroll">
        <!-- Form view -->
        <div v-show="mode === 'form'" id="cfg-form-view">
          <div
            v-for="t in TABS"
            :id="'cfg-tab-' + t.id"
            :key="t.id"
            class="tab-panel"
            role="tabpanel"
            :style="{ display: activeTab === t.id ? '' : 'none' }"
          >
            <template v-if="entriesForTab(t).length === 0">
              <div class="cfg-empty-state">No matching fields</div>
            </template>
            <template v-else>
              <section
                v-for="group in groupEntries(entriesForTab(t))"
                :key="group.id"
                class="cfg-settings-group"
                :aria-label="group.title"
              >
                <header class="cfg-settings-group-header">
                  <div>
                    <h3 class="cfg-settings-group-title">{{ group.title }}</h3>
                    <div class="cfg-settings-group-meta">{{ group.entries.length }} {{ group.entries.length === 1 ? 'field' : 'fields' }}</div>
                  </div>
                </header>
                <div class="cfg-settings-fields">
                  <div
                    v-for="[k, v] in group.entries"
                    :key="k"
                    class="config-field"
                    :class="{
                      'config-field--object': isObject(v),
                      'field-dirty': k in dirty,
                      'config-field--invalid': k in invalidJson,
                      'config-field--stacked': k.length > 24,
                    }"
                  >
                    <div class="config-field__label-row">
                      <label class="form-label" :for="'cfg-input-' + safeId(k)">{{ k }}</label>
                      <button
                        type="button"
                        class="cfg-help-btn"
                        :aria-label="'Help for ' + k"
                        tabindex="0"
                        @click.stop="toggleTooltip($event, k)"
                        @focus="showTooltip($event, k)"
                        @blur="hideTooltipDelayed($event, k)"
                        @mouseenter="showTooltip($event, k)"
                        @mouseleave="hideTooltipDelayed($event, k)"
                      >
                        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">
                          <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.25"/>
                          <path d="M5.9 6.1c.2-1.1 1.1-1.85 2.2-1.85 1.2 0 2.05.8 2.05 1.85 0 .85-.45 1.3-1.3 1.85-.65.4-1 .8-1 1.55v.35" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/>
                          <circle cx="8" cy="11.6" r="0.7" fill="currentColor"/>
                        </svg>
                      </button>
                    </div>

                    <!-- Boolean -->
                    <template v-if="typeof v === 'boolean'">
                      <label class="cfg-switch">
                        <input
                          :id="'cfg-input-' + safeId(k)"
                          type="checkbox"
                          :checked="currentValue(k, v) as boolean"
                          :aria-label="k"
                          @change="onFieldChange(k, ($event.target as HTMLInputElement).checked, 'boolean')"
                        >
                        <span class="cfg-switch-track" aria-hidden="true"><span class="cfg-switch-thumb"></span></span>
                        <span class="cfg-switch-text">{{ (currentValue(k, v) as boolean) ? 'Enabled' : 'Disabled' }}</span>
                      </label>
                    </template>

                    <!-- Number -->
                    <template v-else-if="typeof v === 'number'">
                      <input
                        :id="'cfg-input-' + safeId(k)"
                        class="input cfg-input-number"
                        type="number"
                        :value="currentValue(k, v) as number"
                        @input="onFieldChange(k, Number(($event.target as HTMLInputElement).value), 'number')"
                      >
                    </template>

                    <!-- Object -->
                    <template v-else-if="isObject(v)">
                      <details class="cfg-object-field" :open="k in dirty || k in invalidJson">
                        <summary>
                          <span class="cfg-object-summary">{{ objectSummary(currentValue(k, v)) }}</span>
                          <span class="cfg-object-action">Edit</span>
                        </summary>
                        <textarea
                          :id="'cfg-input-' + safeId(k)"
                          class="input cfg-input-json"
                          :rows="jsonRows(k, v)"
                          :aria-describedby="'cfg-input-' + safeId(k) + '-error'"
                          :value="jsonDrafts[k] ?? JSON.stringify(currentValue(k, v), null, 2)"
                          @input="onJsonInput(k, ($event.target as HTMLTextAreaElement).value, v)"
                        />
                        <div
                          :id="'cfg-input-' + safeId(k) + '-error'"
                          class="cfg-json-error"
                          :class="{ hidden: !(k in invalidJson) }"
                        >Invalid JSON</div>
                      </details>
                    </template>

                    <!-- String -->
                    <template v-else>
                      <div class="cfg-input-row">
                        <input
                          :id="'cfg-input-' + safeId(k)"
                          class="input cfg-input-text"
                          :type="passwordVisible[k] ? 'text' : (isSensitive(k) ? 'password' : 'text')"
                          :value="String(currentValue(k, v) ?? '')"
                          @input="onFieldChange(k, ($event.target as HTMLInputElement).value, 'string')"
                        >
                        <button
                          v-if="isSensitive(k)"
                          class="btn btn--sm"
                          type="button"
                          @click="passwordVisible[k] = !passwordVisible[k]"
                        >{{ passwordVisible[k] ? 'Hide' : 'Show' }}</button>
                      </div>
                    </template>
                  </div>
                </div>
              </section>
            </template>
          </div>
        </div>

        <!-- YAML view -->
        <div v-show="mode === 'yaml'" id="cfg-yaml-view">
          <div class="cfg-yaml-shell">
            <textarea
              id="cfg-yaml-area"
              v-model="yamlDraft"
              class="input cfg-yaml-area"
              spellcheck="false"
              @input="yamlDirty = yamlDraft !== yamlText"
            />
          </div>
        </div>

        <!-- Sticky save bar -->
        <div
          v-show="stickyBarVisible"
          id="cfg-stickybar"
          class="cfg-stickybar"
          aria-live="polite"
        >
          <div class="cfg-stickybar__row">
            <span class="cfg-stickybar__pulse" aria-hidden="true"></span>
            <span class="cfg-stickybar__count"><strong>{{ stickyBarCount }}</strong> changes pending</span>
            <span class="cfg-stickybar__sep" aria-hidden="true">·</span>
            <button
              class="cfg-stickybar__diff-toggle"
              type="button"
              :aria-expanded="diffOpen ? 'true' : 'false'"
              :aria-controls="'cfg-stickybar-diff'"
              :class="{ 'is-open': diffOpen }"
              @click="diffOpen = !diffOpen"
            >
              <span>View diff</span>
              <span class="cfg-stickybar__chevron" aria-hidden="true">
                <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false">
                  <path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </span>
            </button>
            <span class="cfg-stickybar__spacer"></span>
            <button class="cfg-btn cfg-btn--ghost cfg-stickybar__btn" type="button" @click="discard">Discard</button>
            <button class="cfg-btn cfg-btn--primary cfg-stickybar__btn" type="button" @click="save">
              <Icon name="check" :size="14" />
              <span>Save</span>
            </button>
          </div>
          <div
            v-show="diffOpen"
            id="cfg-stickybar-diff"
            class="cfg-stickybar__diff"
          >
            <template v-if="mode === 'yaml' && yamlDirty">
              <div class="cfg-diff-row">
                <span class="cfg-diff-key">YAML</span>
                <span class="cfg-diff-old">loaded config</span>
                <span class="cfg-diff-arrow">-></span>
                <span class="cfg-diff-new">unsaved draft</span>
              </div>
            </template>
            <template v-else>
              <div v-for="[k, d] in Object.entries(dirty)" :key="k" class="cfg-diff-row">
                <span class="cfg-diff-key">{{ k }}</span>
                <span class="cfg-diff-old">{{ summariseDiffValue(d.old) }}</span>
                <span class="cfg-diff-arrow">-></span>
                <span class="cfg-diff-new">{{ summariseDiffValue(d.new) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Tooltip -->
    <div
      v-show="activeTooltipKey !== null"
      id="cfg-tooltip"
      ref="tooltipRef"
      class="cfg-tooltip"
      role="tooltip"
      :data-placement="tooltipPlacement"
      :style="tooltipStyle"
    >
      <div class="cfg-tooltip__body">{{ activeTooltipKey ? helpFor(activeTooltipKey) : '' }}</div>
      <span class="cfg-tooltip__arrow" aria-hidden="true" :style="tooltipArrowStyle"></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import { useConfigTooltip } from '@/composables/config/useConfigTooltip'
import { useDocumentEvent } from '@/composables/useDocumentEvent'
import Icon from '@/components/Icon.vue'
import { summariseDiffValue } from '@/utils/config/diff'
import { objectSummary, searchBlob } from '@/utils/config/summary'
import { objToYaml } from '@/utils/config/yaml'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TabDef {
  id: string
  label: string
  prefixes: string[]
}

interface DirtyEntry {
  old: unknown
  new: unknown
}

const emit = defineEmits<{
  'open-setup': []
}>()

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TABS: TabDef[] = [
  { id: 'core', label: 'Core', prefixes: ['general', 'auth', 'host', 'port', 'version', 'debug', 'control_ui', 'diagnostics'] },
  { id: 'ai', label: 'AI & Agents', prefixes: ['provider', 'model', 'agent', 'llm', 'skills', 'squilla_router', 'prompt_cache', 'thinking'] },
  { id: 'memory', label: 'Memory', prefixes: ['memory'] },
  { id: 'communication', label: 'Communication', prefixes: ['channel', 'telegram', 'slack', 'discord', 'email', 'messaging'] },
  { id: 'automation', label: 'Automation', prefixes: ['cron', 'scheduler'] },
  { id: 'infrastructure', label: 'Infrastructure', prefixes: ['log', 'storage', 'db', 'cache', 'search'] },
]

const HELP: Record<string, string> = {
  host: 'Network interface the gateway binds to. Defaults to 127.0.0.1 (loopback). Use 0.0.0.0 to expose on all interfaces — opt-in only, never on an untrusted network.',
  port: 'TCP port for the ASGI gateway. Default 18791. Pick a free port; the WebSocket and REST endpoints share it.',
  debug: 'Security-sensitive developer mode. Auth scope expansion can take effect immediately for new connections; Starlette debug, uvicorn log level, and some startup wiring need a gateway restart. Keep it off in shared deployments.',
  diagnostics_enabled: 'Default standard diagnostics mode at gateway startup. Raw turn-call capture stays off unless OPENSQUILLA_TURN_CALL_LOG=1 or the running gateway is switched with opensquilla diagnostics on --raw.',
  log_file_enabled: 'Writes gateway debug.log records for operator troubleshooting. This is separate from raw turn-call capture, which requires OPENSQUILLA_TURN_CALL_LOG=1 or opensquilla diagnostics on --raw.',
  log_level: 'Minimum gateway file log level. OPENSQUILLA_LOG_LEVEL can override this at runtime.',
  log_file_max_bytes: 'Maximum debug.log size before rotation. Set to 0 to disable rotation in the stdlib handler.',
  log_file_backup_count: 'Number of rotated debug.log backups to retain.',
  'agent_token_saving.tool_result_projection_max_inline_chars': 'Maximum inline size for canonical tokenjuice tool-result projections. Raw tool output is transient and is not stored.',
  'squilla_router.enabled': 'Turn the ML-powered tier router on or off. When off, every request uses the default model regardless of complexity.',
  'squilla_router.rollout_phase': 'Rollout stage for new router model versions. Higher phases enable more aggressive routing decisions.',
  'squilla_router.require_router_runtime': 'When true, the gateway fails fast on startup if the router cannot initialize (missing ONNX runtime, model files, etc.). Set false to fall back silently.',
  'memory.embedding': 'Long-term memory embedding provider. Defaults to local bundled BGE in auto mode when available; remote embeddings require explicit memory embedding configuration.',
  'memory.embedding.provider': 'Canonical memory embedding provider: auto, none, local, openai/openai-compatible, or ollama. This is independent from the chat LLM provider.',
  'memory.embedding.remote.api_key': 'API key for the memory embedding endpoint. This does not inherit the chat/OpenRouter key in auto mode.',
  'memory.embedding.remote.base_url': 'OpenAI-compatible API root for memory indexing, for example https://api.openai.com/v1. The provider appends /embeddings.',
  'memory.embedding.local.onnx_dir': 'Optional ONNX directory for a custom local embedding model. Leave empty to use the bundled BGE-small model.',
  'memory.retrieval_mode': 'Memory retrieval mode. "hybrid" uses vectors when an embedding provider is available; "fts_only" disables vectors.',
  'sandbox.sandbox': 'Runtime sandbox switch. The out-of-box posture keeps this false; use opensquilla sandbox on|bypass|full to change sandbox and permission defaults together.',
  'sandbox.security_grading': 'Risk grading and approval gate for tool actions. Keep this paired with sandbox.sandbox unless using the sandbox CLI posture commands.',
  'permissions.default_mode': 'Default owner/operator permission mode: bypass is the out-of-box local posture, off keeps sandboxed execution, on uses host execution with approvals, and full bypasses sensitive-path gates too.',
  'prompt_cache.mode': 'Anthropic prompt cache control. "auto" (default) lets the provider decide; "on" forces caching; "off" disables it entirely.',
  context_budget_tokens: 'Soft cap on the assembled prompt size. When exceeded, the configured overflow policy kicks in (summarize, truncate, or refuse).',
  context_overflow_policy: '"auto_summarize" compacts older history via a small LLM; "hard_truncate" drops oldest turns; "refuse" rejects the turn with a stable error.',
  auth_mode: 'Gateway auth scheme. "token" requires a static bearer token; "none" is open (loopback only); other modes per deployment.',
}

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

const rpc = useRpcStore()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const configData = ref<Record<string, unknown>>({})
const yamlText = ref('')
const yamlDraft = ref('')
const yamlDirty = ref(false)
const dirty = ref<Record<string, DirtyEntry>>({})
const invalidJson = ref<Record<string, boolean>>({})
const jsonDrafts = ref<Record<string, string>>({})
const mode = ref<'form' | 'yaml'>('form')
const activeTab = ref('core')
const searchText = ref('')
const diffOpen = ref(false)
const passwordVisible = ref<Record<string, boolean>>({})

const {
  activeTooltipKey,
  tooltipRef,
  tooltipPlacement,
  tooltipStyle,
  tooltipArrowStyle,
  helpFor,
  showTooltip,
  toggleTooltip,
  hideTooltipDelayed,
  onDocClickForTooltip,
  onDocKeyForTooltip,
} = useConfigTooltip(HELP)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const stickyBarVisible = computed(() => {
  const keys = Object.keys(dirty.value)
  const yamlDirtyVisible = mode.value === 'yaml' && yamlDirty.value
  return keys.length > 0 || yamlDirtyVisible
})

const stickyBarCount = computed(() => {
  if (mode.value === 'yaml' && yamlDirty.value) return 1
  return Object.keys(dirty.value).length
})

// Unsaved edits in either editor mode; the modal host consults this before closing.
const hasUnsavedChanges = computed(() => Object.keys(dirty.value).length > 0 || yamlDirty.value)

defineExpose({ hasUnsavedChanges })

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
})

useDocumentEvent('click', onDocClickForTooltip, true)
useDocumentEvent('keydown', onDocKeyForTooltip, true)

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    const data = await rpc.call<Record<string, unknown>>('config.get')
    configData.value = data || {}
    yamlText.value = objToYaml(configData.value)
    if (!yamlDirty.value) yamlDraft.value = yamlText.value
    invalidJson.value = {}
    jsonDrafts.value = {}
  } catch (err) {
    console.warn('Failed to load config: ' + (err instanceof Error ? err.message : String(err)))
  }
}

// ---------------------------------------------------------------------------
// Mode & Actions
// ---------------------------------------------------------------------------

function setMode(m: 'form' | 'yaml') {
  mode.value = m
}

function reload() {
  dirty.value = {}
  invalidJson.value = {}
  jsonDrafts.value = {}
  yamlDraft.value = ''
  yamlDirty.value = false
  diffOpen.value = false
  loadData()
}

function discard() {
  if (Object.keys(dirty.value).length === 0 && !yamlDirty.value) return
  dirty.value = {}
  invalidJson.value = {}
  jsonDrafts.value = {}
  yamlDraft.value = ''
  yamlDirty.value = false
  diffOpen.value = false
  loadData()
}

async function save() {
  if (mode.value === 'yaml') {
    try {
      const res = await rpc.call<{ restartRequired?: boolean }>('config.apply', { config_yaml: yamlDraft.value })
      console.warn(res?.restartRequired
        ? 'Config applied. Gateway restart required for the change to take effect.'
        : 'Config applied')
      dirty.value = {}
      invalidJson.value = {}
      jsonDrafts.value = {}
      yamlDirty.value = false
      yamlDraft.value = ''
      loadData()
    } catch (err) {
      console.warn('Apply failed: ' + (err instanceof Error ? err.message : String(err)))
    }
  } else {
    if (Object.keys(invalidJson.value).length > 0) {
      console.warn('Fix invalid JSON before saving')
      return
    }
    const patches = Object.fromEntries(Object.entries(dirty.value).map(([k, v]) => [k, v.new]))
    if (Object.keys(patches).length === 0) {
      console.warn('No changes to save')
      return
    }
    try {
      const res = await rpc.call<{ restartRequired?: boolean }>('config.patch', { patches })
      console.warn(res?.restartRequired
        ? 'Config saved. Gateway restart required for the change to take effect.'
        : 'Config saved')
      dirty.value = {}
      invalidJson.value = {}
      jsonDrafts.value = {}
      loadData()
    } catch (err) {
      console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
    }
  }
}

// ---------------------------------------------------------------------------
// Form rendering helpers
// ---------------------------------------------------------------------------

function entriesForTab(tab: TabDef): [string, unknown][] {
  const st = searchText.value.toLowerCase()
  return Object.entries(configData.value).filter(([k, v]) => {
    const lk = k.toLowerCase()
    const matchesTab = tab.prefixes.some(p => lk.startsWith(p + '.') || lk === p || lk.startsWith(p + '_'))
    const matchesSearch = !st || lk.includes(st) || searchBlob(v).includes(st)
    return matchesTab && matchesSearch
  })
}

function groupEntries(entries: [string, unknown][]): { id: string; title: string; entries: [string, unknown][] }[] {
  const groups = new Map<string, { id: string; title: string; entries: [string, unknown][] }>()
  entries.forEach(([k, v]) => {
    const id = groupIdForKey(k, v)
    if (!groups.has(id)) groups.set(id, { id, title: groupTitle(id), entries: [] })
    groups.get(id)!.entries.push([k, v])
  })
  return Array.from(groups.values())
}

function groupIdForKey(k: string, v: unknown): string {
  if (k.includes('.')) return k.split('.')[0]
  if (v && typeof v === 'object') return k
  return 'general'
}

function groupTitle(id: string): string {
  if (id === 'general') return 'General'
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase())
}

function currentValue(key: string, original: unknown): unknown {
  return key in dirty.value ? dirty.value[key].new : original
}

function isObject(v: unknown): boolean {
  return typeof v === 'object' && v !== null
}

function isSensitive(k: string): boolean {
  return /key|token|secret|password|api_key/i.test(k)
}

function jsonRows(k: string, v: unknown): number {
  const jsonStr = k in jsonDrafts.value ? jsonDrafts.value[k] : JSON.stringify(currentValue(k, v), null, 2)
  const lines = jsonStr.split('\n').length
  return Math.min(Math.max(lines + 1, 4), 12)
}

function onFieldChange(key: string, newVal: unknown, type: string) {
  const oldVal = configData.value[key]
  if (newVal === oldVal || JSON.stringify(newVal) === JSON.stringify(oldVal)) {
    delete dirty.value[key]
    if (type === 'json') delete jsonDrafts.value[key]
  } else {
    dirty.value[key] = { old: oldVal, new: newVal }
  }
}

function onJsonInput(key: string, text: string, _original: unknown) {
  jsonDrafts.value[key] = text
  try {
    const newVal = JSON.parse(text)
    invalidJson.value[key] = false
    delete invalidJson.value[key]
    onFieldChange(key, newVal, 'json')
  } catch {
    invalidJson.value[key] = true
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function safeId(s: string): string {
  return String(s).replace(/[^a-zA-Z0-9_-]+/g, '-')
}
</script>

<style scoped>
.cfg-panel {
  display: flex;
  flex: 1;
  min-height: 0;
  min-width: 0;
}

/* Section rail */
.cfg-rail {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 200px;
  flex-shrink: 0;
  padding: var(--sp-3);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}

.cfg-rail-tab {
  background: transparent;
  border: none;
  border-left: 2px solid transparent;
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  text-align: left;
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
}

.cfg-rail-tab:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.cfg-rail-tab.is-active {
  background: var(--bg-elevated);
  border-left-color: var(--accent);
  color: var(--text);
}

.cfg-rail-tab:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

/* Main column */
.cfg-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.cfg-toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.cfg-toolbar__spacer {
  flex: 1;
}

.cfg-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-4);
}

/* Mode toggle */
.cfg-mode-toggle {
  display: inline-flex;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.cfg-mode-btn {
  background: transparent;
  border: none;
  padding: 6px 14px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}

.cfg-mode-btn:hover {
  color: var(--text);
}

.cfg-mode-btn.is-active {
  background: var(--accent);
  color: var(--accent-foreground);
}

/* Buttons */
.cfg-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius-md);
  font-size: var(--fs-sm);
  font-weight: 600;
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
  border: 1px solid transparent;
}

.cfg-btn--ghost {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.cfg-btn--ghost:hover {
  border-color: var(--border-focus);
  background: var(--bg-surface);
}

.cfg-btn--primary {
  background: var(--accent);
  color: var(--accent-foreground);
  border-color: var(--accent);
}

.cfg-btn--primary:hover {
  background: var(--accent-hover);
}

.cfg-search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0 12px;
  min-width: 220px;
}

.cfg-search-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.cfg-search-input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 0;
  width: 100%;
}

.cfg-search-input::placeholder {
  color: var(--text-dim);
}

/* Settings groups */
.cfg-settings-group {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-bottom: var(--sp-3);
  overflow: hidden;
}

.cfg-settings-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
}

.cfg-settings-group-title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
}

.cfg-settings-group-meta {
  font-size: var(--fs-xs);
  color: var(--text-dim);
  margin-top: 2px;
}

.cfg-settings-fields {
  padding: var(--sp-3) var(--sp-4);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-3);
}

/* Config field */
.config-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.config-field--stacked {
  grid-column: 1 / -1;
}

.config-field__label-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.form-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.cfg-help-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 2px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  transition: color var(--transition);
}

.cfg-help-btn:hover {
  color: var(--accent);
}

/* Inputs */
.input {
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  font-size: var(--fs-sm);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  outline: none;
  transition: border-color var(--transition), box-shadow var(--transition);
  font-family: inherit;
}

.input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}

.cfg-input-number {
  font-variant-numeric: tabular-nums;
}

.cfg-input-text {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.cfg-input-row {
  display: flex;
  gap: 6px;
}

.cfg-input-row .input {
  flex: 1;
}

/* Switch */
.cfg-switch {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.cfg-switch input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.cfg-switch-track {
  width: 40px;
  height: 22px;
  background: var(--border);
  border-radius: 999px;
  position: relative;
  transition: background var(--transition);
  flex-shrink: 0;
}

.cfg-switch input:checked + .cfg-switch-track {
  background: var(--accent);
}

.cfg-switch-thumb {
  width: 18px;
  height: 18px;
  background: #fff;
  border-radius: 50%;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: transform var(--transition);
  box-shadow: var(--shadow-xs);
}

.cfg-switch input:checked + .cfg-switch-track .cfg-switch-thumb {
  transform: translateX(18px);
}

.cfg-switch-text {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-muted);
}

/* Object field */
.cfg-object-field {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.cfg-object-field summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  cursor: pointer;
  font-size: var(--fs-sm);
  color: var(--text-muted);
  user-select: none;
  list-style: none;
}

.cfg-object-field summary::-webkit-details-marker {
  display: none;
}

.cfg-object-summary {
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.cfg-object-action {
  font-weight: 600;
  color: var(--accent);
}

.cfg-input-json {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  border: none;
  border-top: 1px solid var(--border);
  border-radius: 0;
  resize: vertical;
  min-height: 80px;
}

.cfg-json-error {
  padding: 6px 12px;
  font-size: var(--fs-xs);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 6%, transparent);
  border-top: 1px solid var(--border);
}

.cfg-json-error.hidden {
  display: none;
}

/* Dirty / invalid states */
.field-dirty .form-label {
  color: var(--accent);
}

.config-field--invalid {
  border-color: var(--danger);
}

.config-field--invalid .input {
  border-color: var(--danger);
}

/* YAML area */
.cfg-yaml-shell {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.cfg-yaml-area {
  width: 100%;
  min-height: 500px;
  padding: var(--sp-4);
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.6;
  background: var(--bg);
  border: none;
  border-radius: 0;
  color: var(--text);
  outline: none;
  resize: vertical;
}

/* Empty state */
.cfg-empty-state {
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

/* Sticky bar */
.cfg-stickybar {
  position: sticky;
  bottom: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  margin-top: var(--sp-4);
  z-index: 10;
}

.cfg-stickybar__row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}

.cfg-stickybar__pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: cfg-pulse 1.6s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes cfg-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@media (prefers-reduced-motion: reduce) {
  .cfg-stickybar__pulse {
    animation: none;
  }
}

.cfg-stickybar__count {
  font-size: var(--fs-sm);
  color: var(--text);
}

.cfg-stickybar__sep {
  color: var(--text-dim);
}

.cfg-stickybar__diff-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: none;
  color: var(--accent);
  font-size: var(--fs-sm);
  font-weight: 600;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  transition: background var(--transition);
}

.cfg-stickybar__diff-toggle:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.cfg-stickybar__chevron {
  display: inline-flex;
  transition: transform var(--transition);
}

.cfg-stickybar__diff-toggle.is-open .cfg-stickybar__chevron {
  transform: rotate(180deg);
}

.cfg-stickybar__spacer {
  flex: 1;
}

.cfg-stickybar__btn {
  padding: 6px 14px;
}

.cfg-stickybar__diff {
  padding: 0 var(--sp-4) var(--sp-3);
  border-top: 1px solid var(--border);
  padding-top: var(--sp-3);
}

.cfg-diff-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  font-family: var(--font-mono);
  padding: 4px 0;
}

.cfg-diff-key {
  font-weight: 600;
  color: var(--text);
  min-width: 160px;
}

.cfg-diff-old {
  color: var(--text-dim);
  text-decoration: line-through;
}

.cfg-diff-arrow {
  color: var(--accent);
}

.cfg-diff-new {
  color: var(--ok);
}

/* Tooltip */
.cfg-tooltip {
  position: fixed;
  z-index: 1000;
  max-width: 320px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--sp-3);
  pointer-events: none;
}

.cfg-tooltip__body {
  font-size: var(--fs-sm);
  line-height: 1.5;
  color: var(--text);
}

.cfg-tooltip__arrow {
  position: absolute;
  width: 8px;
  height: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  transform: rotate(45deg);
}

.cfg-tooltip[data-placement="bottom"] .cfg-tooltip__arrow {
  top: -5px;
  border-right: none;
  border-bottom: none;
}

.cfg-tooltip[data-placement="top"] .cfg-tooltip__arrow {
  bottom: -5px;
  border-left: none;
  border-top: none;
}

/* Responsive */
@media (max-width: 768px) {
  .cfg-panel {
    flex-direction: column;
  }

  .cfg-rail {
    flex-direction: row;
    width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding: var(--sp-2) var(--sp-3);
  }

  .cfg-rail-tab {
    border-left: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
  }

  .cfg-rail-tab.is-active {
    background: transparent;
    border-bottom-color: var(--accent);
  }

  .cfg-toolbar {
    padding: var(--sp-2) var(--sp-3);
  }

  .cfg-search-wrap {
    min-width: 0;
    flex: 1 1 100%;
    order: 10;
  }

  .cfg-scroll {
    padding: var(--sp-3);
  }

  .cfg-settings-fields {
    grid-template-columns: 1fr;
  }

  .cfg-stickybar__row {
    flex-wrap: wrap;
  }
}
</style>
