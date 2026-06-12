import { computed, ref, type ComputedRef } from 'vue'
import {
  DEFAULT_TEXT_TIER,
  IMAGE_TIER,
  normalizeRouterTier,
} from '@/utils/chat/routerTiers'

export interface SetupTierValue {
  provider: string
  model: string
  thinkingLevel: string
  supportsImage: boolean
}

export interface SetupTierRow extends SetupTierValue {
  name: string
}

export function buildRouterPayload(
  mode: string,
  defaultTier: string,
  tierValues: Record<string, SetupTierValue>,
): Record<string, unknown> {
  const tiers: Record<string, Record<string, unknown>> = {}
  Object.entries(tierValues).forEach(([name, tier]) => {
    const tierName = normalizeRouterTier(name) || name
    tiers[tierName] = {
      provider: tier.provider,
      model: tier.model,
      thinkingLevel: tier.thinkingLevel,
      supportsImage: tier.supportsImage,
    }
  })
  return { mode, defaultTier: normalizeRouterTier(defaultTier) || DEFAULT_TEXT_TIER, tiers }
}

interface TierConfig {
  provider?: string
  model?: string
  thinkingLevel?: string
  thinking_level?: string
  supportsImage?: boolean
  supports_image?: boolean
}

interface RouterConfig {
  enabled?: boolean
  default_tier?: string
  tiers?: Record<string, TierConfig>
}

interface RouterPanelContext {
  routerSummary: ComputedRef<string>
  hasSavedProvider: ComputedRef<boolean>
  textTiers: readonly string[]
  tierLabel: (tier: string) => string
}

export function useSetupRouterForm() {
  const routerMode = ref('recommended')
  const routerDefaultTier = ref(DEFAULT_TEXT_TIER)
  const tierValues = ref<Record<string, SetupTierValue>>({})
  const mode = computed(() => routerMode.value)
  const defaultTier = computed(() => routerDefaultTier.value)

  const serialized = computed(() => JSON.stringify({ m: routerMode.value, d: routerDefaultTier.value, t: tierValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const baseline = ref(serialized.value)
  const isDirty = computed(() => serialized.value !== baseline.value)

  function initFromConfig(
    router: RouterConfig,
    profileTiers: Record<string, TierConfig>,
  ) {
    routerMode.value = router.enabled === false ? 'disabled' : 'recommended'
    routerDefaultTier.value = normalizeRouterTier(router.default_tier || '') || DEFAULT_TEXT_TIER

    const tiers = Object.assign({}, profileTiers || {}, router.tiers || {})
    const next: Record<string, SetupTierValue> = {}
    Object.entries(tiers).forEach(([name, tier]) => {
      const tierName = normalizeRouterTier(name) || name
      next[tierName] = {
        provider: tier.provider || '',
        model: tier.model || '',
        thinkingLevel: tier.thinkingLevel || tier.thinking_level || '',
        supportsImage: tier.supportsImage || tier.supports_image || false,
      }
    })
    tierValues.value = next
    baseline.value = serialized.value
  }

  function updateTierField(name: string, key: keyof SetupTierValue, value: string | boolean) {
    const tier = tierValues.value[name]
    if (!tier) return
    if (key === 'supportsImage') {
      tier.supportsImage = Boolean(value)
    } else {
      tier[key] = String(value)
    }
  }

  function tierRows(textTiers: readonly string[]): SetupTierRow[] {
    return Object.entries(tierValues.value)
      .filter(([name]) => textTiers.includes(name) || name === IMAGE_TIER)
      .map(([name, tier]) => ({
        name,
        provider: tier.provider,
        model: tier.model,
        thinkingLevel: tier.thinkingLevel,
        supportsImage: tier.supportsImage,
      }))
  }

  function setRouterMode(value: string) {
    routerMode.value = value
  }

  function setRouterDefaultTier(value: string) {
    routerDefaultTier.value = normalizeRouterTier(value) || DEFAULT_TEXT_TIER
  }

  function payload(): Record<string, unknown> {
    return buildRouterPayload(routerMode.value, routerDefaultTier.value, tierValues.value)
  }

  function createPanel(context: RouterPanelContext) {
    return computed(() => ({
      routerSummary: context.routerSummary.value,
      routerMode: routerMode.value,
      routerDefaultTier: routerDefaultTier.value,
      hasSavedProvider: context.hasSavedProvider.value,
      textTiers: context.textTiers,
      tierRows: tierRows(context.textTiers),
      tierLabel: context.tierLabel,
    }))
  }

  return {
    mode,
    defaultTier,
    isDirty,
    initFromConfig,
    setRouterMode,
    setRouterDefaultTier,
    updateTierField,
    payload,
    createPanel,
  }
}
