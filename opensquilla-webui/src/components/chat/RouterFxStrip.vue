<template>
  <div
    class="router-fx"
    :data-source="message.routerSource"
    :data-observe="message.routerObserve ? 'true' : undefined"
    :data-static="message.routerStatic ? 'true' : undefined"
    :data-settled="message.routerSettled ? 'true' : undefined"
    :data-panel="message.routerPanel || 'real-candidates'"
  >
    <template v-if="isEnsemblePanel">
      <button
        class="router-fx-ensemble"
        type="button"
        :aria-label="ensembleButtonLabel"
        :aria-expanded="inspectorOpen ? 'true' : 'false'"
        :aria-controls="inspectorId"
        :aria-busy="!isEnsembleDone ? 'true' : 'false'"
        :disabled="!hasInspector"
        data-testid="router-ensemble-toggle"
        @click="toggleInspector"
      >
        <span :class="['router-fx-ensemble__dot', { done: isEnsembleDone, pending: !hasEnsembleModels }]" aria-hidden="true"></span>
        <span class="router-fx-ensemble__label" role="status" aria-live="polite">{{ ensembleStatusLabel }}</span>
        <span class="router-fx-ensemble__meta">{{ ensembleMetaLabel }}</span>
        <span v-if="!isEnsembleDone" class="router-fx-ensemble__scan" aria-hidden="true"></span>
      </button>

      <div
        v-if="inspectorOpen && hasInspector"
        :id="inspectorId"
        class="router-fx-inspector"
        data-testid="router-ensemble-inspector"
      >
        <div class="router-fx-inspector__head">
          <span class="router-fx-inspector__title">{{ t('chat.routerFx.ensembleTraceTitle') }}</span>
          <span class="router-fx-inspector__mode">{{ ensembleInspectorMeta }}</span>
        </div>
        <div class="router-fx-inspector__rows">
          <div
            v-for="model in ensembleModels"
            :key="`${model.role}:${model.provider}:${model.model}`"
            class="router-fx-inspector__row"
            :class="{
              'router-fx-inspector__row--running': model.status === 'running',
              'router-fx-inspector__row--failed': model.status === 'failed',
            }"
            :data-status="model.status || undefined"
          >
            <span class="router-fx-inspector__role">{{ model.role }}</span>
            <span class="router-fx-inspector__model" :title="model.model">{{ model.modelShort }}</span>
            <span class="router-fx-inspector__usage" :title="model.error || undefined">
              <span
                v-if="model.status === 'running'"
                class="router-fx-inspector__spin"
                aria-hidden="true"
              ></span>
              <template v-else-if="model.status === 'failed'">{{ ensembleModelFailure(model) }}</template>
              <template v-else>{{ ensembleModelUsage(model) }}</template>
            </span>
          </div>
          <div
            v-if="!hasEnsembleModels"
            class="router-fx-inspector__row router-fx-inspector__row--empty"
            data-testid="router-ensemble-detail-unavailable"
          >
            <span class="router-fx-inspector__empty">{{ emptyTraceLabel }}</span>
          </div>
        </div>
        <div class="router-fx-inspector__foot">
          <span>{{ fallbackLabel }}</span>
          <span>{{ t('chat.routerFx.ensembleRouterPoolHidden') }}</span>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="router-fx-header">
        <span class="glyph">&#8592;</span>
        <span class="title">{{ t('chat.aiModelRouter') }}</span>
        <span class="glyph">&#8594;</span>
      </div>
      <div class="router-fx-grid" :style="gridStyle">
        <div
          v-for="(cell, cellIndex) in gridCells"
          :key="cell.tiers?.join(':') || `${cell.displayName}-${cellIndex}`"
          class="router-fx-cell"
          :data-cell-idx="cellIndex"
          :class="{ win: cellIndex === message.winnerIdx }"
        >
          <span class="nm" :title="cell.displayName" :aria-label="cell.displayName">
            <span class="nm-base">{{ cell.displayName }}</span>
            <span class="nm-win" aria-hidden="true">{{ cell.displayName }}</span>
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatEnsembleMetaModel, ChatRenderedMessage } from '@/types/chat'

const { t } = useI18n()

const props = defineProps<{
  message: ChatRenderedMessage
}>()

const inspectorOpen = ref(false)
const gridCells = computed(() => props.message.gridCells || [])
const ensemble = computed(() => props.message.ensemble)
const ensembleModels = computed(() => ensemble.value?.models || [])
const isEnsemblePanel = computed(() => props.message.routerPanel === 'llm-ensemble')
const hasEnsembleModels = computed(() => ensembleModels.value.length > 0)
const isEnsembleHandoff = computed(() => props.message.routerState === 'handoff' && !hasEnsembleModels.value)
// Ensemble strips are trace surfaces, not only animations: keep them openable
// even while candidate details are still unknown so the empty/pending state is
// visible instead of looking broken.
const hasInspector = computed(() =>
  isEnsemblePanel.value || hasEnsembleModels.value || (ensemble.value?.modelCount || 0) > 0,
)
// A live ensemble is complete only after the aggregator has reached a terminal
// state. Proposer completion alone is the handoff into synthesis, not the end.
const hasAggregator = computed(() =>
  ensembleModels.value.some(member => member.role === 'aggregator'),
)
const allMembersTerminal = computed(() =>
  hasEnsembleModels.value && ensembleModels.value.every(
    member => member.status === 'done' || member.status === 'failed',
  ),
)
const isEnsembleDone = computed(
  () => (hasAggregator.value && allMembersTerminal.value)
    || (Boolean(ensemble.value) && props.message.routerSettled === true),
)
const isLegacyGrid = computed(() => props.message.routerPanel === 'legacy-grid')
const gridColumnCount = computed(() => isLegacyGrid.value ? 5 : Math.min(4, Math.max(2, gridCells.value.length)))
const mobileGridColumnCount = computed(() => isLegacyGrid.value ? 3 : (gridCells.value.length > 2 ? 2 : Math.max(1, gridCells.value.length)))
// The terminal breakdown contains the aggregator as a model row, while the
// router label describes proposer candidates. Prefer the trace's explicit
// candidate count and otherwise exclude the aggregator row.
const candidateCount = computed(() => {
  const traced = Number(ensemble.value?.totalCandidates || 0)
  if (traced > 0) return traced
  const proposers = ensembleModels.value.filter(member => member.role !== 'aggregator').length
  return proposers || ensemble.value?.modelCount || ensembleModels.value.length
})
const totalCandidates = computed(() => ensemble.value?.totalCandidates || 0)
const hasKnownCandidateCount = computed(() => candidateCount.value > 0)
const emptyTraceLabel = computed(() =>
  isEnsembleHandoff.value
    ? t('chat.routerFx.ensembleTraceUnavailable')
    : hasKnownCandidateCount.value
    ? t('chat.routerFx.ensembleDetailUnavailable', { count: candidateCount.value })
    : t('chat.routerFx.ensembleTracePending'),
)
const inspectorId = computed(() => `router-ensemble-inspector-${props.message.messageId || props.message.id || 'current'}`)
const gridStyle = computed<Record<string, string>>(() => {
  return {
    '--router-fx-cols': String(gridColumnCount.value),
    '--router-fx-mobile-cols': String(mobileGridColumnCount.value),
  }
})
const ensembleStatusLabel = computed(() => {
  if (isEnsembleHandoff.value) return t('chat.routerFx.ensembleHandedOff')
  if (!hasEnsembleModels.value) return t('chat.routerFx.ensembleSelecting')
  if (isEnsembleDone.value) return t('chat.routerFx.ensembleDone', { count: candidateCount.value })
  return t('chat.routerFx.ensembleRunning', { count: candidateCount.value })
})
const ensembleMetaLabel = computed(() =>
  hasInspector.value ? t('chat.routerFx.ensembleViewTrace') : t('chat.routerFx.ensembleMode'),
)
const ensembleButtonLabel = computed(() => {
  return hasInspector.value
    ? t('chat.routerFx.ensembleToggleTrace')
    : ensembleStatusLabel.value
})
const ensembleInspectorMeta = computed(() => {
  const pool = totalCandidates.value > 0 ? totalCandidates.value : candidateCount.value
  if (pool <= 0) return t('chat.routerFx.ensembleTelemetryPendingMeta')
  return t('chat.routerFx.ensemblePlanMeta', { count: pool })
})
const fallbackLabel = computed(() => {
  if (!ensemble.value?.fallbackUsed) return t('chat.routerFx.ensembleFallbackNone')
  return ensemble.value.fallbackReason
    ? t('chat.routerFx.ensembleFallbackReason', { reason: ensemble.value.fallbackReason })
    : t('chat.routerFx.ensembleFallbackUsed')
})

function toggleInspector() {
  if (!hasInspector.value) return
  inspectorOpen.value = !inspectorOpen.value
}

function ensembleModelUsage(model: ChatEnsembleMetaModel): string {
  const total = model.input + model.output
  const usage = total > 0 ? t('chat.routerFx.ensembleTokens', { count: total }) : t('chat.routerFx.ensembleUsed')
  const elapsed = ensembleModelElapsed(model)
  return elapsed ? `${usage} · ${elapsed}` : usage
}

function ensembleModelFailure(model: ChatEnsembleMetaModel): string {
  const failed = t('chat.routerFx.ensembleFailed')
  const elapsed = ensembleModelElapsed(model)
  return elapsed ? `${failed} · ${elapsed}` : failed
}

function ensembleModelElapsed(model: ChatEnsembleMetaModel): string {
  const elapsedMs = Number(model.elapsedMs || 0)
  if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) return ''
  const seconds = elapsedMs / 1000
  return `${seconds >= 10 ? Math.round(seconds) : Number(seconds.toFixed(1))}s`
}
</script>

<style scoped>
.router-fx {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(calc(100% - 48px), 620px);
  margin: 0.375rem auto 0.25rem;
  padding: 0;
  user-select: none;
  --router-accent: var(--accent);
  --router-bg: var(--bg-surface);
  --router-surface: var(--bg-elevated);
  --router-hairline: var(--hairline);
  --router-text: var(--text);
  --router-muted: var(--text-dim);
  --router-danger: var(--danger);
  --router-cell-bg: color-mix(in srgb, var(--bg-surface) 72%, transparent);
}

.router-fx-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 2px 0 0;
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.44em;
  white-space: nowrap;
}

@media (max-width: 480px) {
  .router-fx-header {
    gap: 8px;
    font-size: 10px;
    letter-spacing: 0.18em;
  }

  .router-fx-header .title {
    padding-left: 0.18em;
  }
}

.router-fx-header .title {
  padding-left: 0.44em;
}

.router-fx-header .glyph {
  color: var(--router-accent);
  font-size: 12px;
  letter-spacing: 0;
}

.router-fx-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--router-fx-cols, 2), 1fr);
  grid-auto-rows: 34px;
  gap: 4px;
  padding: 8px;
  background:
    radial-gradient(color-mix(in srgb, var(--router-text) 8%, transparent) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
    var(--router-surface);
  border: 1px solid var(--router-hairline);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.router-fx-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 6px;
  background: var(--router-cell-bg);
  border: 1px solid var(--router-hairline);
  border-radius: var(--radius-sm);
  color: var(--router-text);
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: transform var(--dur-base) var(--ease-out), background var(--dur-base) var(--ease-out), color var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out), box-shadow var(--dur-base) var(--ease-out);
}

.router-fx-ensemble {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 44px;
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--router-hairline);
  border-radius: var(--radius-md);
  background:
    radial-gradient(color-mix(in srgb, var(--router-text) 6%, transparent) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
    var(--router-surface);
  color: var(--router-text);
  font: inherit;
  text-align: left;
  overflow: hidden;
  cursor: pointer;
  transition: background var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out);
}

.router-fx-ensemble:hover:not(:disabled),
.router-fx-ensemble[aria-expanded="true"] {
  border-color: color-mix(in srgb, var(--router-accent) 48%, var(--router-hairline));
  background:
    radial-gradient(color-mix(in srgb, var(--router-text) 6%, transparent) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
    color-mix(in srgb, var(--router-accent) 3%, var(--router-surface));
}

.router-fx-ensemble:disabled {
  cursor: default;
}

.router-fx-ensemble__dot {
  flex: 0 0 auto;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--router-accent);
  box-shadow: 0 0 11px color-mix(in srgb, var(--router-accent) 72%, transparent);
  animation: router-fx-ensemble-beat 1.55s var(--ease-out) infinite;
}

.router-fx-ensemble__dot.pending {
  background: var(--router-muted);
  box-shadow: none;
  animation-name: router-fx-ensemble-pending;
}

.router-fx-ensemble__dot.done {
  background: var(--ok);
  box-shadow: 0 0 10px color-mix(in srgb, var(--ok) 58%, transparent);
  animation: none;
}

.router-fx-ensemble__label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--router-text);
  font-size: 12.5px;
  font-weight: 650;
  white-space: nowrap;
}

.router-fx-ensemble__meta {
  flex: 0 0 auto;
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  white-space: nowrap;
}

.router-fx-ensemble__scan {
  position: absolute;
  left: 11px;
  right: 11px;
  bottom: 5px;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--router-accent) 20%, transparent), var(--router-accent), color-mix(in srgb, var(--router-accent) 18%, transparent), transparent);
  transform-origin: center;
  animation: router-fx-ensemble-sweep 2.8s var(--ease-out) infinite;
}

.router-fx-inspector {
  position: relative;
  margin-top: 6px;
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--router-accent) 26%, var(--router-hairline));
  border-radius: var(--radius-md);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--router-accent) 4%, transparent), transparent 42%),
    var(--router-bg);
  box-shadow: var(--shadow-lg);
}

.router-fx-inspector::before {
  content: '';
  position: absolute;
  top: -7px;
  left: 50%;
  width: 1px;
  height: 7px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--router-accent) 60%, transparent), transparent);
}

.router-fx-inspector__head,
.router-fx-inspector__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.router-fx-inspector__head {
  padding-bottom: 8px;
  border-bottom: 1px solid color-mix(in srgb, var(--router-hairline) 78%, transparent);
}

.router-fx-inspector__title {
  color: var(--router-text);
  font-size: 12px;
  font-weight: 700;
}

.router-fx-inspector__mode,
.router-fx-inspector__foot {
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
}

.router-fx-inspector__rows {
  display: grid;
  gap: 5px;
  margin-top: 8px;
}

.router-fx-inspector__row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) 64px;
  align-items: center;
  gap: 7px;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--router-hairline) 80%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--router-bg) 64%, transparent);
  font-family: var(--font-mono);
  font-size: 9px;
}

.router-fx-inspector__role {
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--router-muted);
  text-transform: uppercase;
  white-space: nowrap;
}

.router-fx-inspector__model {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--router-text);
  font-weight: 650;
  white-space: nowrap;
}

.router-fx-inspector__usage {
  color: var(--router-accent);
  text-align: right;
  white-space: nowrap;
}

.router-fx-inspector__row--empty {
  grid-template-columns: 1fr;
  justify-items: start;
}

.router-fx-inspector__empty {
  color: var(--router-muted);
  text-transform: none;
}

.router-fx-inspector__row--running .router-fx-inspector__model {
  color: var(--router-accent);
}

.router-fx-inspector__row--failed .router-fx-inspector__model,
.router-fx-inspector__row--failed .router-fx-inspector__usage {
  color: var(--danger);
}

.router-fx-inspector__spin {
  display: inline-block;
  width: 8px;
  height: 8px;
  border: 1.4px solid color-mix(in srgb, var(--router-accent) 32%, transparent);
  border-top-color: var(--router-accent);
  border-radius: 50%;
  animation: router-fx-inspector-spin 0.8s linear infinite;
}

@keyframes router-fx-inspector-spin {
  to {
    transform: rotate(360deg);
  }
}

.router-fx-inspector__foot {
  margin-top: 8px;
}

.router-fx[data-panel="legacy-grid"] .router-fx-grid {
  grid-auto-rows: 30px;
}

.router-fx-cell .nm {
  display: grid;
  max-width: 100%;
  min-width: 0;
}

/* Normal and bold name variants are stacked from first paint so the winner
   reveal is a pure opacity crossfade: the cell never reflows text. */
.router-fx-cell .nm-base,
.router-fx-cell .nm-win {
  grid-area: 1 / 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.router-fx-cell .nm-win {
  font-weight: 600;
  opacity: 0;
}

.router-fx-cell.win {
  font-style: normal;
  animation: router-fx-winner-reveal var(--dur-enter) var(--ease-out) both;
}

.router-fx-cell.win .nm-base {
  animation: router-fx-winner-name-swap-out var(--dur-enter) var(--ease-out) both;
}

.router-fx-cell.win .nm-win {
  color: var(--router-accent);
  animation: router-fx-winner-name-swap-in var(--dur-enter) var(--ease-out) both;
}

.router-fx[data-source="fallback"] .router-fx-cell.win .nm-win {
  color: var(--router-danger);
}

.router-fx-cell.win::after {
  content: '';
  position: absolute;
  top: 3px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--router-accent);
  opacity: 1;
  animation: router-fx-winner-dot-reveal var(--dur-enter) var(--ease-out) both;
}

.router-fx[data-source="fallback"] .router-fx-cell.win {
  animation-name: router-fx-winner-reveal-fallback;
}

.router-fx[data-source="fallback"] .router-fx-cell.win::after {
  background: var(--router-danger);
}

.router-fx[data-settled="true"] .router-fx-cell,
.router-fx[data-settled="true"] .router-fx-cell.win,
.router-fx[data-settled="true"] .router-fx-cell.win::after,
.router-fx[data-settled="true"] .router-fx-cell .nm-base,
.router-fx[data-settled="true"] .router-fx-cell .nm-win,
.router-fx[data-settled="true"] .router-fx-header .glyph {
  animation: none !important;
}

.router-fx[data-settled="true"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
  border-color: var(--router-accent);
}

.router-fx[data-settled="true"] .router-fx-cell.win .nm-base {
  opacity: 0;
}

.router-fx[data-settled="true"] .router-fx-cell.win .nm-win {
  opacity: 1;
}

.router-fx[data-settled="true"][data-source="fallback"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
  border-color: var(--router-danger);
}

@keyframes router-fx-winner-reveal {
  0% {
    background: var(--router-cell-bg);
    border-color: var(--router-hairline);
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
    border-color: var(--router-accent);
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
  }
}

@keyframes router-fx-winner-reveal-fallback {
  0% {
    background: var(--router-cell-bg);
    border-color: var(--router-hairline);
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
    border-color: var(--router-danger);
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
  }
}

@keyframes router-fx-winner-name-swap-out {
  0% { opacity: 1; }
  100% { opacity: 0; }
}

@keyframes router-fx-winner-name-swap-in {
  0% { opacity: 0; }
  100% { opacity: 1; }
}

@keyframes router-fx-winner-dot-reveal {
  0% { opacity: 0.72; }
  100% { opacity: 1; }
}

@keyframes router-fx-ensemble-beat {
  0%, 100% { opacity: 0.42; transform: scale(0.82); }
  50% { opacity: 1; transform: scale(1); }
}

@keyframes router-fx-ensemble-pending {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 0.85; }
}

@keyframes router-fx-ensemble-sweep {
  0%, 100% { transform: scaleX(0.18); opacity: 0.28; }
  48% { transform: scaleX(0.86); opacity: 0.95; }
}

.router-fx[data-observe="true"] {
  opacity: 0.55;
}

.router-fx[data-observe="true"] .router-fx-header::after {
  content: 'observe';
  margin-left: 12px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--router-muted) 16%, transparent);
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.router-fx[data-observe="true"] .router-fx-cell.win {
  animation: none;
  background: color-mix(in srgb, var(--router-muted) 8%, transparent);
  border-color: color-mix(in srgb, var(--router-muted) 35%, transparent);
  color: var(--router-muted);
  font-weight: 500;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-base,
.router-fx[data-observe="true"] .router-fx-cell.win .nm-win {
  animation: none;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-base {
  opacity: 1;
}

.router-fx[data-observe="true"] .router-fx-cell.win .nm-win {
  opacity: 0;
}

.router-fx[data-static="true"] .router-fx-cell,
.router-fx[data-static="true"] .router-fx-cell .nm-base,
.router-fx[data-static="true"] .router-fx-cell .nm-win {
  animation: none;
}

.router-fx[data-static="true"] .router-fx-cell.win {
  animation: none;
  background: color-mix(in srgb, var(--router-accent) 9%, var(--router-bg));
  border-color: var(--router-accent);
  transform: translateY(-1px);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win .nm-base {
  opacity: 0;
}

.router-fx[data-static="true"] .router-fx-cell.win .nm-win {
  opacity: 1;
}

.router-fx[data-static="true"][data-source="fallback"] .router-fx-cell.win {
  background: color-mix(in srgb, var(--router-danger) 9%, var(--router-bg));
  border-color: var(--router-danger);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win::after {
  animation: none;
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .router-fx-cell,
  .router-fx-cell .nm-base,
  .router-fx-cell .nm-win,
  .router-fx-ensemble__dot,
  .router-fx-ensemble__scan,
  .router-fx-inspector__spin {
    animation: none !important;
    transition: none !important;
  }
}

@media (max-width: 640px) {
  .router-fx {
    width: min(calc(100% - 24px), 620px);
  }

  .router-fx-grid {
    grid-template-columns: repeat(var(--router-fx-mobile-cols, var(--router-fx-cols, 2)), 1fr);
    grid-auto-rows: 30px;
    padding: 6px;
    gap: 3px;
  }

  .router-fx-cell {
    font-size: 10px;
    padding: 0 5px;
  }

  .router-fx-header {
    font-size: 9.5px;
    letter-spacing: 0.36em;
  }

  .router-fx-ensemble {
    align-items: flex-start;
    flex-direction: column;
    gap: 5px;
  }

  .router-fx-inspector__row {
    grid-template-columns: 64px minmax(0, 1fr);
  }

  .router-fx-inspector__usage {
    display: none;
  }
}
</style>
