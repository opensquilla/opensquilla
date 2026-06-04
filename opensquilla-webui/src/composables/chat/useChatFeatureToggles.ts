import { ref } from 'vue'
import {
  routerFxSortTiers,
} from '@/composables/chat/useChatRenderedMessages'

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
    tiers?: Record<string, { model?: string }>
  }
  permissions?: {
    default_mode?: string
  }
}

export function useChatFeatureToggles(options: UseChatFeatureTogglesOptions) {
  const routerSlots = ref<string[]>([])
  const routerModels = ref<Record<string, string>>({})

  async function loadFeatureToggles() {
    try {
      await options.rpc.waitForConnection()
      const cfg = await options.rpc.call<ChatFeatureConfig>('config.get')

      const tiers = cfg?.squilla_router?.tiers
      const tierKeys: string[] = []
      const tierModels: Record<string, string> = {}
      if (tiers && typeof tiers === 'object') {
        Object.keys(tiers).forEach((tier) => {
          if (!tier) return
          const lower = String(tier).toLowerCase()
          tierKeys.push(lower)
          const model = tiers[tier]?.model
          if (typeof model === 'string' && model.trim()) {
            tierModels[lower] = model.trim()
          }
        })
      }

      routerSlots.value = routerFxSortTiers(tierKeys)
      routerModels.value = tierModels
      options.setGlobalElevatedMode(cfg?.permissions?.default_mode || '')
      await options.loadCurrentSessionUsage()
    } catch {
      // Feature toggles are optional for older gateways.
    }
  }

  return {
    routerSlots,
    routerModels,
    loadFeatureToggles,
  }
}
