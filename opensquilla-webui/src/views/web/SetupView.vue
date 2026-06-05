<template>
  <section class="setup">
    <header class="setup__head">
      <div>
        <p class="setup__kicker">OpenSquilla setup</p>
        <h2>{{ hasSetupAction ? 'Action needed' : 'Ready to run' }}</h2>
      </div>
      <div class="setup__head-aside">
        <button type="button" class="setup__exit" aria-label="Exit setup and return to Overview" @click="router.push('/overview')">
          <span aria-hidden="true">&larr;</span><span>Exit setup</span>
        </button>
        <div class="setup__status" :class="hasSetupAction ? 'is-warn' : 'is-ok'">
          {{ hasSetupAction ? 'Action needed' : 'Ready' }}
        </div>
        <ul v-if="onboardingReasons.length > 0" class="setup-reasons" aria-label="Setup actions needed">
          <li v-for="(reason, i) in onboardingReasons" :key="i">{{ reason }}</li>
        </ul>
      </div>
    </header>

    <nav class="setup-stepper" aria-label="Setup steps">
      <button
        v-for="(s, idx) in STEPS"
        :key="s.id"
        class="setup-stepper__item"
        :class="{ 'is-active': step === s.id }"
        :aria-label="`${s.label}: ${stepStatus(s.id).label}`"
        @click="setStep(s.id)"
      >
        <span class="setup-stepper__num">{{ idx + 1 }}</span>
        <span class="setup-stepper__label">{{ s.label }}</span>
        <small class="setup-stepper__state" :class="stepStatus(s.id).tone">{{ stepStatus(s.id).label }}</small>
      </button>
    </nav>

    <div class="setup__body">
      <!-- Provider step -->
      <SetupProviderPanel
        v-if="step === 'provider'"
        :panel="providerPanel"
        @update-provider-selected="selectProvider"
        @provider-change="onProviderChange"
        @update-provider-field="updateProviderField"
        @copy="copyCommand"
        @save="saveProvider"
        @next="setStep('router')"
      />

      <!-- Router step -->
      <SetupRouterPanel
        v-else-if="step === 'router'"
        :panel="routerPanel"
        @update-router-mode="setRouterMode"
        @update-router-default-tier="setRouterDefaultTier"
        @update-tier-field="updateTierField"
        @back="setStep('provider')"
        @save="saveRouter"
        @next="setStep('channels')"
      />

      <!-- Channels step -->
      <SetupChannelsPanel
        v-else-if="step === 'channels'"
        :panel="channelsPanel"
        @update-channel-type="selectChannelType"
        @channel-type-change="onChannelTypeChange"
        @update-channel-field="updateChannelField"
        @save="saveChannel"
        @back="setStep('router')"
        @next="setStep('extras')"
      />

      <!-- Extras step -->
      <SetupCapabilitiesPanel
        v-else-if="step === 'extras'"
        :panel="capabilitiesPanel"
        @update-field="updateCapabilityField"
        @search-provider-change="onSearchProviderChange"
        @memory-provider-change="onMemoryProviderChange"
        @image-provider-change="onImageProviderChange"
        @save-search="saveSearch"
        @save-memory="saveMemory"
        @save-image="saveImage"
        @copy="copyCommand"
        @back="setStep('channels')"
        @next="setStep('finish')"
      />

      <!-- Finish step -->
      <section v-else-if="step === 'finish'" class="setup-panel">
        <header class="setup-panel__head">
          <h3>Finish</h3>
          <p>{{ status.configPath || '' }}</p>
        </header>
        <div class="setup-cli">
          <section v-if="fixCommands.length > 0" class="setup-cli__group" aria-label="Fix now">
            <div class="setup-cli__group-head"><h4>Fix now</h4></div>
            <SetupCommandBlock
              v-for="cmd in fixCommands"
              :key="cmd.label"
              class="setup-cli__row"
              :label="cmd.label"
              :command="cmd.command"
              @copy="copyCommand"
            />
          </section>
          <section class="setup-cli__group" aria-label="CLI handoff">
            <div class="setup-cli__group-head"><h4>CLI handoff</h4></div>
            <SetupCommandBlock
              v-for="cmd in handoffCommands"
              :key="cmd.label"
              class="setup-cli__row"
              :label="cmd.label"
              :command="cmd.command"
              @copy="copyCommand"
            />
          </section>
          <section class="setup-cli__group" aria-label="CLI recipes">
            <div class="setup-cli__group-head"><h4>CLI recipes</h4></div>
            <SetupCommandBlock
              v-for="cmd in recipeCommands"
              :key="cmd.label"
              class="setup-cli__row"
              :label="cmd.label"
              :command="cmd.command"
              @copy="copyCommand"
            />
          </section>
        </div>
        <div class="setup-summary">
          <div><span>Provider</span><strong>{{ providerSummary }}</strong></div>
          <div><span>Model</span><strong>{{ modelSummary }}</strong></div>
          <div v-if="providerProxy"><span>Proxy</span><strong>{{ providerProxy }}</strong></div>
          <div><span>Router</span><strong>{{ routerSummary }}</strong></div>
          <div><span>Channels</span><strong>{{ String(status.channelCount || 0) }}</strong></div>
        </div>
        <div v-if="readinessEntries.length > 0" class="setup-readiness" aria-label="Onboarding readiness">
          <div v-if="requiredReadiness.length > 0" class="setup-readiness__group">
            <h4>Required setup</h4>
            <div v-for="[name, detail] in requiredReadiness" :key="name" class="setup-readiness__row" :class="readinessTone(detail, name)">
              <span>{{ detail.label || name }}</span>
              <strong>{{ readinessStatusLabel(detail, name) }}</strong>
              <small>{{ detail.required ? 'Required' : 'Optional' }}</small>
              <button v-if="setupStepForSection(name, detail)" type="button" class="setup-readiness__action" :aria-label="readinessActionAriaLabel(detail, name)" :title="readinessActionAriaLabel(detail, name)" @click="setStep(setupStepForSection(name, detail)!)">
                {{ readinessActionLabel(detail, name) }}
              </button>
              <em v-if="detail.detail" class="setup-readiness__detail">{{ detail.detail }}</em>
            </div>
          </div>
          <div v-if="optionalReadiness.length > 0" class="setup-readiness__group">
            <h4>Optional capabilities</h4>
            <div v-for="[name, detail] in optionalReadiness" :key="name" class="setup-readiness__row" :class="readinessTone(detail, name)">
              <span>{{ detail.label || name }}</span>
              <strong>{{ readinessStatusLabel(detail, name) }}</strong>
              <small>{{ detail.required ? 'Required' : 'Optional' }}</small>
              <button v-if="setupStepForSection(name, detail)" type="button" class="setup-readiness__action" :aria-label="readinessActionAriaLabel(detail, name)" :title="readinessActionAriaLabel(detail, name)" @click="setStep(setupStepForSection(name, detail)!)">
                {{ readinessActionLabel(detail, name) }}
              </button>
              <em v-if="detail.detail" class="setup-readiness__detail">{{ detail.detail }}</em>
            </div>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" @click="setStep('extras')">Back</button>
          <button class="setup-btn" @click="loadData">Refresh</button>
          <button class="setup-btn setup-btn--primary" @click="router.push('/overview')">Open Overview</button>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'
import SetupProviderPanel from '@/components/setup/SetupProviderPanel.vue'
import SetupRouterPanel from '@/components/setup/SetupRouterPanel.vue'
import SetupChannelsPanel from '@/components/setup/SetupChannelsPanel.vue'
import SetupCapabilitiesPanel from '@/components/setup/SetupCapabilitiesPanel.vue'
import { useSetupCatalog } from '@/composables/setup/useSetupCatalog'

const {
  router,
  STEPS,
  status,
  step,
  providerPanel,
  routerPanel,
  channelsPanel,
  capabilitiesPanel,
  loadData,
  providerSummary,
  routerSummary,
  modelSummary,
  providerProxy,
  hasSetupAction,
  onboardingReasons,
  fixCommands,
  handoffCommands,
  recipeCommands,
  readinessEntries,
  requiredReadiness,
  optionalReadiness,
  setStep,
  stepStatus,
  selectProvider,
  setRouterMode,
  setRouterDefaultTier,
  selectChannelType,
  updateProviderField,
  updateTierField,
  updateChannelField,
  updateCapabilityField,
  onProviderChange,
  onChannelTypeChange,
  onSearchProviderChange,
  onMemoryProviderChange,
  onImageProviderChange,
  readinessTone,
  readinessStatusLabel,
  readinessActionLabel,
  readinessActionAriaLabel,
  setupStepForSection,
  saveProvider,
  saveRouter,
  saveChannel,
  saveSearch,
  saveMemory,
  saveImage,
  copyCommand,
} = useSetupCatalog()
</script>

<style>
.setup {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.setup__head {
  align-items: flex-start;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.setup__head h2 {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  margin: var(--sp-2) 0 0;
}

.setup__kicker {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  margin: 0;
  text-transform: uppercase;
}

.setup__head-aside {
  align-items: flex-end;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.setup__exit {
  align-items: center;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-sm);
  gap: 6px;
  padding: 6px 12px;
}

.setup__exit:hover {
  border-color: var(--accent);
  color: var(--text);
}

.setup__status {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 12px;
  text-transform: uppercase;
}

.setup__status.is-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup__status.is-warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.setup-reasons {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  list-style: none;
  margin: 0;
  padding: 0;
  text-align: right;
}

.setup-reasons li::before {
  color: var(--warn);
  content: "\2022";
  margin-right: 6px;
}

/* Stepper */
.setup-stepper {
  display: flex;
  gap: 2px;
}

.setup-stepper__item {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-3);
}

.setup-stepper__item.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
  color: var(--text);
}

.setup-stepper__num {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 50%;
  display: flex;
  font-size: 12px;
  font-weight: 600;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.setup-stepper__item.is-active .setup-stepper__num {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.setup-stepper__label {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.setup-stepper__state {
  font-size: 10px;
}

.setup-stepper__state.is-ok { color: var(--ok); }
.setup-stepper__state.is-warn { color: var(--warn); }
.setup-stepper__state.is-muted { color: var(--text-dim); }

/* Panel */
.setup-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.setup-panel__head {
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--sp-4);
  padding-bottom: var(--sp-3);
}

.setup-panel__head h3 {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-1);
}

.setup-panel__head p {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
}

/* Form */
.setup-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.setup-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.setup-form label > span:first-child {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.setup-form input,
.setup-form select,
.setup-form textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

.setup-form input:focus,
.setup-form select:focus,
.setup-form textarea:focus {
  border-color: var(--accent);
  outline: none;
}

.setup-form input:disabled,
.setup-form select:disabled {
  opacity: 0.5;
}

.setup-check {
  align-items: center;
  flex-direction: row !important;
  gap: 8px !important;
}

.setup-check input {
  width: auto;
}

/* Provider meta */
.setup-provider-meta {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
}

.setup-provider-meta span {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

.setup-provider-meta__badge {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
}

.setup-provider-meta__badge.is-ready {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup-provider-meta__badge.is-direct {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

.setup-provider-meta__badge.is-neutral {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

/* Provider fields */
.setup-provider-fields {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* Warning */
.setup-warning {
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--border));
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  padding: var(--sp-3);
}

.setup-warning__command {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}

.setup-warning__command code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 4px 8px;
}

/* Actions */
.setup-actions {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}

.setup-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 8px 16px;
}

.setup-btn:hover {
  border-color: var(--accent);
}

.setup-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.setup-btn--primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.setup-btn--primary:hover {
  background: color-mix(in srgb, var(--accent) 90%, #000);
}

/* Router toolbar */
.setup-router-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

/* Tier table */
.setup-tier-table {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  margin-bottom: var(--sp-4);
  overflow: hidden;
}

.setup-tier-table__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 80px 1fr 1fr 120px 60px;
  padding: 8px 12px;
}

.setup-tier-table__row.is-head {
  background: var(--bg-elevated);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-tier-table__row:last-child {
  border-bottom: none;
}

.setup-tier-table__row input,
.setup-tier-table__row select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 12px;
  padding: 4px 8px;
}

/* Channel grid */
.setup-channel-grid {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: 1fr 280px;
  margin-bottom: var(--sp-4);
}

.setup-runtime {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
}

.setup-runtime h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.setup-runtime__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  justify-content: space-between;
  padding: 6px 0;
}

.setup-runtime__row.is-ok strong {
  color: var(--ok);
}

.setup-runtime__row.is-warn strong {
  color: var(--warn);
}

.setup-muted {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

/* Extras */
.setup-extras {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.setup-mini {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
}

.setup-mini__head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.setup-mini__head h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0;
}

.setup-badge {
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
}

.setup-badge.is-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.setup-badge.is-warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.setup-badge.is-muted {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

.setup-mini__advanced-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.setup-mini__env-command {
  margin-bottom: var(--sp-2);
}

/* CLI */
.setup-cli {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.setup-cli__group {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.setup-cli__group-head {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: var(--sp-3) var(--sp-4);
}

.setup-cli__group-head h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0;
}

.setup-cli__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  padding: 8px 12px;
}

.setup-cli__row:last-child {
  border-bottom: none;
}

.setup-cli__label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  min-width: 100px;
  text-transform: uppercase;
}

.setup-cli__row code {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.setup-cli__copy {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 28px;
  justify-content: center;
  width: 28px;
}

.setup-cli__copy:hover {
  background: var(--bg);
  border-color: var(--border);
  color: var(--text);
}

/* Summary */
.setup-summary {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  margin-bottom: var(--sp-4);
}

.setup-summary > div {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-3);
}

.setup-summary span {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-summary strong {
  color: var(--text);
  font-size: var(--fs-sm);
}

/* Readiness */
.setup-readiness {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.setup-readiness__group h4 {
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.setup-readiness__row {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 1fr auto auto auto;
  padding: 8px 0;
}

.setup-readiness__row.is-ok strong { color: var(--ok); }
.setup-readiness__row.is-warn strong { color: var(--warn); }
.setup-readiness__row.is-muted strong { color: var(--text-dim); }

.setup-readiness__row span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.setup-readiness__row strong {
  font-size: var(--fs-sm);
}

.setup-readiness__row small {
  color: var(--text-dim);
  font-size: 10px;
}

.setup-readiness__action {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 8px;
}

.setup-readiness__action:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.setup-readiness__detail {
  color: var(--text-dim);
  font-size: 11px;
  font-style: normal;
  grid-column: 1 / -1;
}

/* Need list */
.setup-need-list {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--fs-sm);
  padding: var(--sp-3);
}

.setup-need-list span {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-need-list ul {
  color: var(--text-muted);
  list-style: none;
  margin: var(--sp-1) 0 0;
  padding: 0;
}

.setup-need-list li::before {
  color: var(--accent);
  content: "\2022";
  margin-right: 6px;
}

/* Responsive */
@media (max-width: 980px) {
  .setup-extras {
    grid-template-columns: 1fr;
  }

  .setup-channel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .setup-stepper {
    flex-wrap: wrap;
  }

  .setup-stepper__item {
    flex: 1 1 100px;
  }

  .setup-tier-table__row {
    grid-template-columns: 60px 1fr 1fr 100px 50px;
  }
}
</style>
