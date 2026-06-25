<template>
  <div class="sk-stage control-stage control-stage--spacious">
    <header class="sk-stage__header control-stage__header">
      <div class="sk-stage__title-block control-stage__title-block">
        <h2 class="sk-stage__title control-stage__title">Skills</h2>
        <p class="sk-stage__subtitle control-stage__subtitle">Composable agent capabilities: bundled OpenSquilla skills plus local managed, personal, project, and workspace packs.</p>
      </div>
      <div class="sk-stage__actions control-stage__actions">
        <div class="sk-search-wrap" :style="{ visibility: activeTab === 'installed' ? 'visible' : 'hidden' }">
          <span class="sk-search-icon">
            <Icon name="search" :size="16" />
          </span>
          <input
            v-model="filterText"
            class="sk-search-input"
            type="search"
            placeholder="Filter skills..."
            autocomplete="off"
          />
        </div>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <SkillsStats
      :tiles="statTiles"
      :active-key="statusFilter"
      :proposal-count="proposals.length"
      @select="setStatusFilter"
      @show-proposals="scrollToProposals"
    />

    <div class="sk-tabs" role="tablist" aria-label="Skill source">
      <button
        id="sk-tab-installed"
        class="sk-tab"
        :class="{ 'is-active': activeTab === 'installed' }"
        type="button"
        role="tab"
        :aria-selected="activeTab === 'installed'"
        aria-controls="sk-panel-installed"
        @click="activeTab = 'installed'"
      >
        <Icon name="skills" :size="16" />
        <span>Installed</span>
      </button>
      <button
        id="sk-tab-registry"
        class="sk-tab"
        :class="{ 'is-active': activeTab === 'registry' }"
        type="button"
        role="tab"
        :aria-selected="activeTab === 'registry'"
        aria-controls="sk-panel-registry"
        @click="activeTab = 'registry'"
      >
        <Icon name="download" :size="16" />
        <span>Community</span>
      </button>
    </div>

    <div v-show="activeTab === 'installed'" class="sk-panel" role="tabpanel" id="sk-panel-installed" aria-labelledby="sk-tab-installed">
      <div class="sk-installed">
        <details
          v-if="proposalsSettings.available"
          class="sk-group sk-group--ap-settings"
          :open="proposalsSettingsOn"
        >
          <summary class="sk-group__head">
            <span class="sk-group__caret">▾</span>
            <span class="sk-group__label">Auto-Propose Settings</span>
            <span class="sk-group__count">{{ proposalsSettingsOn ? 'on' : 'off' }}</span>
            <span class="sk-group__meta">Unattended synthesis of new meta-skills from your usage patterns.</span>
          </summary>
          <div class="sk-ap-settings">
            <label class="sk-ap-toggle">
              <input
                type="checkbox"
                :checked="proposalsSettings.enabled"
                @change="toggleAutoPropose('enabled', ($event.target as HTMLInputElement).checked)"
              />
              <span class="sk-ap-toggle__label">Scheduled (cron)</span>
              <span class="sk-ap-toggle__hint">Run on <code>{{ proposalsSettings.cron || '0 5 * * *' }}</code>. Drives the meta-skill-creator DAG against your top co-occurrence patterns.</span>
            </label>
            <label class="sk-ap-toggle">
              <input
                type="checkbox"
                :checked="proposalsSettings.on_dream_complete"
                @change="toggleAutoPropose('on_dream_complete', ($event.target as HTMLInputElement).checked)"
              />
              <span class="sk-ap-toggle__label">After memory consolidation (dream)</span>
              <span class="sk-ap-toggle__hint">Piggyback on the memory-dream completion. Independent of the cron toggle.</span>
            </label>
            <label class="sk-ap-toggle">
              <input
                type="checkbox"
                :checked="proposalsSettings.auto_enable"
                @change="toggleAutoPropose('auto_enable', ($event.target as HTMLInputElement).checked)"
              />
              <span class="sk-ap-toggle__label">Auto-enable gated proposals</span>
              <span class="sk-ap-toggle__hint">Promote only proposals that pass all gates and stay within the configured <code>{{ proposalsSettings.auto_enable_max_risk || 'low' }}</code> risk ceiling.</span>
            </label>
            <label class="sk-ap-toggle">
              <span class="sk-ap-toggle__label">Auto-enable risk ceiling</span>
              <select
                class="sk-ap-select"
                :value="proposalsSettings.auto_enable_max_risk || 'low'"
                @change="setAutoEnableRisk(($event.target as HTMLSelectElement).value)"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <span class="sk-ap-toggle__hint">Low is the default. Higher ceilings still run the static safety preflight and keep audit metadata.</span>
            </label>
          </div>
        </details>

        <PendingSkillProposals
          ref="proposalsPanelRef"
          :proposals="proposals"
          @show="openProposalDialog"
          @accept="acceptProposal"
          @reject="rejectProposal"
        />
        <AutoEnabledSkills :skills="autoEnabledSkills" @disable="disableAutoEnabled" />
        <SkillGroup
          title="Meta-Skills"
          description="Composed workflows that drive a DAG of sub-skills."
          :skills="metaSkills"
          group-class="sk-group--meta"
          meta
          @open="openSkillDialog"
        />
        <SkillGroup
          v-for="layer in visibleLayerGroups"
          :key="layer.key"
          :title="skillLayerLabel(layer.key)"
          :description="skillLayerHelp(layer.key)"
          :skills="layer.skills"
          @open="openSkillDialog"
        />

        <div v-if="installedEmpty" class="state">
          <div class="state-icon">
            <Icon name="skills" :size="36" />
          </div>
          <p class="state-text">
            <template v-if="filterText">No skills match <strong>{{ filterText }}</strong>.</template>
            <template v-else>{{ emptyMessage }}</template>
          </p>
        </div>
      </div>
    </div>

    <div v-show="activeTab === 'registry'" class="sk-panel" role="tabpanel" id="sk-panel-registry" aria-labelledby="sk-tab-registry">
      <SkillsRegistryPanel
        v-model:registry-query="registryQuery"
        v-model:github-url="githubUrl"
        :results="registryResults"
        :loading="registryLoading"
        :installing-id="installingId"
        @search="searchRegistry"
        @install-github="installGithub"
        @install="installSkill"
      />
    </div>

    <SkillDetailDialog
      :skill="selectedSkill"
      :proposal="selectedProposal"
      :installing-deps-id="installingDepsId"
      :uninstalling-name="uninstallingName"
      @close="closeDialog"
      @install-deps="installDepsAndMaybeClose"
      @uninstall="uninstallSkillAndClose"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import AutoEnabledSkills from '@/components/skills/AutoEnabledSkills.vue'
import PendingSkillProposals from '@/components/skills/PendingSkillProposals.vue'
import SkillDetailDialog from '@/components/skills/SkillDetailDialog.vue'
import SkillGroup from '@/components/skills/SkillGroup.vue'
import SkillsRegistryPanel from '@/components/skills/SkillsRegistryPanel.vue'
import SkillsStats from '@/components/skills/SkillsStats.vue'
import { useSkillProposals } from '@/composables/skills/useSkillProposals'
import { useSkillRegistry } from '@/composables/skills/useSkillRegistry'
import { skillLayerHelp, skillLayerLabel, useSkillsCatalog } from '@/composables/skills/useSkillsCatalog'
import { useRpcStore } from '@/stores/rpc'
import type { Proposal, Skill } from '@/types/skills'

const rpc = useRpcStore()
const activeTab = ref('installed')
const selectedSkill = ref<Skill | null>(null)
const selectedProposal = ref<Proposal | null>(null)
const proposalsPanelRef = ref<InstanceType<typeof PendingSkillProposals> | null>(null)

let loadData: () => Promise<void>

const proposalsModel = useSkillProposals(rpc, async () => loadData())
const {
  proposals,
  autoEnabledSkills,
  proposalsSettings,
  proposalsSettingsOn,
  loadProposals,
  toggleAutoPropose,
  setAutoEnableRisk,
  showProposal,
  acceptProposal,
  rejectProposal,
  disableAutoEnabled,
} = proposalsModel

const catalog = useSkillsCatalog(rpc, {
  proposals,
  autoEnabledSkills,
  proposalsSettings,
  loadProposals,
})

const {
  filterText,
  statusFilter,
  metaSkills,
  visibleLayerGroups,
  installedEmpty,
  emptyMessage,
  statTiles,
  setStatusFilter,
} = catalog

loadData = catalog.loadData

const registry = useSkillRegistry(rpc, loadData)
const {
  registryQuery,
  githubUrl,
  registryResults,
  registryLoading,
  installingId,
  installingDepsId,
  uninstallingName,
  searchRegistry,
  installGithub,
  installSkill,
  installDeps,
  uninstallSkill,
} = registry

onMounted(() => {
  void loadData()
})

function scrollToProposals() {
  proposalsPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openSkillDialog(skill: Skill) {
  selectedSkill.value = skill
  selectedProposal.value = null
}

async function openProposalDialog(proposalId: string) {
  const proposal = await showProposal(proposalId)
  if (!proposal) return
  selectedProposal.value = proposal
  selectedSkill.value = null
}

function closeDialog() {
  selectedSkill.value = null
  selectedProposal.value = null
}

async function installDepsAndMaybeClose(name: string, installId: string) {
  const done = await installDeps(name, installId)
  if (done) {
    setTimeout(() => {
      closeDialog()
    }, 600)
  }
}

async function uninstallSkillAndClose(name: string) {
  const removed = await uninstallSkill(name)
  if (removed) closeDialog()
}
</script>

<style>
/* Search */
.sk-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.sk-search-icon {
  position: absolute;
  left: 10px;
  color: var(--text-dim);
  pointer-events: none;
  display: inline-flex;
  align-items: center;
}
.sk-search-input {
  padding: 8px 12px 8px 34px;
  font-size: var(--fs-sm);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  outline: none;
  min-width: 200px;
  transition: border-color var(--transition), box-shadow var(--transition);
}
/* base.css resets text inputs via input:not([type="radio"]):not([type="checkbox"])
   — specificity (0,2,1), which outranks the .sk-search-input class and drops the
   leading-icon clearance (and elevated fill), letting the search/download icon
   overlap the placeholder. Re-assert just those two properties at matching reach;
   the :not() mirror clears the base reset without touching the --lg width rule. */
.sk-search-input:not([type="radio"]):not([type="checkbox"]) {
  padding: 8px 12px 8px 34px;
  background: var(--bg-elevated);
}
.sk-search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}
.sk-search-wrap--lg .sk-search-input {
  min-width: 320px;
}

/* Tabs */
.sk-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
}
.sk-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--transition), border-color var(--transition);
}
.sk-tab.is-active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.sk-tab:hover:not(.is-active) {
  color: var(--text);
}

/* Panels */
.sk-panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* Groups */
.sk-group {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.sk-group--meta {
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
}
.sk-group--proposals {
  border-color: color-mix(in srgb, var(--warn) 30%, var(--border));
}
.sk-group--ap-settings {
  border-color: color-mix(in srgb, var(--accent) 20%, var(--border));
}
.sk-group__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  user-select: none;
  background: var(--bg-elevated);
  font-size: var(--fs-sm);
}
.sk-group__caret {
  color: var(--text-dim);
  font-size: 10px;
  transition: transform 200ms ease;
}
.sk-group[open] .sk-group__caret {
  transform: rotate(180deg);
}
.sk-group__label {
  font-weight: 600;
  color: var(--text);
}
.sk-group__count {
  font-size: var(--fs-xs);
  color: var(--text-dim);
  background: var(--bg);
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}
.sk-group__meta {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  margin-left: auto;
}

/* Grid */
.sk-grid {
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}
.sk-card__head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.sk-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.sk-card__dot.is-ready {
  background: var(--ok);
}
.sk-card__dot.is-needs {
  background: var(--warn);
}
.sk-card__dot.is-unverified {
  background: var(--text-dim);
}
.sk-card__emoji {
  font-size: 14px;
  line-height: 1;
}
.sk-card__name {
  font-weight: 600;
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.sk-card__kind-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  flex-shrink: 0;
}
.sk-card__desc {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
}
.sk-card__sub-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 2px;
}
.sk-card__sub-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-right: 2px;
}
.sk-card__sub-chip {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
}
.sk-card__sub-chip--more {
  background: transparent;
  border-style: dashed;
}

/* Proposals list */
.sk-proposals-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}
.sk-proposal-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  flex-wrap: wrap;
}
.sk-proposal-row__head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.sk-proposal-row__id {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--text);
  background: var(--bg-elevated);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}
.sk-proposal-row__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.sk-prop-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.sk-prop-chip--ok {
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}
.sk-prop-chip--warn {
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}
.sk-prop-chip--auto {
  border-style: dashed;
  color: var(--accent);
}
.sk-prop-hash {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
}

/* Auto-propose settings */
.sk-ap-settings {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}
.sk-ap-toggle {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  flex-wrap: wrap;
  cursor: pointer;
}
.sk-ap-toggle input[type="checkbox"] {
  margin-top: 2px;
  accent-color: var(--accent);
}
.sk-ap-toggle__label {
  font-weight: 600;
  font-size: var(--fs-sm);
  color: var(--text);
}
.sk-ap-toggle__hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  width: 100%;
  margin-left: 24px;
}
.sk-ap-select {
  padding: 4px 8px;
  font-size: var(--fs-sm);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  outline: none;
}
.sk-ap-select:focus {
  border-color: var(--accent);
}

/* Registry */
.sk-registry {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.sk-registry__head,
.sk-github-install {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.sk-registry__results {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  min-height: 120px;
}
.sk-registry__hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-5);
  color: var(--text-muted);
  text-align: center;
}
.sk-registry__hint-icon {
  color: var(--text-dim);
}
.sk-registry__loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-5);
  color: var(--text-muted);
}
.sk-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: sk-spin 0.8s linear infinite;
}
.sk-registry__name {
  font-weight: 600;
}
.sk-registry__desc {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  max-width: 300px;
}

/* Dialog */
.sk-dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  color: var(--text);
  max-width: 640px;
  width: 90vw;
  max-height: 85vh;
  overflow: hidden;
  padding: 0;
  margin: 0;
}
.sk-dialog::backdrop {
  background: var(--scrim);
}
.sk-detail {
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}
.sk-detail__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-bottom: 1px solid var(--border);
}
.sk-detail__head-left {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  min-width: 0;
}
.sk-detail__emoji {
  font-size: 18px;
  line-height: 1;
}
.sk-detail__name {
  font-size: var(--fs-lg);
  font-weight: 600;
}
.sk-detail__chips {
  display: flex;
  gap: 6px;
}
.sk-detail__body {
  padding: var(--sp-4);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.sk-detail__desc {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.sk-detail__section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.sk-detail__section-title {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.sk-detail__sub-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.sk-detail__missing {
  margin: 0;
  padding-left: var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.sk-detail__missing li {
  margin-bottom: 4px;
}
.sk-detail__install-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}
.sk-detail__link {
  color: var(--accent);
  text-decoration: none;
  font-size: var(--fs-sm);
}
.sk-detail__link:hover {
  text-decoration: underline;
}
.sk-detail__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
.sk-detail__path {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.sk-iconbtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--transition), border-color var(--transition);
}
.sk-iconbtn:hover {
  color: var(--text);
  border-color: var(--border-focus);
}

/* Chips */
.sk-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 10.5px;
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-muted);
}
.sk-chip--ok {
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}
.sk-chip--warn {
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}
.sk-chip--unverified {
  border-color: color-mix(in srgb, var(--text-dim) 40%, var(--border));
  color: var(--text-dim);
}
.sk-chip--sub {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  color: var(--accent);
}
.sk-chip--trigger {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg);
}

/* Audit grid */
.sk-audit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: var(--fs-sm);
}
.sk-audit-grid__wide {
  grid-column: 1 / -1;
}
.sk-audit-grid span {
  color: var(--text-dim);
  font-size: var(--fs-xs);
}
.sk-audit-grid strong {
  color: var(--text);
  font-weight: 600;
}
.sk-audit-grid code {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-elevated);
  padding: 1px 4px;
  border-radius: var(--radius-sm);
  margin-right: 4px;
}
.sk-audit-empty {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  padding: var(--sp-2);
}

/* Preformatted */
.sk-detail__pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
  font-family: var(--font-mono);
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  color: var(--text-muted);
}

/* Empty state */
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-5);
  color: var(--text-muted);
}
.state-icon {
  color: var(--text-dim);
}
.state-text {
  margin: 0;
  font-size: var(--fs-sm);
}
.state-text strong {
  color: var(--text);
}

/* Utility */
.sk-dim {
  color: var(--text-dim);
}
.sk-mono {
  font-family: var(--font-mono);
}

/* Animations */
@keyframes sk-fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes sk-spin {
  to { transform: rotate(360deg); }
}

/* Responsive */
@media (max-width: 720px) {
  .sk-stage__header {
    flex-direction: column;
    align-items: stretch;
  }
  .sk-stage__actions {
    width: 100%;
  }
  .sk-search-input,
  .sk-search-wrap--lg .sk-search-input {
    min-width: 0;
    width: 100%;
  }
  .sk-grid {
    grid-template-columns: 1fr;
  }
  .sk-proposal-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
