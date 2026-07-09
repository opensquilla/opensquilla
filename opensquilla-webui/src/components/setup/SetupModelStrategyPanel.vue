<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ControlSwitch from '@/components/ControlSwitch.vue'
import SetupTierTable from '@/components/setup/SetupTierTable.vue'
import type { ModelStrategy } from '@/composables/setup/useSetupModelStrategyForm'
import type { SetupTierRow } from '@/composables/setup/useSetupRouterForm'
import type { DiscoveredModel } from '@/composables/setup/useSetupProviderForm'
import type {
  EnsembleCandidateView,
  EnsembleCredentialStatus,
  EnsembleFixedOpenRouterProfile,
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
  discoveredModels?: DiscoveredModel[]
  discoveredModelsProvider?: string
  discoveredModelSource?: string
  hasMixedTierProviders: boolean
}

interface EnsemblePanelContract {
  enabled: boolean
  selectionMode: string
  modelOptions: string[]
  candidates: readonly { provider: string; model: string; source?: string; enabled?: boolean }[]
  tierCandidates: readonly EnsembleCandidateView[]
  customCandidates: readonly EnsembleCandidateView[]
  fixedOpenRouterProfile: EnsembleFixedOpenRouterProfile | null
  showOpenRouterFixedSwitch: boolean
  openRouterCustomEnsemble: boolean
  minSuccessfulProposers: number
  allFailedPolicy: string
  showModelOptions: boolean
  showCandidateEditor: boolean
  showOpenrouterHint: boolean
  advancedOpen: boolean
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
  updateEnsembleEnabled: [value: boolean]
  updateEnsembleSelectionMode: [value: string]
  addEnsembleModelOption: [value: string]
  removeEnsembleModelOption: [value: string]
  addEnsembleCandidate: [provider: string, model: string]
  removeEnsembleCandidate: [candidate: EnsembleCandidateView]
  resetEnsembleCandidates: []
  updateOpenrouterCustomEnsemble: [value: boolean]
  updateEnsembleMinSuccessful: [value: number]
  updateEnsembleAllFailedPolicy: [value: string]
  goToSection: [value: string]
}>()

const showRouterDetails = computed(() => props.panel.activeStrategy === 'router')
const routerEditingDisabled = computed(() => !props.panel.hasSavedProvider)
const newCandidateProvider = ref('')
const newCandidateModel = ref('')

function displayProvider(provider: string): string {
  const normalized = String(provider || '').trim().toLowerCase()
  if (!normalized) return props.panel.providerLabel
  if (normalized === 'openrouter') return 'OpenRouter'
  if (normalized === 'openai') return 'OpenAI'
  if (normalized === 'deepseek') return 'DeepSeek'
  if (normalized === 'anthropic') return 'Anthropic'
  if (normalized === 'groq') return 'Groq'
  return normalized
}

const defaultRouteModel = computed(() => {
  const tier = props.panel.router.tierRows.find(row => row.name === props.panel.router.routerDefaultTier)
    || props.panel.router.tierRows[0]
  return tier?.model || ''
})

const defaultRouteProvider = computed(() => {
  const tier = props.panel.router.tierRows.find(row => row.name === props.panel.router.routerDefaultTier)
    || props.panel.router.tierRows[0]
  return displayProvider(tier?.provider || '')
})

const dependencyModel = computed(() => defaultRouteModel.value || props.panel.providerLabel)
const dependencyProvider = computed(() => defaultRouteProvider.value || props.panel.providerLabel)

const ensembleCandidates = computed(() => {
  return [
    ...props.panel.ensemble.tierCandidates,
    ...props.panel.ensemble.customCandidates,
  ]
})

function submitCandidate() {
  const provider = newCandidateProvider.value.trim()
  const model = newCandidateModel.value.trim()
  if (!provider || !model) return
  emit('addEnsembleCandidate', provider, model)
  newCandidateProvider.value = ''
  newCandidateModel.value = ''
}

function resetCandidates() {
  newCandidateProvider.value = ''
  newCandidateModel.value = ''
  emit('resetEnsembleCandidates')
}

function candidateLabel(candidate: EnsembleCandidateView): string {
  return `${displayProvider(candidate.provider)} · ${candidate.model}`
}

function candidateSourceKey(candidate: EnsembleCandidateView): string {
  if (candidate.source === 'tier') return 'setup.modelStrategy.candidateSourceTier'
  if (candidate.source === 'legacy_model_options') return 'setup.modelStrategy.candidateSourceLegacy'
  if (candidate.source === 'openrouter_fixed') return 'setup.modelStrategy.candidateSourceOpenRouterFixed'
  return 'setup.modelStrategy.candidateSourceCustom'
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
            {{ t('setup.modelStrategy.routerDependency', { provider: dependencyProvider, model: dependencyModel }) }}
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
          :models="panel.router.discoveredModels || []"
          :models-provider="panel.router.discoveredModelsProvider || ''"
          :model-source="panel.router.discoveredModelSource || 'none'"
          @update-tier-field="(name, key, value) => emit('updateTierField', name, key, value)"
        />
      </section>

      <section v-else-if="panel.activeStrategy === 'ensemble'" class="control-section setup-model-strategy__detail">
        <div class="control-section__head">
          <h3 class="control-section__title">{{ t('setup.modelStrategy.ensembleTitle') }}</h3>
          <p class="control-section__desc">
            {{ t('setup.modelStrategy.ensembleDependency', { provider: dependencyProvider, model: dependencyModel }) }}
          </p>
        </div>

        <label v-if="panel.ensemble.showOpenRouterFixedSwitch" class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.modelStrategy.customizeOpenRouterLabel') }}</span>
            <span class="control-row__desc">{{ t('setup.modelStrategy.customizeOpenRouterDesc') }}</span>
          </div>
          <div class="control-row__control">
            <ControlSwitch
              :checked="panel.ensemble.openRouterCustomEnsemble"
              name="setup_model_strategy_openrouter_custom"
              :aria-label="t('setup.modelStrategy.customizeOpenRouterLabel')"
              @change="(value) => emit('updateOpenrouterCustomEnsemble', value)"
            />
          </div>
        </label>

        <div v-if="panel.ensemble.fixedOpenRouterProfile" class="control-row control-row--stack">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.modelStrategy.openrouterFixedTitle', { provider: panel.ensemble.fixedOpenRouterProfile.providerLabel }) }}</span>
            <span class="control-row__desc">{{ t('setup.modelStrategy.openrouterFixedDesc', { provider: panel.ensemble.fixedOpenRouterProfile.providerLabel }) }}</span>
          </div>
          <div class="setup-model-strategy__candidate-list" role="list">
            <div
              v-for="candidate in panel.ensemble.fixedOpenRouterProfile.proposers"
              :key="candidate.key"
              class="setup-model-strategy__candidate"
              role="listitem"
            >
              <span class="setup-model-strategy__candidate-main">
                <span class="setup-model-strategy__candidate-label">{{ candidateLabel(candidate) }}</span>
                <span class="setup-model-strategy__candidate-source">{{ t('setup.modelStrategy.openrouterFixedProposer') }}</span>
              </span>
              <span class="setup-model-strategy__credential" :class="{ 'is-missing': candidate.credential && !candidate.credential.available }">
                {{ credentialLabel(candidate) }}
              </span>
            </div>
            <div class="setup-model-strategy__candidate setup-model-strategy__candidate--aggregator" role="listitem">
              <span class="setup-model-strategy__candidate-main">
                <span class="setup-model-strategy__candidate-label">
                  {{ candidateLabel(panel.ensemble.fixedOpenRouterProfile.aggregator) }}
                </span>
                <span class="setup-model-strategy__candidate-source">{{ t('setup.modelStrategy.openrouterFixedAggregator') }}</span>
              </span>
              <span
                class="setup-model-strategy__credential"
                :class="{ 'is-missing': panel.ensemble.fixedOpenRouterProfile.aggregator.credential && !panel.ensemble.fixedOpenRouterProfile.aggregator.credential.available }"
              >
                {{ credentialLabel(panel.ensemble.fixedOpenRouterProfile.aggregator) }}
              </span>
            </div>
          </div>
        </div>

        <div v-else class="control-row control-row--stack">
          <div class="setup-model-strategy__candidate-head">
            <div class="control-row__label-block">
              <span class="control-row__label">{{ t('setup.modelStrategy.candidatesLabel') }}</span>
              <span class="control-row__desc">{{ t('setup.modelStrategy.candidatesDesc') }}</span>
            </div>
            <button
              type="button"
              class="btn"
              data-testid="setup-model-strategy-reset-candidates"
              :disabled="panel.ensemble.customCandidates.length === 0"
              @click="resetCandidates"
            >
              {{ t('setup.modelStrategy.resetCandidates') }}
            </button>
          </div>

          <div v-if="panel.ensemble.tierCandidates.length" class="setup-model-strategy__candidate-group">
            <span class="setup-model-strategy__group-label">{{ t('setup.modelStrategy.candidateSourceTier') }}</span>
            <div class="setup-model-strategy__candidate-list" role="list">
              <div
                v-for="candidate in panel.ensemble.tierCandidates"
                :key="candidate.key"
                class="setup-model-strategy__candidate"
                role="listitem"
              >
                <span class="setup-model-strategy__candidate-main">
                  <span class="setup-model-strategy__candidate-label">{{ candidateLabel(candidate) }}</span>
                  <span class="setup-model-strategy__candidate-source">{{ t(candidateSourceKey(candidate)) }}</span>
                </span>
                <span class="setup-model-strategy__credential" :class="{ 'is-missing': candidate.credential && !candidate.credential.available }">
                  {{ credentialLabel(candidate) }}
                </span>
              </div>
            </div>
          </div>

          <div v-if="panel.ensemble.customCandidates.length" class="setup-model-strategy__candidate-group">
            <span class="setup-model-strategy__group-label">{{ t('setup.modelStrategy.customCandidatesLabel') }}</span>
            <div class="setup-model-strategy__candidate-list" role="list">
            <div
              v-for="candidate in panel.ensemble.customCandidates"
              :key="candidate.key"
              class="setup-model-strategy__candidate"
              role="listitem"
            >
              <span class="setup-model-strategy__candidate-main">
                <span class="setup-model-strategy__candidate-label">{{ candidateLabel(candidate) }}</span>
                <span class="setup-model-strategy__candidate-source">
                  {{ t(candidateSourceKey(candidate)) }}
                </span>
              </span>
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
          </div>

          <p
            v-if="!panel.ensemble.tierCandidates.length && !panel.ensemble.customCandidates.length"
            class="setup-model-strategy__notice"
          >
            {{ t('setup.modelStrategy.ensembleEmpty') }}
          </p>

          <div v-if="panel.ensemble.showCandidateEditor" class="setup-model-strategy__candidate-add">
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
            <button
              type="button"
              class="btn"
              data-testid="setup-model-strategy-add-candidate"
              @click="submitCandidate"
            >
              {{ t('setup.modelStrategy.addCandidate') }}
            </button>
          </div>
        </div>

        <p v-if="!panel.ensemble.fixedOpenRouterProfile && ensembleCandidates.length === 1" class="setup-model-strategy__notice">
          {{ t('setup.modelStrategy.ensembleMinimum') }}
        </p>

        <label class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">{{ t('setup.modelStrategy.ensembleFailureLabel') }}</span>
            <span class="control-row__desc">
              {{ t('setup.modelStrategy.ensembleFailure', { provider: dependencyProvider, model: dependencyModel }) }}
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
            {{ t('setup.modelStrategy.singleDependency', { provider: panel.providerLabel, model: dependencyModel }) }}
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
  grid-template-columns: minmax(7rem, 0.45fr) minmax(12rem, 1fr) auto;
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
