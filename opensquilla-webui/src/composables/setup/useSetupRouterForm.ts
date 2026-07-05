import { computed, ref, type ComputedRef } from 'vue'
import i18n from '@/i18n'
import {
  DEFAULT_TEXT_TIER,
  IMAGE_TIER,
  normalizeRouterTier,
} from '@/utils/chat/routerTiers'
import {
  DEFAULT_ROUTER_VISUAL_MODE,
  normalizeRouterVisualMode,
  type RouterVisualMode,
} from '@/utils/chat/routerVisualMode'

export interface SetupTierValue {
  provider: string
  model: string
  thinkingLevel: string
  supportsImage: boolean
}

export interface SetupTierRow extends SetupTierValue {
  name: string
}

export type RouterConfigDisabledReason = 'single-model' | 'ensemble' | null

const ROUTER_VISUAL_MODE_VALUES: readonly RouterVisualMode[] = ['real_candidates', 'legacy_grid']

function routerVisualModeOptions(): Array<{ value: RouterVisualMode; label: string }> {
  return ROUTER_VISUAL_MODE_VALUES.map((value) => ({
    value,
    label: i18n.global.t(`setup.router.visualMode.${value}`),
  }))
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
  visual_mode?: string
  tier_profile?: string | null
  tiers?: Record<string, TierConfig>
}

interface RouterPanelContext {
  routerSummary: ComputedRef<string>
  ensembleProfileActive: ComputedRef<boolean>
  hasSavedProvider: ComputedRef<boolean>
  isOpenrouter: ComputedRef<boolean>
  textTiers: readonly string[]
  tierLabel: (tier: string) => string
}

export function useSetupRouterForm() {
  const routerMode = ref('recommended')
  const routerDefaultTier = ref(DEFAULT_TEXT_TIER)
  const routerVisualMode = ref<RouterVisualMode>(DEFAULT_ROUTER_VISUAL_MODE)
  const tierValues = ref<Record<string, SetupTierValue>>({})
  const mode = computed(() => routerMode.value)
  const defaultTier = computed(() => routerDefaultTier.value)
  const routerModeChoice = computed(() =>
    routerMode.value === 'disabled'
      ? 'disabled'
      : routerMode.value === 'openrouter-mix'
        ? 'openrouter-mix'
        : 'recommended',
  )

  function routerConfigDisabledReason(ensembleProfileActive: boolean): RouterConfigDisabledReason {
    if (ensembleProfileActive) return 'ensemble'
    if (routerMode.value === 'disabled') return 'single-model'
    return null
  }

  const routerSerialized = computed(() => JSON.stringify({ m: routerMode.value, d: routerDefaultTier.value, t: tierValues.value }))
  // Seed from the initial state so the pristine form is never dirty while config loads.
  const routerBaseline = ref(routerSerialized.value)
  const visualModeBaseline = ref(routerVisualMode.value)
  const routingDirty = computed(() => routerSerialized.value !== routerBaseline.value)
  const visualModeDirty = computed(() => routerVisualMode.value !== visualModeBaseline.value)
  const isDirty = computed(() => routingDirty.value || visualModeDirty.value)

  function initFromConfig(
    router: RouterConfig,
    profileTiers: Record<string, TierConfig>,
    provider = '',
  ) {
    // openrouter-mix is the only enabled router mode whose tier_profile is null,
    // and it is only valid for the openrouter LLM provider; recommended carries
    // tier_profile = the provider. Anything else enabled is recommended.
    if (router.enabled === false) {
      routerMode.value = 'disabled'
    } else if (provider.toLowerCase() === 'openrouter' && !router.tier_profile) {
      routerMode.value = 'openrouter-mix'
    } else {
      routerMode.value = 'recommended'
    }
    routerDefaultTier.value = normalizeRouterTier(router.default_tier || '') || DEFAULT_TEXT_TIER
    routerVisualMode.value = normalizeRouterVisualMode(router.visual_mode)

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
    routerBaseline.value = routerSerialized.value
    visualModeBaseline.value = routerVisualMode.value
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

  function setRouterVisualMode(value: string) {
    routerVisualMode.value = normalizeRouterVisualMode(value)
  }

  function payload(): Record<string, unknown> {
    return buildRouterPayload(routerMode.value, routerDefaultTier.value, tierValues.value)
  }

  function visualModePatches(): Record<string, unknown> {
    if (!visualModeDirty.value) return {}
    return { 'squilla_router.visual_mode': routerVisualMode.value }
  }

  function createPanel(context: RouterPanelContext) {
    return computed(() => {
      const disabledReason = routerConfigDisabledReason(context.ensembleProfileActive.value)
      return {
        routerSummary: context.routerSummary.value,
        ensembleProfileActive: context.ensembleProfileActive.value,
        routerMode: routerMode.value,
        routerModeChoice: routerModeChoice.value,
        routerConfigDisabled: disabledReason !== null,
        routerConfigDisabledReason: disabledReason,
        routerDefaultTier: routerDefaultTier.value,
        routerVisualMode: routerVisualMode.value,
        routerVisualModeDirty: visualModeDirty.value,
        routerVisualModeOptions: routerVisualModeOptions(),
        hasSavedProvider: context.hasSavedProvider.value,
        canUseOpenrouterMix: context.isOpenrouter.value,
        textTiers: context.textTiers,
        tierRows: tierRows(context.textTiers),
        tierLabel: context.tierLabel,
      }
    })
  }

  return {
    mode,
    defaultTier,
    routingDirty,
    visualModeDirty,
    isDirty,
    initFromConfig,
    setRouterMode,
    setRouterDefaultTier,
    setRouterVisualMode,
    updateTierField,
    payload,
    visualModePatches,
    createPanel,
  }
}
