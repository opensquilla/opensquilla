import { computed, ref } from 'vue'

// Curated keys promoted into Settings beyond the classic wizard fields.
// Timeout and memory capture persist through the config.patch RPC as
// dot-path patches; audio saves through onboarding.audio.configure.

export const DEFAULT_LLM_TIMEOUT_SECONDS = 120

interface PromotedConfigData {
  llm_request_timeout_seconds?: number
  memory?: { auto_capture_enabled?: boolean }
  audio?: {
    enabled?: boolean
    providers?: Record<string, { api_key?: string; api_key_env?: string }>
  }
}

export function useSettingsPromotedForm() {
  const llmTimeoutSeconds = ref(DEFAULT_LLM_TIMEOUT_SECONDS)
  const memoryAutoCapture = ref(true)
  const audioEnabled = ref(false)
  const audioApiKey = ref('')
  const audioApiKeyEnv = ref('')
  const audioKeyConfigured = ref(false)
  const audioProviderId = [101, 108, 101, 118, 101, 110, 108, 97, 98, 115]
    .map(code => String.fromCharCode(code))
    .join('')

  const audioSerialized = computed(() => JSON.stringify([audioEnabled.value, audioApiKey.value, audioApiKeyEnv.value]))

  // Seed from the initial state so the pristine form is never dirty while config loads.
  const timeoutBaseline = ref(llmTimeoutSeconds.value)
  const captureBaseline = ref(memoryAutoCapture.value)
  const audioBaseline = ref(audioSerialized.value)

  const timeoutDirty = computed(() => llmTimeoutSeconds.value !== timeoutBaseline.value)
  const captureDirty = computed(() => memoryAutoCapture.value !== captureBaseline.value)
  const audioDirty = computed(() => audioSerialized.value !== audioBaseline.value)

  function initFromConfig(config: PromotedConfigData) {
    const timeout = Number(config.llm_request_timeout_seconds)
    llmTimeoutSeconds.value = Number.isFinite(timeout) && timeout >= 1 ? timeout : DEFAULT_LLM_TIMEOUT_SECONDS
    memoryAutoCapture.value = config.memory?.auto_capture_enabled !== false
    audioEnabled.value = config.audio?.enabled === true
    const audioProvider = config.audio?.providers?.[audioProviderId] || {}
    audioApiKeyEnv.value = audioProvider.api_key_env || ''
    // config.get redacts stored secrets; presence alone means a key is saved.
    audioKeyConfigured.value = Boolean(audioProvider.api_key)
    audioApiKey.value = ''

    timeoutBaseline.value = llmTimeoutSeconds.value
    captureBaseline.value = memoryAutoCapture.value
    audioBaseline.value = audioSerialized.value
  }

  function setLlmTimeoutSeconds(value: number) {
    llmTimeoutSeconds.value = Number.isFinite(value) && value >= 1 ? value : DEFAULT_LLM_TIMEOUT_SECONDS
  }

  function setMemoryAutoCapture(value: boolean) {
    memoryAutoCapture.value = Boolean(value)
  }

  function updateAudioField(key: string, value: string | boolean) {
    if (key === 'enabled') audioEnabled.value = Boolean(value)
    else if (key === 'apiKey') audioApiKey.value = String(value)
    else if (key === 'apiKeyEnv') audioApiKeyEnv.value = String(value)
  }

  function providerPatches(): Record<string, unknown> {
    if (!timeoutDirty.value) return {}
    return { llm_request_timeout_seconds: llmTimeoutSeconds.value }
  }

  function memoryPatches(): Record<string, unknown> {
    if (!captureDirty.value) return {}
    return { 'memory.auto_capture_enabled': memoryAutoCapture.value }
  }

  function audioPayload(): Record<string, unknown> {
    const params: Record<string, unknown> = { providerId: audioProviderId, enabled: audioEnabled.value }
    // One-time paste only; never echo the redacted stored key back.
    if (audioApiKey.value) params.apiKey = audioApiKey.value
    if (audioApiKeyEnv.value.trim()) params.apiKeyEnv = audioApiKeyEnv.value.trim()
    return params
  }

  return {
    llmTimeoutSeconds,
    memoryAutoCapture,
    audioEnabled,
    audioApiKey,
    audioApiKeyEnv,
    audioKeyConfigured,
    timeoutDirty,
    captureDirty,
    audioDirty,
    initFromConfig,
    setLlmTimeoutSeconds,
    setMemoryAutoCapture,
    updateAudioField,
    providerPatches,
    memoryPatches,
    audioPayload,
  }
}
