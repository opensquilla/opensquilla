<template>
  <div class="sk-stage">
    <header class="sk-stage__header">
      <div class="sk-stage__title-block">
        <span class="sk-stage__eyebrow">Control &middot; Skills</span>
        <h2 class="sk-stage__title">Skills</h2>
        <p class="sk-stage__subtitle">Composable agent capabilities: bundled OpenSquilla skills plus local managed, personal, project, and workspace packs.</p>
      </div>
      <div class="sk-stage__actions">
        <div class="sk-search-wrap" :style="{ visibility: activeTab === 'installed' ? 'visible' : 'hidden' }">
          <span class="sk-search-icon">
            <Icon name="search" :size="16" />
          </span>
          <input
            v-model="filterText"
            class="sk-search-input"
            type="search"
            placeholder="Filter skills…"
            autocomplete="off"
          />
        </div>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <section class="sk-stats">
      <button
        v-for="tile in statTiles"
        :key="tile.key"
        class="sk-stat"
        :class="[tile.mods, { 'is-active': statusFilter === tile.key }]"
        type="button"
        @click="setStatusFilter(tile.key)"
      >
        <div class="sk-stat__label">{{ tile.label }}</div>
        <div class="sk-stat__value" v-html="tile.value" />
        <div class="sk-stat__hint">{{ tile.hint }}</div>
      </button>
      <button
        v-if="proposals.length > 0"
        class="sk-stat sk-stat--proposals"
        :class="{ 'is-active': statusFilter === 'proposals' }"
        type="button"
        title="Pending meta-skill proposals — synthesised by meta-skill-creator from your usage patterns"
        @click="scrollToProposals"
      >
        <div class="sk-stat__label">Pending Proposals</div>
        <div class="sk-stat__value"><span class="sk-stat__warn">{{ proposals.length }}</span></div>
        <div class="sk-stat__hint">awaiting review</div>
      </button>
    </section>

    <div class="sk-tabs" role="tablist" aria-label="Skill source">
      <button
        class="sk-tab"
        :class="{ 'is-active': activeTab === 'installed' }"
        role="tab"
        @click="activeTab = 'installed'"
      >
        <Icon name="skills" :size="16" />
        <span>Installed</span>
      </button>
      <button
        class="sk-tab"
        :class="{ 'is-active': activeTab === 'registry' }"
        role="tab"
        @click="activeTab = 'registry'"
      >
        <Icon name="download" :size="16" />
        <span>Community</span>
      </button>
    </div>

    <div v-show="activeTab === 'installed'" class="sk-panel">
      <div class="sk-installed">
        <!-- Auto-propose settings -->
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

        <!-- Pending proposals -->
        <details
          v-if="proposals.length"
          ref="proposalsRef"
          class="sk-group sk-group--proposals"
          open
        >
          <summary class="sk-group__head">
            <span class="sk-group__caret">▾</span>
            <span class="sk-group__label">Pending Proposals</span>
            <span class="sk-group__count">{{ proposals.length }}</span>
            <span class="sk-group__meta">meta-skill-creator candidates awaiting your accept/reject decision.</span>
          </summary>
          <div class="sk-proposals-list">
            <div v-for="p in proposals" :key="p.proposal_id" class="sk-proposal-row">
              <div class="sk-proposal-row__head">
                <code class="sk-proposal-row__id">{{ p.proposal_id }}</code>
                <span v-if="p.auto_enable_eligible" class="sk-prop-chip sk-prop-chip--ok">gates ✓</span>
                <span v-else class="sk-prop-chip sk-prop-chip--warn">gates ✗</span>
                <span v-if="typeof p.triggered_by === 'string' && p.triggered_by.startsWith('auto_')" class="sk-prop-chip sk-prop-chip--auto" :title="`Auto-generated by ${p.triggered_by}`">[auto]</span>
                <span v-if="p.auto_enable && p.auto_enable.status" class="sk-prop-chip sk-prop-chip--warn" :title="p.auto_enable.reason || ''">auto-enable: {{ p.auto_enable.status }}</span>
                <span v-if="p.auto_enable && p.auto_enable.validation_profile" class="sk-prop-chip" title="validation profile">{{ p.auto_enable.validation_profile }}</span>
                <span v-if="p.chain_hash" class="sk-prop-hash" title="chain hash">{{ String(p.chain_hash).slice(0, 8) }}</span>
              </div>
              <div class="sk-proposal-row__actions">
                <button class="btn btn--ghost btn--sm" type="button" @click="showProposal(p.proposal_id)">Show</button>
                <button class="btn btn--primary btn--sm" type="button" @click="acceptProposal(p.proposal_id)">Accept</button>
                <button class="btn btn--ghost btn--sm" type="button" @click="rejectProposal(p.proposal_id)">Reject</button>
              </div>
            </div>
          </div>
        </details>

        <!-- Auto-enabled skills -->
        <details v-if="autoEnabledSkills.length" class="sk-group sk-group--proposals" open>
          <summary class="sk-group__head">
            <span class="sk-group__caret">▾</span>
            <span class="sk-group__label">Auto-Enabled Meta-Skills</span>
            <span class="sk-group__count">{{ autoEnabledSkills.length }}</span>
            <span class="sk-group__meta">Promoted by auto-enable. Disable moves the skill back to pending proposals.</span>
          </summary>
          <div class="sk-proposals-list">
            <div v-for="s in autoEnabledSkills" :key="s.name" class="sk-proposal-row">
              <div class="sk-proposal-row__head">
                <code class="sk-proposal-row__id">{{ s.name }}</code>
                <span class="sk-prop-chip sk-prop-chip--ok">enabled</span>
                <span class="sk-prop-chip sk-prop-chip--auto">{{ s.triggered_by || 'unknown' }}</span>
                <span class="sk-prop-chip">risk: {{ s.risk_level || 'unknown' }}</span>
                <span class="sk-prop-chip">{{ s.validation_profile || 'unknown' }}</span>
                <span v-if="Array.isArray(s.skills) && s.skills.length" class="sk-prop-chip" :title="s.skills.join(', ')">{{ s.skills.slice(0, 4).join(', ') }}</span>
                <span v-if="s.proposal_id" class="sk-prop-hash" title="proposal id">{{ s.proposal_id }}</span>
              </div>
              <div class="sk-proposal-row__actions">
                <button class="btn btn--ghost btn--sm" type="button" @click="disableAutoEnabled(s.name)">Disable</button>
              </div>
            </div>
          </div>
        </details>

        <!-- Meta-skills group -->
        <details v-if="metaSkills.length" class="sk-group sk-group--meta" open>
          <summary class="sk-group__head">
            <span class="sk-group__caret">▾</span>
            <span class="sk-group__label">Meta-Skills</span>
            <span class="sk-group__count">{{ metaSkills.length }}</span>
            <span class="sk-group__meta">Composed workflows that drive a DAG of sub-skills.</span>
          </summary>
          <div class="sk-grid">
            <button
              v-for="skill in metaSkills"
              :key="skill.name"
              type="button"
              class="sk-card sk-card--meta"
              :title="skill.name + (skill.description ? ': ' + skill.description : '')"
              @click="openSkillDialog(skill)"
            >
              <div class="sk-card__head">
                <span class="sk-card__dot" :class="dotClass(skill)" :title="dotTitle(skill)" />
                <span v-if="skill.emoji" class="sk-card__emoji">{{ skill.emoji }}</span>
                <span class="sk-card__name" :title="skill.name">{{ skill.name }}</span>
                <span v-if="skill.kind === 'meta_sop'" class="sk-card__kind-badge" title="meta_sop">SOP</span>
                <span v-else-if="isMeta(skill)" class="sk-card__kind-badge" title="meta">META</span>
              </div>
              <p class="sk-card__desc" :title="skill.description || ''">{{ skill.description || '' }}</p>
              <div v-if="skill.sub_skills && skill.sub_skills.length" class="sk-card__sub-row" title="Sub-skills used by this meta-skill">
                <span class="sk-card__sub-label">uses</span>
                <span v-for="n in skill.sub_skills.slice(0, 6)" :key="n" class="sk-card__sub-chip">{{ n }}</span>
                <span v-if="skill.sub_skills.length > 6" class="sk-card__sub-chip sk-card__sub-chip--more">+{{ skill.sub_skills.length - 6 }}</span>
              </div>
            </button>
          </div>
        </details>

        <!-- Layer groups -->
        <details
          v-for="layer in visibleLayerGroups"
          :key="layer.key"
          class="sk-group"
          open
        >
          <summary class="sk-group__head">
            <span class="sk-group__caret">▾</span>
            <span class="sk-group__label">{{ layerLabel(layer.key) }}</span>
            <span class="sk-group__count">{{ layer.skills.length }}</span>
            <span class="sk-group__meta">{{ layerHelp(layer.key) }}</span>
          </summary>
          <div class="sk-grid">
            <button
              v-for="skill in layer.skills"
              :key="skill.name"
              type="button"
              class="sk-card"
              :class="{ 'sk-card--meta': isMeta(skill) }"
              :title="skill.name + (skill.description ? ': ' + skill.description : '')"
              @click="openSkillDialog(skill)"
            >
              <div class="sk-card__head">
                <span class="sk-card__dot" :class="dotClass(skill)" :title="dotTitle(skill)" />
                <span v-if="skill.emoji" class="sk-card__emoji">{{ skill.emoji }}</span>
                <span class="sk-card__name" :title="skill.name">{{ skill.name }}</span>
                <span v-if="skill.kind === 'meta_sop'" class="sk-card__kind-badge" title="meta_sop">SOP</span>
                <span v-else-if="isMeta(skill)" class="sk-card__kind-badge" title="meta">META</span>
              </div>
              <p class="sk-card__desc" :title="skill.description || ''">{{ skill.description || '' }}</p>
              <div v-if="skill.sub_skills && skill.sub_skills.length" class="sk-card__sub-row" title="Sub-skills used by this meta-skill">
                <span class="sk-card__sub-label">uses</span>
                <span v-for="n in skill.sub_skills.slice(0, 6)" :key="n" class="sk-card__sub-chip">{{ n }}</span>
                <span v-if="skill.sub_skills.length > 6" class="sk-card__sub-chip sk-card__sub-chip--more">+{{ skill.sub_skills.length - 6 }}</span>
              </div>
            </button>
          </div>
        </details>

        <!-- Empty state -->
        <div v-if="installedEmpty" class="state">
          <div class="state-icon">
            <Icon name="skills" :size="36" />
          </div>
          <p class="state-text" v-html="emptyMessage" />
        </div>
      </div>
    </div>

    <div v-show="activeTab === 'registry'" class="sk-panel">
      <div class="sk-registry">
        <div class="sk-registry__head">
          <div class="sk-search-wrap sk-search-wrap--lg">
            <span class="sk-search-icon">
              <Icon name="search" :size="16" />
            </span>
            <input
              v-model="registryQuery"
              class="sk-search-input sk-search-input--lg"
              type="search"
              placeholder="Search community skills..."
              autocomplete="off"
              @keydown.enter="searchRegistry"
            />
          </div>
          <button class="btn btn--primary" @click="searchRegistry">Search</button>
        </div>
        <div class="sk-github-install">
          <div class="sk-search-wrap sk-search-wrap--lg">
            <span class="sk-search-icon">
              <Icon name="download" :size="16" />
            </span>
            <input
              v-model="githubUrl"
              class="sk-search-input sk-search-input--lg"
              type="url"
              placeholder="https://github.com/owner/repo/tree/main/path/to/skill"
              autocomplete="off"
              @keydown.enter="installGithub"
            />
          </div>
          <button class="btn btn--primary" @click="installGithub">Install GitHub URL</button>
        </div>
        <div class="sk-registry__results">
          <template v-if="registryLoading">
            <div class="sk-registry__loading">
              <span class="sk-spinner" />
              Searching ClawHub...
            </div>
          </template>
          <template v-else-if="registryResults.length === 0">
            <div class="sk-registry__hint">
              <div class="sk-registry__hint-icon">
                <Icon name="skills" :size="36" />
              </div>
              <p>Search ClawHub skills to browse and install.</p>
              <p class="sk-dim">Paste a GitHub skill URL above for direct install.</p>
            </div>
          </template>
          <template v-else>
            <table class="sk-registry__table">
              <thead>
                <tr><th>Name</th><th>Description</th><th>Source</th><th>Trust</th><th /></tr>
              </thead>
              <tbody>
                <tr v-for="r in registryResults" :key="r.identifier || r.name">
                  <td class="sk-registry__name">{{ r.name }}</td>
                  <td class="sk-registry__desc">{{ (r.description || '').slice(0, 80) }}</td>
                  <td class="sk-mono sk-dim">{{ r.source || '' }}</td>
                  <td>
                    <span class="sk-chip" :class="r.trust_level === 'trusted' ? 'sk-chip--ok' : 'sk-chip--warn'">{{ r.trust_level || 'community' }}</span>
                  </td>
                  <td>
                    <button
                      v-if="r.installed"
                      class="btn btn--sm"
                      disabled
                    >✓ Installed</button>
                    <button
                      v-else
                      class="btn btn--primary btn--sm"
                      :disabled="installingId === (r.identifier || r.name)"
                      @click="installSkill(r.identifier || r.name, r.source || 'clawhub')"
                    >
                      {{ installingId === (r.identifier || r.name) ? 'Installing…' : 'Install' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>
      </div>
    </div>

    <!-- Skill detail dialog -->
    <dialog ref="dialogRef" class="sk-dialog" @click="onDialogBackdropClick">
      <div v-if="selectedSkill" class="sk-detail">
        <header class="sk-detail__header">
          <div class="sk-detail__head-left">
            <span v-if="selectedSkill.emoji" class="sk-detail__emoji">{{ selectedSkill.emoji }}</span>
            <strong class="sk-detail__name">{{ selectedSkill.name }}</strong>
            <div class="sk-detail__chips">
              <span class="sk-chip" :title="layerHelp(selectedSkill.layer)">{{ layerLabel(selectedSkill.layer) }}</span>
              <span class="sk-chip" :class="statusChipClass(selectedSkill)">{{ statusChipText(selectedSkill) }}</span>
            </div>
          </div>
          <button type="button" class="sk-iconbtn" aria-label="Close" @click="closeDialog">
            <Icon name="x" :size="18" />
          </button>
        </header>
        <section class="sk-detail__body">
          <p class="sk-detail__desc">{{ selectedSkill.description || '' }}</p>

          <!-- Triggers -->
          <div v-if="isMeta(selectedSkill) && selectedSkill.triggers && selectedSkill.triggers.length" class="sk-detail__section">
            <div class="sk-detail__section-title">Triggers</div>
            <div class="sk-detail__sub-list">
              <code v-for="t in selectedSkill.triggers" :key="t" class="sk-chip sk-chip--trigger">{{ t }}</code>
            </div>
          </div>

          <!-- Composition -->
          <div v-if="isMeta(selectedSkill) && selectedSkill.sub_skills && selectedSkill.sub_skills.length" class="sk-detail__section">
            <div class="sk-detail__section-title">Composition ({{ selectedSkill.kind === 'meta_sop' ? 'meta_sop' : 'meta' }}, {{ selectedSkill.sub_skills.length }} sub-skills)</div>
            <div class="sk-detail__sub-list">
              <span v-for="n in selectedSkill.sub_skills" :key="n" class="sk-chip sk-chip--sub">{{ n }}</span>
            </div>
          </div>

          <!-- Missing dependencies -->
          <div v-if="selectedSkill.status === 'needs_setup' && (selectedSkill.missing_bins?.length || selectedSkill.missing_env?.length)" class="sk-detail__section">
            <div class="sk-detail__section-title">Missing</div>
            <ul class="sk-detail__missing">
              <li v-for="b in selectedSkill.missing_bins" :key="b"><code>{{ b }}</code> <span class="sk-dim">binary</span></li>
              <li v-for="e in selectedSkill.missing_env" :key="e"><code>{{ e }}</code> <span class="sk-dim">env var</span></li>
            </ul>
          </div>

          <!-- Install options -->
          <div v-if="selectedSkill.missing_bins?.length && selectedSkill.install?.length" class="sk-detail__section">
            <div class="sk-detail__section-title">Install</div>
            <div v-for="i in selectedSkill.install" :key="i.id" class="sk-detail__install-row">
              <span>{{ i.label || `Install via ${i.kind}` }}{{ i.bins?.length ? ` (${i.bins.join(', ')})` : '' }}</span>
              <button
                class="btn btn--primary btn--sm"
                :disabled="installingDepsId === i.id"
                @click="installDeps(selectedSkill.name, i.id)"
              >
                {{ installingDepsId === i.id ? 'Installing…' : `Install via ${i.kind}` }}
              </button>
            </div>
          </div>

          <!-- Homepage -->
          <div v-if="selectedSkill.homepage" class="sk-detail__section">
            <a :href="selectedSkill.homepage" target="_blank" rel="noopener" class="sk-detail__link">Homepage ↗</a>
          </div>
        </section>
        <footer class="sk-detail__foot">
          <small v-if="selectedSkill.file_path" class="sk-dim sk-detail__path">{{ selectedSkill.file_path }}</small>
          <button v-if="selectedSkill.layer === 'managed'" class="btn btn--sm" :disabled="uninstallingName === selectedSkill.name" @click="uninstallSkill(selectedSkill.name)">
            {{ uninstallingName === selectedSkill.name ? 'Removing…' : 'Remove' }}
          </button>
        </footer>
      </div>

      <!-- Proposal detail view -->
      <div v-else-if="selectedProposal" class="sk-detail">
        <header class="sk-detail__header">
          <h3>Proposal {{ selectedProposal.proposal_id }}</h3>
          <button class="btn btn--ghost btn--sm" type="button" @click="closeDialog">Close</button>
        </header>
        <section class="sk-detail__section">
          <h4>Auto-enable Audit</h4>
          <div v-if="selectedProposal.auto_enable_audit && selectedProposal.auto_enable_audit.status" class="sk-audit-grid">
            <div><span>Status</span><strong>{{ selectedProposal.auto_enable_audit.status }}</strong></div>
            <div><span>Risk</span><strong>{{ selectedProposal.auto_enable_audit.risk_level || 'unknown' }} / {{ selectedProposal.auto_enable_audit.max_risk || 'unknown' }}</strong></div>
            <div><span>static-safety profile</span><strong>{{ selectedProposal.auto_enable_audit.validation_profile || 'unknown' }}</strong></div>
            <div><span>Reason</span><strong>{{ selectedProposal.auto_enable_audit.reason || 'none' }}</strong></div>
            <div class="sk-audit-grid__wide">
              <span>Skills</span>
              <p>
                <template v-if="selectedProposal.auto_enable_audit.skills?.length">
                  <code v-for="v in selectedProposal.auto_enable_audit.skills" :key="v">{{ v }}</code>
                </template>
                <span v-else class="sk-dim">none</span>
              </p>
            </div>
            <div class="sk-audit-grid__wide">
              <span>Tools</span>
              <p>
                <template v-if="selectedProposal.auto_enable_audit.tools?.length">
                  <code v-for="v in selectedProposal.auto_enable_audit.tools" :key="v">{{ v }}</code>
                </template>
                <span v-else class="sk-dim">none</span>
              </p>
            </div>
            <div class="sk-audit-grid__wide">
              <span>Static-safety reasons</span>
              <p>
                <template v-if="selectedProposal.auto_enable_audit.reasons?.length">
                  <code v-for="v in selectedProposal.auto_enable_audit.reasons" :key="v">{{ v }}</code>
                </template>
                <span v-else class="sk-dim">none</span>
              </p>
            </div>
          </div>
          <div v-else class="sk-audit-empty">No auto-enable decision recorded.</div>
        </section>
        <section class="sk-detail__section">
          <h4>SKILL.md</h4>
          <pre class="sk-detail__pre">{{ selectedProposal.skill_md || '' }}</pre>
        </section>
        <section class="sk-detail__section">
          <h4>Gates</h4>
          <pre class="sk-detail__pre">{{ JSON.stringify(selectedProposal.gates || {}, null, 2) }}</pre>
        </section>
      </div>
    </dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SkillInstall {
  id: string
  kind: string
  label?: string
  bins?: string[]
}

interface Skill {
  name: string
  description?: string
  emoji?: string
  status?: string
  status_detail?: string
  eligible?: boolean
  layer?: string
  kind?: string
  sub_skills?: string[]
  triggers?: string[]
  missing_bins?: string[]
  missing_env?: string[]
  install?: SkillInstall[]
  homepage?: string
  file_path?: string
}

interface Proposal {
  proposal_id: string
  auto_enable_eligible?: boolean
  triggered_by?: string
  auto_enable?: {
    status?: string
    reason?: string
    validation_profile?: string
  }
  chain_hash?: string
  skill_md?: string
  gates?: Record<string, unknown>
  auto_enable_audit?: {
    status?: string
    risk_level?: string
    max_risk?: string
    validation_profile?: string
    reason?: string
    skills?: string[]
    tools?: string[]
    reasons?: string[]
  }
}

interface AutoEnabledSkill {
  name: string
  risk_level?: string
  triggered_by?: string
  validation_profile?: string
  skills?: string[]
  proposal_id?: string
}

interface ProposalsSettings {
  available: boolean
  enabled: boolean
  on_dream_complete: boolean
  auto_enable: boolean
  auto_enable_max_risk: string
  cron?: string
}

interface SkillsListData {
  skills?: Skill[]
}

interface ProposalsListData {
  proposals?: Proposal[]
}

interface AutoEnabledListData {
  skills?: AutoEnabledSkill[]
}

interface ProposalSettingsData {
  settings?: ProposalsSettings
}

interface ProposalShowData {
  status?: string
  reason?: string
  skill_md?: string
  gates?: Record<string, unknown>
  auto_enable_audit?: Proposal['auto_enable_audit']
}

interface ProposalActionData {
  status?: string
  reason?: string
}

interface RegistryResult {
  name: string
  description?: string
  identifier?: string
  source?: string
  trust_level?: string
  installed?: boolean
}

interface RegistrySearchData {
  results?: RegistryResult[]
}

interface InstallResult {
  success: boolean
  message?: string
  missing_still?: {
    bins?: string[]
    env?: string[]
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LAYER_ORDER = ['workspace', 'bundled', 'managed', 'personal', 'project', 'extra']
const LAYER_LABEL: Record<string, string> = {
  workspace: 'Workspace',
  bundled: 'Bundled',
  managed: 'Managed',
  personal: 'Personal',
  project: 'Project',
  extra: 'Extra',
}
const LAYER_HELP: Record<string, string> = {
  workspace: 'Workspace skills are local to the active workspace.',
  bundled: 'Bundled skills ship with OpenSquilla.',
  managed: 'Managed skills are locally installed into OpenSquilla state.',
  personal: 'Personal skills are local user installs, not bundled.',
  project: 'Project skills are local to the current project.',
  extra: 'Extra skills come from configured local directories.',
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const rpc = useRpcStore()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const allSkills = ref<Skill[]>([])
const proposals = ref<Proposal[]>([])
const autoEnabledSkills = ref<AutoEnabledSkill[]>([])
const proposalsSettings = ref<ProposalsSettings>({
  available: false,
  enabled: false,
  on_dream_complete: false,
  auto_enable: false,
  auto_enable_max_risk: 'low',
})
const filterText = ref('')
const statusFilter = ref('all')
const activeTab = ref('installed')
const registryQuery = ref('')
const githubUrl = ref('')
const registryResults = ref<RegistryResult[]>([])
const registryLoading = ref(false)
const installingId = ref<string | null>(null)
const installingDepsId = ref<string | null>(null)
const uninstallingName = ref<string | null>(null)
const selectedSkill = ref<Skill | null>(null)
const selectedProposal = ref<Proposal | null>(null)
const dialogRef = ref<HTMLDialogElement | null>(null)
const proposalsRef = ref<HTMLElement | null>(null)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const proposalsSettingsOn = computed(() => {
  const s = proposalsSettings.value
  return s.enabled || s.on_dream_complete || s.auto_enable
})

const filteredSkills = computed(() => {
  let skills = allSkills.value
  if (filterText.value) {
    const ft = filterText.value.toLowerCase()
    skills = skills.filter(s =>
      (s.name || '').toLowerCase().includes(ft) ||
      (s.description || '').toLowerCase().includes(ft) ||
      (s.triggers || []).some(t => t.toLowerCase().includes(ft))
    )
  }
  if (statusFilter.value === 'ready') {
    skills = skills.filter(s => s.status === 'ready')
  } else if (statusFilter.value === 'needs-setup') {
    skills = skills.filter(s => s.status === 'needs_setup')
  } else if (statusFilter.value === 'not-declared') {
    skills = skills.filter(s => s.status === 'not_declared')
  }
  return skills
})

const metaSkills = computed(() => {
  return sortByReady(filteredSkills.value.filter(s => isMeta(s)))
})

const layerGroups = computed(() => {
  const groups: Record<string, Skill[]> = {}
  filteredSkills.value.forEach(s => {
    if (isMeta(s)) return
    const l = s.layer || 'extra'
    if (!groups[l]) groups[l] = []
    groups[l].push(s)
  })
  return groups
})

const visibleLayerGroups = computed(() => {
  return LAYER_ORDER
    .map(key => ({ key, skills: sortByReady(layerGroups.value[key] || []) }))
    .filter(g => g.skills.length > 0)
})

const installedEmpty = computed(() => {
  return filteredSkills.value.length === 0 && !proposals.value.length && !autoEnabledSkills.value.length && !proposalsSettings.value.available
})

const emptyMessage = computed(() => {
  if (filterText.value) {
    return `No skills match <strong>${esc(filterText.value)}</strong>.`
  }
  if (statusFilter.value === 'ready') {
    return 'No skills are ready. Install dependencies to enable them.'
  }
  if (statusFilter.value === 'needs-setup') {
    return 'No skills currently need setup.'
  }
  if (statusFilter.value === 'not-declared') {
    return 'No skills without declared dependencies.'
  }
  return 'No skills installed.'
})

const statTiles = computed(() => {
  const total = allSkills.value.length
  const ready = allSkills.value.filter(s => s.status === 'ready').length
  const needs = allSkills.value.filter(s => s.status === 'needs_setup').length
  const notDeclared = allSkills.value.filter(s => s.status === 'not_declared').length
  const layers = new Set(allSkills.value.map(s => s.layer).filter(Boolean))

  return [
    { key: 'all', label: 'All skills', value: String(total), hint: `${layers.size} layer${layers.size === 1 ? '' : 's'}`, mods: 'sk-stat--accent' },
    { key: 'ready', label: 'Ready', value: `<span class="sk-stat__ok">${ready}</span>`, hint: ready ? 'install-ready' : 'none ready', mods: '' },
    { key: 'needs-setup', label: 'Needs setup', value: `<span class="sk-stat__warn">${needs}</span>`, hint: needs ? 'awaiting deps' : 'all set', mods: '' },
    { key: 'not-declared', label: 'Not declared', value: String(notDeclared), hint: 'no manifest', mods: '' },
  ]
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function setStatusFilter(key: string) {
  statusFilter.value = key
}

function scrollToProposals() {
  if (proposalsRef.value) {
    proposalsRef.value.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function isMeta(skill: Skill): boolean {
  return skill.kind === 'meta' || skill.kind === 'meta_sop'
}

function rank(skill: Skill): number {
  if (skill.status === 'ready') return 0
  if (skill.status === 'not_declared') return 1
  return 2
}

function sortByReady(list: Skill[]): Skill[] {
  return [...list].sort((a, b) => {
    const ra = rank(a)
    const rb = rank(b)
    if (ra !== rb) return ra - rb
    return (a.name || '').localeCompare(b.name || '')
  })
}

function dotClass(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'is-ready'
  if (status === 'needs_setup') return 'is-needs'
  return 'is-unverified'
}

function dotTitle(skill: Skill): string {
  return skill.status_detail || (skill.eligible ? 'Ready' : 'Needs setup')
}

function statusChipClass(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return 'sk-chip--ok'
  if (status === 'not_declared') return 'sk-chip--unverified'
  return 'sk-chip--warn'
}

function statusChipText(skill: Skill): string {
  const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup')
  if (status === 'ready') return '✓ ready'
  if (status === 'not_declared') return 'no deps declared'
  return 'needs deps'
}

function layerLabel(layer: string | undefined): string {
  return LAYER_LABEL[layer || ''] || layer || 'Unknown'
}

function layerHelp(layer: string | undefined): string {
  return LAYER_HELP[layer || ''] || 'Configured local skill directory.'
}

function openSkillDialog(skill: Skill) {
  selectedSkill.value = skill
  selectedProposal.value = null
  if (dialogRef.value) {
    if (dialogRef.value.open) dialogRef.value.close()
    dialogRef.value.showModal()
  }
}

function closeDialog() {
  if (dialogRef.value) {
    dialogRef.value.close()
  }
  selectedSkill.value = null
  selectedProposal.value = null
}

function onDialogBackdropClick(e: MouseEvent) {
  if (e.target === dialogRef.value) {
    closeDialog()
  }
}

async function loadData() {
  try {
    await rpc.waitForConnection()
  } catch {
    return
  }
  try {
    const data = await rpc.call<SkillsListData>('skills.list')
    allSkills.value = data.skills || []
    await loadProposals()
  } catch (err) {
    console.warn('Failed to load skills:', (err as Error).message)
  }
}

async function loadProposals() {
  try {
    const data = await rpc.call<ProposalsListData>('exec.proposals.list')
    proposals.value = data.proposals || []
  } catch {
    proposals.value = []
  }
  try {
    const data = await rpc.call<AutoEnabledListData>('exec.proposals.auto_enabled.list')
    autoEnabledSkills.value = data.skills || []
  } catch {
    autoEnabledSkills.value = []
  }
  try {
    const data = await rpc.call<ProposalSettingsData>('exec.proposals.settings.get')
    proposalsSettings.value = data.settings || proposalsSettings.value
  } catch {
    proposalsSettings.value = {
      available: false,
      enabled: false,
      on_dream_complete: false,
      auto_enable: false,
      auto_enable_max_risk: 'low',
    }
  }
}

async function toggleAutoPropose(key: string, value: boolean) {
  try {
    const out = await rpc.call<ProposalSettingsData>('exec.proposals.settings.set', { [key]: value })
    if (out && (out as unknown as { status?: string }).status === 'error') {
      console.warn('Settings update failed:', (out as unknown as { reason?: string }).reason || 'unknown')
      return
    }
    proposalsSettings.value = out.settings || proposalsSettings.value
    await loadData()
  } catch (err) {
    console.warn('Settings update failed:', (err as Error).message)
  }
}

async function setAutoEnableRisk(value: string) {
  try {
    const out = await rpc.call<ProposalSettingsData>('exec.proposals.settings.set', { auto_enable_max_risk: value })
    if (out && (out as unknown as { status?: string }).status === 'error') {
      console.warn('Settings update failed:', (out as unknown as { reason?: string }).reason || 'unknown')
      return
    }
    proposalsSettings.value = out.settings || proposalsSettings.value
  } catch (err) {
    console.warn('Settings update failed:', (err as Error).message)
  }
}

async function showProposal(proposalId: string) {
  try {
    const data = await rpc.call<ProposalShowData>('exec.proposals.show', { proposal_id: proposalId })
    if (data.status !== 'ok') {
      console.warn('Show failed:', data.reason || 'unknown')
      return
    }
    selectedProposal.value = { proposal_id: proposalId, ...data }
    selectedSkill.value = null
    if (dialogRef.value) {
      if (dialogRef.value.open) dialogRef.value.close()
      dialogRef.value.showModal()
    }
  } catch (err) {
    console.warn('Show failed:', (err as Error).message)
  }
}

async function acceptProposal(proposalId: string) {
  try {
    let data = await rpc.call<ProposalActionData>('exec.proposals.accept', { proposal_id: proposalId })
    if (data.status === 'refused' && data.reason && data.reason.indexOf('gates') !== -1) {
      if (!confirm(`Proposal ${proposalId} did not pass all gates.\n\n${data.reason}\n\nAccept anyway (force)?`)) return
      data = await rpc.call<ProposalActionData>('exec.proposals.accept', { proposal_id: proposalId, force: true })
    }
    if (data.status !== 'ok') {
      console.warn('Accept failed:', data.reason || data.status)
      return
    }
    await loadData()
  } catch (err) {
    console.warn('Accept failed:', (err as Error).message)
  }
}

async function rejectProposal(proposalId: string) {
  if (!confirm(`Reject and delete proposal ${proposalId}? This cannot be undone.`)) return
  try {
    const data = await rpc.call<ProposalActionData>('exec.proposals.reject', { proposal_id: proposalId })
    if (data.status !== 'ok') {
      console.warn('Reject failed:', data.reason || data.status)
      return
    }
    await loadData()
  } catch (err) {
    console.warn('Reject failed:', (err as Error).message)
  }
}

async function disableAutoEnabled(name: string) {
  if (!confirm(`Disable auto-enabled skill ${name} and move it back to pending proposals?`)) return
  try {
    const data = await rpc.call<ProposalActionData>('exec.proposals.auto_enabled.disable', { name })
    if (data.status !== 'ok') {
      console.warn('Disable failed:', data.reason || data.status)
      return
    }
    await loadData()
  } catch (err) {
    console.warn('Disable failed:', (err as Error).message)
  }
}

async function installDeps(name: string, installId: string) {
  if (!name || !installId) return
  installingDepsId.value = installId
  try {
    const res = await rpc.call<InstallResult>('skills.deps.install', { name, install_id: installId })
    if (res.success) {
      console.warn(res.message || 'Installed')
      const still = res.missing_still || {}
      const stillMissing = (still.bins || []).length + (still.env || []).length
      if (stillMissing === 0) {
        setTimeout(() => {
          closeDialog()
        }, 600)
      }
      await loadData()
    } else {
      console.warn(res.message || 'Install failed')
    }
  } catch (err) {
    console.warn((err as Error).message)
  } finally {
    installingDepsId.value = null
  }
}

async function searchRegistry() {
  if (!registryQuery.value.trim()) return
  registryLoading.value = true
  registryResults.value = []
  try {
    const data = await rpc.call<RegistrySearchData>('skills.search', { query: registryQuery.value.trim(), limit: 20 })
    registryResults.value = data.results || []
  } catch (err) {
    console.warn('Search failed:', (err as Error).message)
  } finally {
    registryLoading.value = false
  }
}

function installGithub() {
  const url = githubUrl.value.trim()
  if (!url) return
  installSkill(url, 'github')
}

async function installSkill(identifier: string, source: string) {
  installingId.value = identifier
  try {
    const res = await rpc.call<InstallResult>('skills.install', { identifier, source })
    if (res.success) {
      await loadData()
    } else {
      console.warn(res.message || 'Install failed')
    }
  } catch (err) {
    console.warn((err as Error).message)
  } finally {
    installingId.value = null
  }
}

async function uninstallSkill(name: string) {
  uninstallingName.value = name
  try {
    const res = await rpc.call<InstallResult>('skills.uninstall', { name })
    if (res.success) {
      await loadData()
      closeDialog()
    } else {
      console.warn(res.message || 'Uninstall failed')
    }
  } catch (err) {
    console.warn((err as Error).message)
  } finally {
    uninstallingName.value = null
  }
}

function esc(s: string): string {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
</script>

<style scoped>
.sk-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
  max-width: none;
  position: relative;
}

.sk-stage__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding-top: var(--sp-3);
}
.sk-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.sk-stage__eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.sk-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  position: relative;
  margin: 0;
}
.sk-stage__title::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 36px;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
}
.sk-stage__subtitle {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  margin: var(--sp-3) 0 0;
  max-width: 60ch;
}
.sk-stage__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

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
.sk-search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}
.sk-search-wrap--lg .sk-search-input {
  min-width: 320px;
}

/* Stats */
.sk-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-3);
}
.sk-stat {
  position: relative;
  text-align: left;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition), transform 200ms ease;
  animation: sk-fade-up 360ms ease both;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.sk-stat.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.sk-stat:hover {
  border-color: var(--border-focus);
  box-shadow: 0 8px 24px -16px rgba(0, 0, 0, 0.4);
  transform: translateY(-1px);
}
.sk-stat--accent::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent);
}
.sk-stat--proposals::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--warn);
}
.sk-stat__label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.sk-stat__value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.18;
  font-variant-numeric: tabular-nums;
}
.sk-stat__ok {
  color: var(--ok);
}
.sk-stat__warn {
  color: var(--warn);
}
.sk-stat__hint {
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
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
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}

/* Cards */
.sk-card {
  position: relative;
  text-align: left;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: border-color var(--transition), box-shadow var(--transition), transform 150ms ease;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sk-card:hover {
  border-color: var(--border-focus);
  box-shadow: 0 4px 12px -8px rgba(0, 0, 0, 0.3);
  transform: translateY(-1px);
}
.sk-card--meta {
  border-color: color-mix(in srgb, var(--accent) 25%, var(--border));
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
.sk-registry__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}
.sk-registry__table th {
  text-align: left;
  padding: 8px 10px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
}
.sk-registry__table td {
  padding: 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  vertical-align: middle;
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
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  color: var(--text);
  max-width: 640px;
  width: 90vw;
  max-height: 85vh;
  overflow: hidden;
  padding: 0;
}
.sk-dialog::backdrop {
  background: rgba(0, 0, 0, 0.5);
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
.state-text :deep(strong) {
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
  .sk-registry__table {
    font-size: var(--fs-xs);
  }
  .sk-registry__table th,
  .sk-registry__table td {
    padding: 6px;
  }
}
</style>
