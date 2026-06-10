import { ref } from 'vue'
import type { ChatRouterTierConfig } from '@/types/chat'
import { normalizeRouterTier, sortRouterTiers } from '@/utils/chat/routerTiers'

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

export function useChatFeatureToggles(options: UseChatFeatureTogglesOptions) {
  const routerEnabled = ref(false)
  const routerVisualEffectsEnabled = ref(true)
  const routerSettingsBusy = ref(false)
  const routerSlots = ref<string[]>([])
  const routerModels = ref<Record<string, string>>({})
  const routerTierConfigs = ref<Record<string, ChatRouterTierConfig>>({})

  async function loadFeatureToggles() {
    try {
      await options.rpc.waitForConnection()
      const cfg = await options.rpc.call<ChatFeatureConfig>('config.get')
      const router = cfg?.squilla_router || {}

      routerEnabled.value = Boolean(router.enabled && router.rollout_phase !== 'observe')
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
      options.setGlobalElevatedMode(cfg?.permissions?.default_mode || '')
      await options.loadCurrentSessionUsage()
    } catch {
      // Feature toggles are optional for older gateways.
    }
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
