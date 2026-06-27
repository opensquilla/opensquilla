import { ref } from 'vue'
import type { ChatRouterTierConfig } from '@/types/chat'
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
}

const ROUTER_FX_PREF_KEY = 'opensquilla.routerFx'
const ROUTER_SHAPE_KEY = 'opensquilla.router.shape'

export function useChatFeatureToggles(options: UseChatFeatureTogglesOptions) {
  const routerEnabled = ref(false)
  const routerVisualEffectsEnabled = ref(true)
  const routerVisualMode = ref(DEFAULT_ROUTER_VISUAL_MODE)
  const routerSettingsBusy = ref(false)
  const routerSlots = ref<string[]>([])
  const routerModels = ref<Record<string, string>>({})
  const routerTierConfigs = ref<Record<string, ChatRouterTierConfig>>({})

  // Seed the last-known router shape synchronously so the router-strip reserve
  // twin can hold its slot on the first turn, before config.get resolves.
  hydrateRouterShape()

  async function loadFeatureToggles() {
    try {
      await options.rpc.waitForConnection()
      const cfg = await options.rpc.call<ChatFeatureConfig>('config.get')
      const router = cfg?.squilla_router || {}

      routerEnabled.value = Boolean(router.enabled && router.rollout_phase !== 'observe')
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
      await options.loadCurrentSessionUsage()
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
    if (routerSettingsBusy.value) return
    const nextEnabled = Boolean(enabled)
    const previous = routerEnabled.value
    routerEnabled.value = nextEnabled
    routerSettingsBusy.value = true
    try {
      await options.rpc.waitForConnection()
      await options.rpc.call('config.patch.safe', {
        patches: {
          'squilla_router.enabled': nextEnabled,
          'squilla_router.rollout_phase': nextEnabled ? 'full' : 'observe',
        },
      })
      await loadFeatureToggles()
    } catch (err) {
      routerEnabled.value = previous
      console.warn('Failed to update Squilla Router:', err instanceof Error ? err.message : String(err))
    } finally {
      routerSettingsBusy.value = false
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
    routerSlots,
    routerModels,
    routerTierConfigs,
    loadFeatureToggles,
    setRouterEnabled,
    setRouterVisualEffectsEnabled,
    bindFeatureRefresh,
  }
}
