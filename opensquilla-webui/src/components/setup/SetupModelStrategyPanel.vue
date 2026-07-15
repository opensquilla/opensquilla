<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SetupTierTable from '@/components/setup/SetupTierTable.vue'
import type { ModelStrategy } from '@/composables/setup/useSetupModelStrategyForm'
import type { SetupTierRow } from '@/composables/setup/useSetupRouterForm'
import type { DiscoveredModelsByProvider } from '@/composables/setup/useSetupProviderForm'
import {
  ENSEMBLE_PROPOSER_ROLES,
  type EnsembleCandidateRole,
  type EnsembleCandidateView,
  type EnsembleCredentialStatus,
  type EnsembleCustomLineupView,
  type EnsembleEffectiveFacts,
  type EnsembleFixedProfileView,
  type EnsembleScheme,
} from '@/composables/setup/useSetupEnsembleForm'

const { t } = useI18n()

interface StrategyCard {
  id: ModelStrategy
  enabled: boolean
  titleKey: string
  descKey: string
}

interface RouterPanelContract {
  routerDefaultTier: string
  routerVisualMode: string
  routerVisualModeOptions: readonly { value: string; label: string }[]
  routerConfigDisabled: boolean
  hasSavedProvider: boolean
  textTiers: readonly string[]
  tierRows: readonly SetupTierRow[]
  tierLabel: (tier: string) => string
  discoveredModelsByProvider?: DiscoveredModelsByProvider
  hasMixedTierProviders: boolean
}

interface EnsemblePanelContract {
  enabled: boolean
  activeProvider?: string
  activeModel?: string
  selectionMode: string
  scheme: EnsembleScheme
  schemeCardsAvailable: boolean
  modelOptions: string[]
  candidates: readonly { provider: string; model: string; source?: string; enabled?: boolean; role?: string }[]
  tierCandidates: readonly EnsembleCandidateView[]
  customCandidates: readonly EnsembleCandidateView[]
  custom: EnsembleCustomLineupView
  fixedProfile: EnsembleFixedProfileView | null
  presetFacts: EnsembleEffectiveFacts
  minSuccessfulProposers: number
  allFailedPolicy: string
  showCandidateEditor: boolean
  statusText: string
}

interface ModelStrategyPanelContract {
  activeStrategy: ModelStrategy
  hasSavedProvider: boolean
  providerLabel: string
  routerTemplateState: string
  cards: readonly StrategyCard[]
  router: RouterPanelContract
  ensemble: EnsemblePanelContract
}

const props = defineProps<{
  panel: ModelStrategyPanelContract
}>()

const emit = defineEmits<{
  updateStrategy: [value: ModelStrategy]
  updateRouterDefaultTier: [value: string]
  updateRouterVisualMode: [value: string]
  updateTierField: [name: string, key: 'model' | 'thinkingLevel' | 'supportsImage', value: string | boolean]
  updateEnsembleScheme: [value: 'preset' | 'custom']
  addEnsembleCandidate: [provider: string, model: string, role: EnsembleCandidateRole]
  removeEnsembleCandidate: [candidate: EnsembleCandidateView]
  setEnsembleCandidateRole: [candidate: EnsembleCandidateView, role: EnsembleCandidateRole]
  importEnsembleTierCandidates: []
  migrateEnsembleLegacy: []
  updateEnsembleMinSuccessful: [value: number]
  updateEnsembleAllFailedPolicy: [value: string]
  goToSection: [value: string]
}>()

const showRouterDetails = computed(() => props.panel.activeStrategy === 'router')
const routerEditingDisabled = computed(() => !props.panel.hasSavedProvider)
const newCandidateProvider = ref('')
const newCandidateModel = ref('')
const newCandidateRole = ref<EnsembleCandidateRole>('')

const proposerRoles = ENSEMBLE_PROPOSER_ROLES

function displayProvider(provider: string): string {
  const normalized = String(provider || '').trim().toLowerCase()
  if (!normalized) return props.panel.providerLabel
  if (normalized === 'openrouter') return 'OpenRouter'
  if (normalized === 'openai') return 'OpenAI'
  if (normalized === 'deepseek') return 'DeepSeek'
  if (normalized === 'anthropic') return 'Anthropic'
  if (normalized === 'groq') return 'Groq'
  if (normalized === 'tokenrhythm') return 'TokenRhythm'
  return normalized
}

const defaultRouteModel = computed(() => {
  const tier = props.panel.router.tierRows.find(row => row.name === props.panel.router.routerDefaultTier)
    || props.panel.router.tierRows[0]
  return tier?.model || ''
})

const ensembleScheme = computed(() => props.panel.ensemble.scheme)
const customLineup = computed(() => props.panel.ensemble.custom)
const currentModel = computed(() => (
  props.panel.ensemble.activeModel
  || customLineup.value.inheritedAggregatorModel
  || defaultRouteModel.value
  || props.panel.providerLabel
))
const currentProvider = computed(() => displayProvider(
  props.panel.ensemble.activeProvider
  || customLineup.value.inheritedAggregatorProvider
  || '',
) || props.panel.providerLabel)
const capacityCells = computed(() => {
  const lineup = customLineup.value
  return Array.from({ length: lineup.maxProposers }, (_, index) => ({
    filled: index < lineup.proposerCount,
    warn: index >= lineup.recommendedMax && index < lineup.proposerCount,
  }))
})

// Preset member blurbs: what each fixed lineup member contributes. Keyed by
// bare model family so the OpenRouter and TokenRhythm spellings share notes.
function presetMemberNoteKey(model: string): string {
  const bare = model.includes('/') ? model.split('/').slice(1).join('/') : model
  if (bare.startsWith('deepseek-v4-pro')) return 'setup.modelStrategy.presetNoteDeepseek'
  if (bare.startsWith('glm-')) return 'setup.modelStrategy.presetNoteGlm'
  if (bare.startsWith('kimi-')) return 'setup.modelStrategy.presetNoteKimi'
  if (bare.startsWith('qwen')) return 'setup.modelStrategy.presetNoteQwen'
  return 'setup.modelStrategy.presetNoteGeneric'
}

function submitCandidate() {
  const provider = newCandidateProvider.value.trim()
  const model = newCandidateModel.value.trim()
  if (!provider || !model) return
  emit('addEnsembleCandidate', provider, model, newCandidateRole.value)
  newCandidateProvider.value = ''
  newCandidateModel.value = ''
  newCandidateRole.value = ''
}

function candidateLabel(candidate: EnsembleCandidateView): string {
  return `${displayProvider(candidate.provider)} · ${candidate.model}`
}

function roleLabel(role: string): string {
  if (!role) return t('setup.modelStrategy.roleUnassigned')
  return t(`setup.modelStrategy.role_${role}`)
}

function credentialKey(status: EnsembleCredentialStatus | undefined): string {
  if (!status) return 'setup.modelStrategy.credentialUnknown'
  if (status.available) return 'setup.modelStrategy.credentialReady'
  if (status.source === 'missing_env') return 'setup.modelStrategy.credentialMissingEnv'
  return 'setup.modelStrategy.credentialNeeded'
}

function credentialLabel(candidate: EnsembleCandidateView): string {
  return t(credentialKey(candidate.credential), {
    provider: displayProvider(candidate.provider),
    envKey: candidate.credential?.envKey || '',
  })
}
</script>

<template>
  <section class="control-section setup-model-strategy">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.modelStrategy.title') }}</h3>
      <p class="control-section__desc">{{ t('setup.modelStrategy.desc', { provider: panel.providerLabel }) }}</p>
    </div>

    <div class="setup-model-strategy__cards" role="radiogroup" :aria-label="t('setup.modelStrategy.title')">
      <button
        v-for="card in panel.cards"
        :key="card.id"
        type="button"
        role="radio"
        class="setup-model-strategy__card"
        :class="{ 'is-active': card.enabled }"
        :data-strategy-id="card.id"
        :aria-checked="card.enabled"
        @click="emit('updateStrategy', card.id)"
      >
        <span class="setup-model-strategy__card-title">{{ t(card.titleKey) }}</span>
        <span class="setup-model-strategy__card-desc">{{ t(card.descKey) }}</span>
      </button>
    </div>

    <div
      v-if="!panel.hasSavedProvider"
      class="setup-warning"
      data-testid="model-strategy-provider-first"
    >
      <span>{{ t('setup.modelStrategy.providerFirst') }}</span>
      <button type="button" class="setup-warning__action" @click="emit('goToSection', 'provider')">
        {{ t('setup.modelStrategy.providerAction') }}
      </button>
    </div>

    <template v-else>
      <p v-if="showRouterDetails && panel.router.hasMixedTierProviders" class="setup-model-strategy__notice">
        {{ t('setup.modelStrategy.crossProviderNotice') }}
      </p>

      <section v-if="showRouterDetails" class="control-section setup-model-strategy__detail">
        <div class="control-section__head">
          <h3 class="control-section__title">{{ t('setup.modelStrategy.routerTitle') }}</h3>
          <p class="control-section__desc">
            {{ t('setup.modelStrategy.routerDependency', { provider: currentProvider, model: currentModel }) }}
          </p>
        </div>

        <label class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.router.defaultRoutingTier') }}</span>
          </div>
          <div class="control-row__control">
            <select
              class="control-input"
              :value="panel.router.routerDefaultTier"
              name="setup_model_strategy_router_default_tier"
              :disabled="routerEditingDisabled"
              @change="emit('updateRouterDefaultTier', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="tier in panel.router.textTiers" :key="tier" :value="tier">{{ panel.router.tierLabel(tier) }}</option>
            </select>
          </div>
        </label>

        <label class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.modelStrategy.visualModeLabel') }}</span>
            <span class="control-row__desc">{{ t('setup.modelStrategy.visualModeDesc') }}</span>
          </div>
          <div class="control-row__control">
            <!-- Chat-panel visualization for routing decisions (squilla_router.visual_mode):
                 cosmetic only, but user-persisted — without this row a saved
                 legacy_grid choice becomes unreachable from the UI. -->
            <select
              class="control-input"
              :value="panel.router.routerVisualMode"
              name="setup_model_strategy_router_visual_mode"
              :disabled="routerEditingDisabled"
              @change="emit('updateRouterVisualMode', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="option in panel.router.routerVisualModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </div>
        </label>

        <SetupTierTable
          :rows="panel.router.tierRows"
          :tier-label="panel.router.tierLabel"
          :disabled="routerEditingDisabled"
          :models-by-provider="panel.router.discoveredModelsByProvider || {}"
          @update-tier-field="(name, key, value) => emit('updateTierField', name, key, value)"
        />
      </section>

      <section v-else-if="panel.activeStrategy === 'ensemble'" class="control-section setup-model-strategy__detail">
        <div class="control-section__head">
          <h3 class="control-section__title">{{ t('setup.modelStrategy.ensembleTitle') }}</h3>
          <p class="control-section__desc">
            {{ t('setup.modelStrategy.ensembleDependency', { provider: currentProvider, model: currentModel }) }}
          </p>
        </div>

        <p class="setup-model-strategy__pipeline" data-testid="ensemble-pipeline">
          {{ t('setup.modelStrategy.ensemblePipeline') }}
        </p>

        <!-- Legacy router_dynamic config: migration banner instead of the old auto UI. -->
        <div v-if="ensembleScheme === 'legacy'" class="setup-model-strategy__notice setup-model-strategy__notice--legacy" data-testid="ensemble-legacy-banner">
          <span>{{ t('setup.modelStrategy.legacyDynamicNotice') }}</span>
          <button
            type="button"
            class="btn"
            data-testid="ensemble-migrate-legacy"
            @click="emit('migrateEnsembleLegacy')"
          >
            {{ t('setup.modelStrategy.legacyDynamicMigrate') }}
          </button>
        </div>

        <!-- Scheme choice: provider preset (recommended) vs custom lineup. -->
        <div
          v-if="panel.ensemble.schemeCardsAvailable && ensembleScheme !== 'legacy'"
          class="setup-model-strategy__schemes"
          role="radiogroup"
          :aria-label="t('setup.modelStrategy.schemeLabel')"
        >
          <button
            type="button"
            role="radio"
            class="setup-model-strategy__scheme"
            :class="{ 'is-active': ensembleScheme === 'preset' }"
            data-testid="ensemble-scheme-preset"
            :aria-checked="ensembleScheme === 'preset'"
            @click="emit('updateEnsembleScheme', 'preset')"
          >
            <span class="setup-model-strategy__scheme-title">
              {{ t('setup.modelStrategy.schemePresetTitle') }}
              <span class="setup-model-strategy__scheme-badge">{{ t('setup.modelStrategy.schemePresetBadge') }}</span>
            </span>
            <span class="setup-model-strategy__scheme-desc">{{ t('setup.modelStrategy.schemePresetDesc') }}</span>
          </button>
          <button
            type="button"
            role="radio"
            class="setup-model-strategy__scheme"
            :class="{ 'is-active': ensembleScheme === 'custom' }"
            data-testid="ensemble-scheme-custom"
            :aria-checked="ensembleScheme === 'custom'"
            @click="emit('updateEnsembleScheme', 'custom')"
          >
            <span class="setup-model-strategy__scheme-title">
              {{ t('setup.modelStrategy.schemeCustomTitle') }}
              <span class="setup-model-strategy__scheme-badge setup-model-strategy__scheme-badge--soft">{{ t('setup.modelStrategy.schemeCustomBadge') }}</span>
            </span>
            <span class="setup-model-strategy__scheme-desc">{{ t('setup.modelStrategy.schemeCustomDesc') }}</span>
          </button>
        </div>

        <!-- Preset lineup (OpenRouter / TokenRhythm fixed B5). -->
        <div v-if="ensembleScheme === 'preset' && panel.ensemble.fixedProfile" class="control-row control-row--stack">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.modelStrategy.openrouterFixedTitle', { provider: panel.ensemble.fixedProfile.providerLabel }) }}</span>
            <span class="control-row__desc">{{ t('setup.modelStrategy.openrouterFixedDesc', { provider: panel.ensemble.fixedProfile.providerLabel }) }}</span>
          </div>
          <div class="setup-model-strategy__candidate-list" role="list">
            <div
              v-for="candidate in panel.ensemble.fixedProfile.proposers"
              :key="candidate.key"
              class="setup-model-strategy__candidate"
              role="listitem"
            >
              <span class="setup-model-strategy__candidate-main">
                <span class="setup-model-strategy__candidate-label">{{ candidateLabel(candidate) }}</span>
                <span class="setup-model-strategy__candidate-source">
                  {{ t('setup.modelStrategy.openrouterFixedProposer') }} · {{ t(presetMemberNoteKey(candidate.model)) }}
                </span>
              </span>
              <span class="setup-model-strategy__credential" :class="{ 'is-missing': candidate.credential && !candidate.credential.available }">
                {{ credentialLabel(candidate) }}
              </span>
            </div>
            <div class="setup-model-strategy__candidate setup-model-strategy__candidate--aggregator" role="listitem">
              <span class="setup-model-strategy__candidate-main">
                <span class="setup-model-strategy__candidate-label">
                  {{ candidateLabel(panel.ensemble.fixedProfile.aggregator) }}
                </span>
                <span class="setup-model-strategy__candidate-source">{{ t('setup.modelStrategy.openrouterFixedAggregator') }} · {{ t('setup.modelStrategy.aggregatorNote') }}</span>
              </span>
              <span
                class="setup-model-strategy__credential"
                :class="{ 'is-missing': panel.ensemble.fixedProfile.aggregator.credential && !panel.ensemble.fixedProfile.aggregator.credential.available }"
              >
                {{ credentialLabel(panel.ensemble.fixedProfile.aggregator) }}
              </span>
            </div>
          </div>
          <p class="setup-model-strategy__facts" data-testid="ensemble-preset-facts">
            {{ t('setup.modelStrategy.effectiveFacts', {
              calls: panel.ensemble.presetFacts.perTurnCalls,
              quorum: panel.ensemble.presetFacts.quorum,
              proposers: panel.ensemble.presetFacts.proposerCount,
              proposerTimeout: panel.ensemble.presetFacts.proposerTimeoutSeconds,
              aggregatorTimeout: panel.ensemble.presetFacts.aggregatorTimeoutSeconds,
              grace: panel.ensemble.presetFacts.quorumGraceSeconds,
            }) }}
          </p>
        </div>

        <!-- Custom lineup: aggregator first, then role-labelled proposers. -->
        <template v-if="ensembleScheme === 'custom' || ensembleScheme === 'legacy'">
          <div class="control-row control-row--stack">
            <div class="control-row__label-block">
              <span class="control-row__label">{{ t('setup.modelStrategy.aggregatorSectionLabel') }}</span>
              <span class="control-row__desc">{{ t('setup.modelStrategy.aggregatorSectionDesc') }}</span>
            </div>
            <div class="setup-model-strategy__candidate-list" role="list">
              <div
                v-if="customLineup.aggregator"
                class="setup-model-strategy__candidate setup-model-strategy__candidate--aggregator"
                role="listitem"
                data-testid="ensemble-custom-aggregator"
              >
                <span class="setup-model-strategy__candidate-main">
                  <span class="setup-model-strategy__candidate-label">{{ candidateLabel(customLineup.aggregator) }}</span>
                  <span class="setup-model-strategy__candidate-source">{{ t('setup.modelStrategy.aggregatorNote') }}</span>
                </span>
                <span class="setup-model-strategy__credential" :class="{ 'is-missing': customLineup.aggregator.credential && !customLineup.aggregator.credential.available }">
                  {{ credentialLabel(customLineup.aggregator) }}
                </span>
                <button
                  type="button"
                  class="setup-model-strategy__candidate-remove"
                  :aria-label="t('setup.modelStrategy.removeCandidateAria', { model: customLineup.aggregator.model })"
                  @click="emit('removeEnsembleCandidate', customLineup.aggregator)"
                >&times;</button>
              </div>
              <div
                v-else
                class="setup-model-strategy__candidate setup-model-strategy__candidate--aggregator setup-model-strategy__candidate--inherited"
                role="listitem"
                data-testid="ensemble-custom-aggregator-inherited"
              >
                <span class="setup-model-strategy__candidate-main">
                  <span class="setup-model-strategy__candidate-label">
                    {{ displayProvider(customLineup.inheritedAggregatorProvider) }} · {{ customLineup.inheritedAggregatorModel || currentModel }}
                  </span>
                  <span class="setup-model-strategy__candidate-source">{{ t('setup.modelStrategy.aggregatorInheritedNote') }}</span>
                </span>
              </div>
            </div>
          </div>

          <div class="control-row control-row--stack">
            <div class="setup-model-strategy__candidate-head">
              <div class="control-row__label-block">
                <span class="control-row__label">
                  {{ t('setup.modelStrategy.proposerSectionLabel') }}
                  <span class="setup-model-strategy__count" data-testid="ensemble-proposer-count">
                    {{ t('setup.modelStrategy.proposerCount', {
                      count: customLineup.proposerCount,
                      max: customLineup.maxProposers,
                      recommendedMin: customLineup.recommendedMin,
                      recommendedMax: customLineup.recommendedMax,
                    }) }}
                  </span>
                </span>
                <span class="control-row__desc">{{ t('setup.modelStrategy.proposerSectionDesc') }}</span>
              </div>
              <button
                type="button"
                class="btn"
                data-testid="setup-model-strategy-import-tiers"
                :disabled="!panel.ensemble.tierCandidates.length || !customLineup.canAddProposer"
                @click="emit('importEnsembleTierCandidates')"
              >
                {{ t('setup.modelStrategy.importTierCandidates') }}
              </button>
            </div>

            <div class="setup-model-strategy__capacity" role="img" :aria-label="t('setup.modelStrategy.proposerCount', { count: customLineup.proposerCount, max: customLineup.maxProposers, recommendedMin: customLineup.recommendedMin, recommendedMax: customLineup.recommendedMax })">
              <span
                v-for="(cell, index) in capacityCells"
                :key="index"
                class="setup-model-strategy__capacity-cell"
                :class="{ 'is-filled': cell.filled, 'is-warn': cell.filled && cell.warn }"
              ></span>
            </div>

            <div v-if="customLineup.proposers.length" class="setup-model-strategy__candidate-list" role="list">
              <div
                v-for="candidate in customLineup.proposers"
                :key="candidate.key"
                class="setup-model-strategy__candidate"
                role="listitem"
              >
                <span class="setup-model-strategy__candidate-main">
                  <span class="setup-model-strategy__candidate-label">{{ candidateLabel(candidate) }}</span>
                  <span class="setup-model-strategy__candidate-source">{{ roleLabel(candidate.role) }}</span>
                </span>
                <select
                  class="control-input setup-model-strategy__role-select"
                  :value="candidate.role"
                  :aria-label="t('setup.modelStrategy.roleSelectAria', { model: candidate.model })"
                  @change="emit('setEnsembleCandidateRole', candidate, ($event.target as HTMLSelectElement).value as EnsembleCandidateRole)"
                >
                  <option value="">{{ t('setup.modelStrategy.roleUnassigned') }}</option>
                  <option v-for="role in proposerRoles" :key="role" :value="role">{{ roleLabel(role) }}</option>
                  <option value="aggregator">{{ t('setup.modelStrategy.role_aggregator') }}</option>
                </select>
                <span class="setup-model-strategy__credential" :class="{ 'is-missing': candidate.credential && !candidate.credential.available }">
                  {{ credentialLabel(candidate) }}
                </span>
                <button
                  type="button"
                  class="setup-model-strategy__candidate-remove"
                  :aria-label="t('setup.modelStrategy.removeCandidateAria', { model: candidate.model })"
                  @click="emit('removeEnsembleCandidate', candidate)"
                >&times;</button>
              </div>
            </div>

            <p v-else class="setup-model-strategy__notice">
              {{ t('setup.modelStrategy.ensembleEmpty') }}
            </p>

            <p v-if="customLineup.belowMinimum && customLineup.proposers.length" class="setup-model-strategy__notice" data-testid="ensemble-below-minimum">
              {{ t('setup.modelStrategy.ensembleMinimum') }}
            </p>

            <p v-if="customLineup.capacity === 'warn'" class="setup-model-strategy__notice" data-testid="ensemble-capacity-warn">
              {{ t('setup.modelStrategy.capacityWarn', { calls: customLineup.facts.perTurnCalls }) }}
            </p>
            <p v-if="customLineup.capacity === 'full'" class="setup-model-strategy__notice" data-testid="ensemble-capacity-full">
              {{ t('setup.modelStrategy.capacityFull', { max: customLineup.maxProposers }) }}
            </p>
            <p v-if="customLineup.diversityWarning" class="setup-model-strategy__notice" data-testid="ensemble-diversity-warn">
              {{ t('setup.modelStrategy.diversityHint') }}
            </p>

            <p class="setup-model-strategy__facts" data-testid="ensemble-custom-facts">
              {{ t('setup.modelStrategy.effectiveFacts', {
                calls: customLineup.facts.perTurnCalls,
                quorum: customLineup.facts.quorum,
                proposers: customLineup.facts.proposerCount,
                proposerTimeout: customLineup.facts.proposerTimeoutSeconds,
                aggregatorTimeout: customLineup.facts.aggregatorTimeoutSeconds,
                grace: customLineup.facts.quorumGraceSeconds,
              }) }}
            </p>

            <div class="setup-model-strategy__candidate-add">
              <input
                v-model="newCandidateProvider"
                class="control-input"
                type="text"
                name="setup_model_strategy_add_candidate_provider"
                :placeholder="t('setup.modelStrategy.addCandidateProviderPlaceholder')"
                :aria-label="t('setup.modelStrategy.addCandidateProviderLabel')"
                @keydown.enter.prevent="submitCandidate"
              >
              <input
                v-model="newCandidateModel"
                class="control-input"
                type="text"
                name="setup_model_strategy_add_candidate_model"
                :placeholder="t('setup.modelStrategy.addCandidateModelPlaceholder')"
                :aria-label="t('setup.modelStrategy.addCandidateModelLabel')"
                @keydown.enter.prevent="submitCandidate"
              >
              <select
                v-model="newCandidateRole"
                class="control-input setup-model-strategy__role-select"
                name="setup_model_strategy_add_candidate_role"
                :aria-label="t('setup.modelStrategy.addCandidateRoleLabel')"
              >
                <option value="">{{ t('setup.modelStrategy.roleUnassigned') }}</option>
                <option v-for="role in proposerRoles" :key="role" :value="role">{{ roleLabel(role) }}</option>
                <option value="aggregator">{{ t('setup.modelStrategy.role_aggregator') }}</option>
              </select>
              <button
                type="button"
                class="btn"
                data-testid="setup-model-strategy-add-candidate"
                :disabled="!customLineup.canAddProposer && newCandidateRole !== 'aggregator'"
                @click="submitCandidate"
              >
                {{ t('setup.modelStrategy.addCandidate') }}
              </button>
            </div>
          </div>
        </template>

        <label class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">
              {{ t('setup.modelStrategy.quorumFailureLabel', {
                quorum: ensembleScheme === 'preset' ? panel.ensemble.presetFacts.quorum : customLineup.facts.quorum,
              }) }}
            </span>
            <span class="control-row__desc">
              {{ t('setup.modelStrategy.ensembleFailure', { provider: currentProvider, model: currentModel }) }}
            </span>
          </div>
          <div class="control-row__control">
            <select
              class="control-input"
              :value="panel.ensemble.allFailedPolicy"
              name="setup_model_strategy_all_failed_policy"
              @change="emit('updateEnsembleAllFailedPolicy', ($event.target as HTMLSelectElement).value)"
            >
              <option value="fallback_single">{{ t('setup.ensemble.allFailedFallback') }}</option>
              <option value="error">{{ t('setup.ensemble.allFailedError') }}</option>
            </select>
          </div>
        </label>
      </section>

      <section v-else class="control-section setup-model-strategy__detail">
        <div class="control-section__head">
          <h3 class="control-section__title">{{ t('setup.modelStrategy.singleTitle') }}</h3>
          <p class="control-section__desc">
            {{ t('setup.modelStrategy.singleDependency', { provider: currentProvider, model: currentModel }) }}
          </p>
        </div>
        <p class="setup-model-strategy__muted">{{ t('setup.modelStrategy.singleDesc') }}</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.setup-model-strategy {
  gap: var(--sp-3);
}

.setup-model-strategy__cards {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.setup-model-strategy__card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: grid;
  gap: var(--sp-1);
  min-height: 5.5rem;
  padding: var(--sp-2);
  text-align: left;
}

.setup-model-strategy__card:hover {
  border-color: color-mix(in srgb, var(--accent) 48%, var(--border));
}

.setup-model-strategy__card.is-active {
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-elevated));
  border-color: color-mix(in srgb, var(--accent) 62%, var(--border));
}

.setup-model-strategy__card-title {
  font-size: var(--fs-sm);
  font-weight: 700;
}

.setup-model-strategy__card-desc {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.35;
}

.setup-model-strategy__detail {
  border-top: 1px solid var(--border);
  padding-top: var(--sp-3);
}

.setup-model-strategy__candidate-list {
  display: grid;
  gap: var(--sp-1);
}

.setup-model-strategy__candidate-group {
  display: grid;
  gap: var(--sp-1);
}

.setup-model-strategy__group-label {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-weight: 700;
}

.setup-model-strategy__candidate-head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.setup-model-strategy__candidate {
  align-items: center;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  justify-content: space-between;
  padding: var(--sp-2);
}

.setup-model-strategy__candidate--aggregator {
  border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
}

.setup-model-strategy__candidate-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.setup-model-strategy__candidate-label {
  overflow-wrap: anywhere;
}

.setup-model-strategy__candidate-source {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.setup-model-strategy__credential {
  color: var(--text-muted);
  flex: 0 0 auto;
  font-size: var(--fs-xs);
}

.setup-model-strategy__credential.is-missing {
  color: var(--warn);
}

.setup-model-strategy__candidate-remove {
  align-items: center;
  background: none;
  border: none;
  border-radius: var(--radius-full);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: var(--fs-md);
  height: 1.5rem;
  justify-content: center;
  line-height: 1;
  padding: 0;
  width: 1.5rem;
}

.setup-model-strategy__candidate-remove:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.setup-model-strategy__candidate-add {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: minmax(7rem, 0.4fr) minmax(10rem, 1fr) minmax(7rem, auto) auto;
}

.setup-model-strategy__candidate-add .control-input {
  min-width: 0;
}

@media (max-width: 720px) {
  .setup-model-strategy__candidate-add {
    grid-template-columns: 1fr;
  }
}

.setup-model-strategy__notice {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 42%, var(--border));
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-xs);
  line-height: 1.4;
  margin: 0;
  padding: var(--sp-2);
}

.setup-model-strategy__notice--legacy {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.setup-model-strategy__pipeline {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.4;
  margin: 0;
  padding: var(--sp-2);
}

.setup-model-strategy__schemes {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.setup-model-strategy__scheme {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: grid;
  gap: var(--sp-1);
  padding: var(--sp-2);
  text-align: left;
}

.setup-model-strategy__scheme:hover {
  border-color: color-mix(in srgb, var(--accent) 48%, var(--border));
}

.setup-model-strategy__scheme.is-active {
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-elevated));
  border-color: color-mix(in srgb, var(--accent) 62%, var(--border));
}

.setup-model-strategy__scheme-title {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  font-size: var(--fs-sm);
  font-weight: 700;
  gap: var(--sp-1);
}

.setup-model-strategy__scheme-badge {
  background: var(--accent);
  border-radius: var(--radius-full);
  color: var(--accent-foreground);
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 1px var(--sp-2);
}

.setup-model-strategy__scheme-badge--soft {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.setup-model-strategy__scheme-desc {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.35;
}

.setup-model-strategy__count {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  margin-left: var(--sp-1);
}

.setup-model-strategy__capacity {
  display: flex;
  gap: var(--sp-1);
}

.setup-model-strategy__capacity-cell {
  background: var(--bg-hover);
  border-radius: var(--radius-xs);
  flex: 1;
  height: 6px;
}

.setup-model-strategy__capacity-cell.is-filled {
  background: var(--accent);
}

.setup-model-strategy__capacity-cell.is-warn {
  background: var(--warn);
}

.setup-model-strategy__candidate--inherited {
  border-style: dashed;
}

.setup-model-strategy__role-select {
  flex: 0 0 auto;
  font-size: var(--fs-xs);
  max-width: 9.5rem;
}

.setup-model-strategy__facts {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
  margin: 0;
  padding: var(--sp-2);
}

.setup-model-strategy__muted {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.45;
  margin: 0;
}

.setup-warning__action {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  display: block;
  font: inherit;
  font-weight: 600;
  margin-top: var(--sp-1);
  padding: 0;
}

.setup-warning__action:hover {
  text-decoration: underline;
}
</style>
