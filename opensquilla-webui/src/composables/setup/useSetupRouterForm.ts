import { computed, ref, type ComputedRef } from 'vue'

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
    tiers[name] = {
      provider: tier.provider,
      model: tier.model,
      thinkingLevel: tier.thinkingLevel,
      supportsImage: tier.supportsImage,
    }
  })
  return { mode, defaultTier, tiers }
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
  const routerDefaultTier = ref('t1')
  const tierValues = ref<Record<string, SetupTierValue>>({})
  const mode = computed(() => routerMode.value)
  const defaultTier = computed(() => routerDefaultTier.value)

  function initFromConfig(
    router: RouterConfig,
    profileTiers: Record<string, TierConfig>,
  ) {
    routerMode.value = router.enabled === false ? 'disabled' : 'recommended'
    routerDefaultTier.value = router.default_tier || 't1'

    const tiers = Object.assign({}, profileTiers || {}, router.tiers || {})
    const next: Record<string, SetupTierValue> = {}
    Object.entries(tiers).forEach(([name, tier]) => {
      next[name] = {
        provider: tier.provider || '',
        model: tier.model || '',
        thinkingLevel: tier.thinkingLevel || tier.thinking_level || '',
        supportsImage: tier.supportsImage || tier.supports_image || false,
      }
    })
    tierValues.value = next
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
      .filter(([name]) => textTiers.includes(name) || name === 'image_model')
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
    routerDefaultTier.value = value
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
    initFromConfig,
    setRouterMode,
    setRouterDefaultTier,
    updateTierField,
    payload,
    createPanel,
  }
}
