import { computed, ref } from 'vue'
import i18n from '@/i18n'
import { useToasts } from '@/composables/useToasts'
import type { ChatRouterTierConfig } from '@/types/chat'
import type { ModelRoutingMode } from '@/types/modelRouting'
import { normalizeModelRoutingMode } from '@/types/modelRouting'
import { normalizeRouterTier, sortRouterTiers } from '@/utils/chat/routerTiers'
import { encodeRouterShape, decodeRouterShape } from '@/utils/chat/routerShapeCache'
import {
  DEFAULT_ROUTER_VISUAL_MODE,
  normalizeRouterVisualMode,
} from '@/utils/chat/routerVisualMode'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface UseChatFeatureTogglesOptions {
  rpc: RpcClient
  setGlobalElevatedMode: (mode: string) => void
  loadCurrentSessionUsage: () => void | Promise<void>
}

interface ChatFeatureConfig {
  squilla_router?: {
    enabled?: boolean
    rollout_phase?: string
    visual_mode?: string
    tiers?: Record<string, {
      model?: string
      supports_image?: boolean
      supportsImage?: boolean
      image_only?: boolean
      imageOnly?: boolean
    }>
  }
  permissions?: {
    default_mode?: string
  }
  skills?: {
    coding_mode?: boolean
  }
  llm_ensemble?: {
    enabled?: boolean
    selection_mode?: string
  }
}

const ROUTER_FX_PREF_KEY = 'opensquilla.routerFx'
const ROUTER_SHAPE_KEY = 'opensquilla.router.shape'
const ROUTER_INDEPENDENT_ENSEMBLE_MODES = new Set([
  'static_openrouter_b5',
  'static_tokenrhythm_b5',
  'custom_b5',
])

export function useChatFeatureToggles(options: UseChatFeatureTogglesOptions) {
  const { pushToast } = useToasts()
  const routerEnabled = ref(false)
  const routerVisualEffectsEnabled = ref(true)
  const routerVisualMode = ref(DEFAULT_ROUTER_VISUAL_MODE)
  const routerSettingsBusy = ref(false)
  const codingModeEnabled = ref(false)
  const codingModeSettingsBusy = ref(false)
  const llmEnsembleEnabled = ref(false)
  const llmEnsembleSelectionMode = ref('')
  const llmEnsembleSettingsBusy = ref(false)
  const modelRoutingSettingsBusy = ref(false)
  const routerSlots = ref<string[]>([])
  const routerModels = ref<Record<string, string>>({})
  const routerTierConfigs = ref<Record<string, ChatRouterTierConfig>>({})

  const modelRoutingMode = computed<ModelRoutingMode>(() => {
    if (llmEnsembleEnabled.value) return 'llm_ensemble'
    return routerEnabled.value ? 'squilla_router' : 'off'
  })

  // Seed the last-known router shape synchronously so the router-strip reserve
  // twin can hold its slot on the first turn, before config.get resolves.
  hydrateRouterShape()

  async function applyFeatureConfig(cfg: ChatFeatureConfig | undefined, applyOptions: { refreshUsage?: boolean } = {}) {
    const router = cfg?.squilla_router || {}
    const ensembleEnabled = cfg?.llm_ensemble?.enabled === true

    routerEnabled.value = ensembleEnabled || Boolean(router.enabled && router.rollout_phase !== 'observe')
    codingModeEnabled.value = cfg?.skills?.coding_mode === true
    llmEnsembleEnabled.value = ensembleEnabled
    llmEnsembleSelectionMode.value = String(cfg?.llm_ensemble?.selection_mode || '')
    routerVisualMode.value = normalizeRouterVisualMode(router.visual_mode)
    loadRouterVisualEffectsPreference()

    const tiers = router.tiers
    const tierKeys: string[] = []
    const tierModels: Record<string, string> = {}
    const tierConfigs: Record<string, ChatRouterTierConfig> = {}
    if (tiers && typeof tiers === 'object') {
      Object.keys(tiers).forEach((tier) => {
        if (!tier) return
        const lower = normalizeRouterTier(tier)
        if (!lower) return
        tierKeys.push(lower)
        const rawTier = tiers[tier] || {}
        const model = rawTier.model
        if (typeof model === 'string' && model.trim()) {
          tierModels[lower] = model.trim()
        }
        tierConfigs[lower] = {
          model: typeof model === 'string' ? model.trim() : '',
          supportsImage: (rawTier as Record<string, unknown>).supports_image === true || (rawTier as Record<string, unknown>).supportsImage === true,
          imageOnly: (rawTier as Record<string, unknown>).image_only === true || (rawTier as Record<string, unknown>).imageOnly === true,
        }
      })
    }

    routerSlots.value = sortRouterTiers(tierKeys)
    routerModels.value = tierModels
    routerTierConfigs.value = tierConfigs
    persistRouterShape()
    options.setGlobalElevatedMode(cfg?.permissions?.default_mode || '')
    if (applyOptions.refreshUsage) {
      await options.loadCurrentSessionUsage()
    }
  }

  async function loadFeatureToggles() {
    try {
      await options.rpc.waitForConnection()
      const cfg = await options.rpc.call<ChatFeatureConfig>('config.get')
      await applyFeatureConfig(cfg, { refreshUsage: true })
    } catch {
      // Feature toggles are optional for older gateways.
    }
  }

  // Hydrate the router shape from localStorage into the live refs. Synchronous
  // and side-effect-free on failure so it is safe to call at composable init.
  function hydrateRouterShape() {
    try {
      const cached = decodeRouterShape(localStorage.getItem(ROUTER_SHAPE_KEY))
      if (!cached) return
      routerEnabled.value = cached.enabled
      routerSlots.value = cached.slots
      routerModels.value = cached.models
      routerTierConfigs.value = cached.configs
    } catch {}
  }

  // Persist the just-loaded shape so the next page load can seed the reserve.
  // Skip when there are no tier models — a degenerate shape would only seed a
  // <=1-cell reserve, which the reserve gate rejects anyway.
  function persistRouterShape() {
    try {
      if (Object.keys(routerModels.value).length === 0) return
      localStorage.setItem(ROUTER_SHAPE_KEY, encodeRouterShape({
        enabled: routerEnabled.value,
        slots: routerSlots.value,
        models: routerModels.value,
        configs: routerTierConfigs.value,
      }))
    } catch {}
  }

  function loadRouterVisualEffectsPreference() {
    try {
      const saved = localStorage.getItem(ROUTER_FX_PREF_KEY)
      if (!saved) return
      const parsed = JSON.parse(saved) as { enabled?: unknown }
      if (typeof parsed.enabled === 'boolean') {
        routerVisualEffectsEnabled.value = parsed.enabled
      }
    } catch {}
  }

  function saveRouterVisualEffectsPreference() {
    try {
      localStorage.setItem(ROUTER_FX_PREF_KEY, JSON.stringify({
        enabled: routerVisualEffectsEnabled.value,
        variant: 'default',
      }))
    } catch {}
  }

  function setRouterVisualEffectsEnabled(enabled: boolean) {
    routerVisualEffectsEnabled.value = Boolean(enabled)
    saveRouterVisualEffectsPreference()
    const savingsFx = (window as unknown as { SavingsFX?: { setEnabled?: (enabled: boolean) => void } }).SavingsFX
    savingsFx?.setEnabled?.(routerVisualEffectsEnabled.value)
  }

  async function setRouterEnabled(enabled: boolean) {
    await setModelRoutingMode(enabled ? 'squilla_router' : 'off')
  }

  async function setCodingModeEnabled(enabled: boolean) {
    if (codingModeSettingsBusy.value) return
    const nextEnabled = Boolean(enabled)
    const previous = codingModeEnabled.value
    codingModeSettingsBusy.value = true
    try {
      await options.rpc.waitForConnection()
      await options.rpc.call('config.patch.safe', {
        patches: {
          'skills.coding_mode': nextEnabled,
        },
      })
      const cfg = await options.rpc.call<ChatFeatureConfig>('config.get')
      await applyFeatureConfig(cfg)
    } catch (err) {
      codingModeEnabled.value = previous
      console.warn('Failed to update Coding mode:', err instanceof Error ? err.message : String(err))
    } finally {
      codingModeSettingsBusy.value = false
    }
  }

  async function setLlmEnsembleEnabled(enabled: boolean) {
    await setModelRoutingMode(enabled ? 'llm_ensemble' : 'off')
  }

  async function setModelRoutingMode(mode: ModelRoutingMode) {
    if (modelRoutingSettingsBusy.value) return
    const nextMode = normalizeModelRoutingMode(mode)
    const previousRouter = routerEnabled.value
    const previousEnsemble = llmEnsembleEnabled.value
    const nextEnsemble = nextMode === 'llm_ensemble'
    // Only known static/custom ensembles are independent of the router. Legacy
    // router_dynamic and unknown modes keep the pre-PR router-on behavior so a
    // slow/older config.get cannot disable a routing dependency.
    const nextRouter = nextMode === 'squilla_router'
      || (
        nextEnsemble
        && !ROUTER_INDEPENDENT_ENSEMBLE_MODES.has(llmEnsembleSelectionMode.value)
      )

    routerEnabled.value = nextEnsemble || nextRouter
    llmEnsembleEnabled.value = nextEnsemble
    modelRoutingSettingsBusy.value = true
    routerSettingsBusy.value = true
    llmEnsembleSettingsBusy.value = true
    try {
      await options.rpc.waitForConnection()
      await options.rpc.call('config.patch.safe', {
        patches: {
          'llm_ensemble.enabled': nextEnsemble,
          'squilla_router.enabled': nextRouter,
          // 'observe' only for a real off. Independent ensembles keep the
          // router disabled but leave its phase at 'full', so re-enabling it
          // from any surface routes immediately instead of shadowing.
          'squilla_router.rollout_phase': nextMode === 'off' ? 'observe' : 'full',
        },
      })
      await loadFeatureToggles()
    } catch (err) {
      routerEnabled.value = previousRouter
      llmEnsembleEnabled.value = previousEnsemble
      console.warn('Failed to update model routing:', err instanceof Error ? err.message : String(err))
      pushToast(i18n.global.t('chat.modelRouting.updateFailed'), { tone: 'danger' })
    } finally {
      modelRoutingSettingsBusy.value = false
      routerSettingsBusy.value = false
      llmEnsembleSettingsBusy.value = false
    }
  }

  function bindFeatureRefresh(scheduleHistorySync?: () => void) {
    let timer: ReturnType<typeof setTimeout> | null = null
    const schedule = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        loadFeatureToggles().finally(() => scheduleHistorySync?.())
      }, 120)
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') schedule()
    }
    const onFocus = () => schedule()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onFocus)
    return () => {
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onFocus)
    }
  }

  return {
    routerEnabled,
    routerVisualEffectsEnabled,
    routerVisualMode,
    routerSettingsBusy,
    modelRoutingMode,
    modelRoutingSettingsBusy,
    codingModeEnabled,
    codingModeSettingsBusy,
    llmEnsembleEnabled,
    llmEnsembleSettingsBusy,
    routerSlots,
    routerModels,
    routerTierConfigs,
    loadFeatureToggles,
    setRouterEnabled,
    setModelRoutingMode,
    setCodingModeEnabled,
    setLlmEnsembleEnabled,
    setRouterVisualEffectsEnabled,
    bindFeatureRefresh,
  }
}
