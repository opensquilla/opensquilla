<template>
  <div class="ag-stage control-stage">
    <header class="ag-stage__header control-stage__header">
      <div class="ag-stage__title-block control-stage__title-block">
        <h2 class="ag-stage__title control-stage__title">Agents</h2>
        <p class="ag-stage__subtitle control-stage__subtitle">Custom personalities and skill sets you can chat with.</p>
      </div>
      <div class="ag-stage__actions control-stage__actions">
        <button
          class="ag-link"
          type="button"
          title="Provider and model defaults live in Settings"
          @click="openSettingsSurface"
        >
          open settings &rarr;
        </button>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <section class="stat-row control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 3">
      <div class="stat stat--hero control-stat control-stat--hero">
        <div class="stat-label control-stat__label">Total agents</div>
        <div class="stat-value control-stat__value">{{ total }}</div>
        <div class="stat-hint control-stat__hint">
          {{ builtins ? `${builtins} built-in` : '' }}
          {{ builtins && customs ? ' &middot; ' : '' }}
          {{ customs ? `${customs} custom` : '' }}
        </div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Models in use</div>
        <div class="stat-value mono control-stat__value control-stat__value--mono">{{ models.size || '—' }}</div>
        <div class="stat-hint control-stat__hint">{{ models.size ? 'distinct models' : 'unset' }}</div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Tools wired</div>
        <div class="stat-value control-stat__value">{{ toolsCount }}</div>
        <div class="stat-hint control-stat__hint">across all agents</div>
      </div>
    </section>

    <section class="ag-create">
      <form class="ag-create__form" @submit.prevent="onInlineAdd">
        <label class="ag-field">
          <span>Agent ID</span>
          <input v-model="newId" class="ag-input" name="id" autocomplete="off" required placeholder="e.g. data-analyst" />
        </label>
        <label class="ag-field">
          <span>Display name <span class="ag-field__optional">(optional)</span></span>
          <input v-model="newName" class="ag-input" name="name" autocomplete="off" placeholder="Defaults to ID" />
        </label>
        <button class="btn btn--primary" type="submit">
          <Icon name="plus" :size="16" />
          <span>Add</span>
        </button>
      </form>
      <p class="ag-create__hint">Created agents inherit the global default model. Click a card to view or edit details.</p>
    </section>

    <section class="ag-list">
      <div class="ag-list__head">
        <h3 class="ag-list__title">
          Configured agents
          <span v-if="agents.length > 0" class="ag-list__count">{{ agents.length }}</span>
        </h3>
      </div>

      <div v-if="agents.length === 0" class="state">
        <div class="state-icon">
          <Icon name="agents" :size="48" />
        </div>
        <div class="state-title">No agents configured.</div>
        <p class="state-text">Use the form above to add one. The default <code>main</code> agent is always available.</p>
      </div>

      <div v-else class="ag-cards control-card-grid" style="--control-card-min: 320px">
        <article
          v-for="(a, i) in agents"
          :key="a.id || a.name || i"
          class="ag-card control-card control-card--interactive"
          :class="{ 'is-builtin control-card--accent': isAgentBuiltin(a) }"
          :style="{ '--i': i }"
          tabindex="0"
          role="button"
          :aria-label="`View agent ${a.id || a.name || ''}`"
          @click="onCardClick"
          @keydown="onCardKeydown"
        >
          <header class="ag-card__head">
            <div class="ag-card__id-block">
              <span class="ag-card__id">{{ a.id || a.name || '—' }}</span>
              <span :class="['chip', isAgentBuiltin(a) ? 'chip-ok' : 'chip-info']">{{ a.type || (a.isBuiltin ? 'builtin' : 'custom') }}</span>
            </div>
            <div class="ag-card__actions">
              <button class="ag-iconbtn" title="Open chat" @click.stop="openChat(a.id)">
                <Icon name="chat" :size="16" />
                <span>Chat</span>
              </button>
              <button
                v-if="isAgentBuiltin(a)"
                class="ag-iconbtn"
                title="Use as starting point for a new agent"
                @click.stop="customizeFromBuiltin(a.id)"
              >
                <Icon name="plus" :size="16" />
                <span>Customize&hellip;</span>
              </button>
              <button
                v-else
                class="ag-iconbtn"
                title="Edit"
                @click.stop="openDrawer('edit', a.id)"
              >
                <Icon name="edit" :size="16" />
                <span>Edit</span>
              </button>
              <button
                v-if="!isAgentBuiltin(a)"
                class="ag-iconbtn ag-iconbtn--danger"
                title="Delete"
                @click.stop="deleteAgent(a.id)"
              >
                <Icon name="trash" :size="16" />
                <span>Delete</span>
              </button>
            </div>
          </header>
          <div class="ag-card__name">{{ a.name || a.id || '—' }}</div>
          <p v-if="a.description" class="ag-card__desc">{{ a.description }}</p>
          <dl class="ag-card__meta">
            <div v-if="a.model">
              <dt>Model</dt>
              <dd class="ag-mono">{{ a.model }}</dd>
            </div>
            <div v-if="agentTools(a).length">
              <dt>Tools</dt>
              <dd>{{ agentTools(a).length }}</dd>
            </div>
            <div v-if="agentSkills(a).length">
              <dt>Skills</dt>
              <dd>{{ agentSkills(a).length }}</dd>
            </div>
          </dl>
          <div v-if="agentTools(a).length" class="ag-card__chips">
            <span class="ag-chips-label">Tools</span>
            <span v-for="t in agentTools(a).slice(0, 8)" :key="t" class="ag-chip">{{ t }}</span>
            <span v-if="agentTools(a).length > 8" class="ag-chip ag-chip--dim">+{{ agentTools(a).length - 8 }}</span>
          </div>
        </article>
      </div>
    </section>

    <!-- Drawer -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="drawerOpen" class="drawer-overlay" @click="onOverlayClick">
          <div class="drawer" :class="{ 'drawer--wide': true }" @click.stop>
            <div class="drawer__header">
              <h3 class="drawer__title">{{ drawerTitle }}</h3>
              <button class="drawer__close" aria-label="Close" @click="closeDrawer">
                <Icon name="x" :size="20" />
              </button>
            </div>
            <div class="drawer__body">
              <div class="ag-drawer__sections">
                <fieldset class="ag-drawer__section">
                  <legend>Identity</legend>
                  <label class="ag-field">
                    <span>Agent ID</span>
                    <input v-model="form.id" class="ag-input" type="text" autocomplete="off" disabled />
                  </label>
                  <label class="ag-field">
                    <span>Display name</span>
                    <input v-model="form.name" class="ag-input" type="text" autocomplete="off" :disabled="drawerMode === 'view'" placeholder="Defaults to ID" />
                  </label>
                  <label class="ag-field">
                    <span>Description</span>
                    <input v-model="form.description" class="ag-input" type="text" autocomplete="off" :disabled="drawerMode === 'view'" placeholder="A short one-liner" />
                  </label>
                </fieldset>

                <details class="ag-drawer__section ag-drawer__section--advanced" :open="advancedOpen">
                  <summary>Capabilities &middot; Advanced</summary>
                  <label class="ag-field">
                    <span>Tools (comma-separated)</span>
                    <input v-model="toolsInput" class="ag-input" type="text" autocomplete="off" :disabled="drawerMode === 'view'" placeholder="Leave blank to inherit defaults" />
                  </label>
                  <label class="ag-field">
                    <span>Workspace</span>
                    <input v-model="form.workspace" class="ag-input" type="text" autocomplete="off" :disabled="drawerMode === 'view'" placeholder="Leave blank to use the default path" />
                  </label>
                  <label class="ag-field">
                    <span>Agent dir</span>
                    <input v-model="form.agentDir" class="ag-input" type="text" autocomplete="off" :disabled="drawerMode === 'view'" placeholder="Optional" />
                  </label>
                  <label class="ag-field ag-field--inline">
                    <input v-model="form.enabled" type="checkbox" :disabled="drawerMode === 'view'" />
                    <span>Enabled</span>
                  </label>
                </details>

                <div v-if="drawerModel || systemPromptHint" class="ag-drawer__readonly-meta">
                  <div v-if="drawerModel">
                    <dt>Inherited model</dt>
                    <dd class="ag-mono">{{ drawerModel }}</dd>
                  </div>
                  <div v-if="systemPromptHint">
                    <dt>System prompt</dt>
                    <dd class="ag-dim">Stored in config &mdash; runtime currently sources from agent SOUL.md instead.</dd>
                  </div>
                </div>
              </div>
            </div>
            <div class="drawer__footer">
              <template v-if="drawerMode === 'view'">
                <button class="btn btn--ghost" @click="closeDrawer">Close</button>
                <button v-if="drawerIsBuiltin" class="btn btn--primary" @click="customizeFromBuiltin(drawerAgentId)">
                  <Icon name="plus" :size="16" />
                  <span>Customize&hellip;</span>
                </button>
                <button v-else class="btn btn--primary" @click="enterEditMode">Edit</button>
              </template>
              <template v-else>
                <button class="btn btn--ghost" @click="onCancelEdit">Cancel</button>
                <button class="btn btn--primary" :disabled="!isDirty || saving" @click="onSave">
                  Save changes{{ isDirty ? ' &bull;' : '' }}
                </button>
              </template>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Confirm modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="confirmOpen" class="modal-overlay" @click="confirmOpen = false">
          <div class="modal" @click.stop>
            <h3 class="modal__title">{{ confirmTitle }}</h3>
            <div class="modal__body">
              <p>{{ confirmBody }}</p>
            </div>
            <div class="modal__footer">
              <button :class="['btn', confirmPrimaryClass]" @click="onConfirmPrimary">{{ confirmPrimaryLabel }}</button>
              <button class="btn btn--ghost" @click="confirmOpen = false">Cancel</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import { useAgentsData } from '@/composables/agents/useAgentsData'
import { isAgentBuiltin, useAgentDrawer } from '@/composables/agents/useAgentDrawer'
import type { Agent } from '@/types/agents'

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const appStore = useAppStore()
const rpc = useRpcStore()
const router = useRouter()

const { agents, loadData } = useAgentsData()
const newId = ref('')
const newName = ref('')

const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmBody = ref('')
const confirmPrimaryLabel = ref('Confirm')
const confirmPrimaryClass = ref('btn--danger')
let confirmResolve: ((value: boolean) => void) | null = null

const {
  drawerOpen,
  drawerMode,
  drawerAgentId,
  drawerIsBuiltin,
  drawerModel,
  systemPromptHint,
  saving,
  form,
  drawerTitle,
  isDirty,
  toolsInput,
  advancedOpen,
  openDrawer,
  closeDrawer,
  enterEditMode,
  onOverlayClick,
  onCancelEdit,
  buildSavePayload,
  applyUpdatedAgent,
} = useAgentDrawer(agents, confirmDiscard)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const total = computed(() => agents.value.length)
const builtins = computed(() => agents.value.filter(a => a.type === 'builtin' || a.isBuiltin).length)
const customs = computed(() => total.value - builtins.value)
const toolsCount = computed(() =>
  agents.value.reduce((acc, a) => acc + (Array.isArray(a.tools) ? a.tools.length : 0), 0)
)
const models = computed(() => {
  const set = new Set<string>()
  agents.value.forEach(a => { if (a.model) set.add(a.model) })
  return set
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function agentTools(a: Agent): string[] {
  return Array.isArray(a.tools) ? a.tools : []
}

function agentSkills(a: Agent): string[] {
  return Array.isArray(a.skills) ? a.skills : []
}

function onCardClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.closest('button')) return
  const card = target.closest('.ag-card') as HTMLElement | null
  if (!card) return
  const id = card.querySelector('.ag-card__id')?.textContent || ''
  if (id) openDrawer('view', id)
}

function onCardKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if ((event.key === 'Enter' || event.key === ' ') && target.classList.contains('ag-card')) {
    event.preventDefault()
    const id = target.querySelector('.ag-card__id')?.textContent || ''
    if (id) openDrawer('view', id)
  }
}

// Desktop keeps its settings route; web opens the settings modal in place.
function openSettingsSurface() {
  if (router.hasRoute('settings')) {
    router.push('/settings')
    return
  }
  appStore.setSettingsOpen(true)
}

function openChat(id?: string) {
  if (!id) return
  const agentId = String(id || '').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '') || 'main'
  const suffix = Math.random().toString(36).slice(2, 10)
  router.push({ path: '/chat', query: { session: `agent:${agentId}:webchat:${suffix}` } })
}

// ---------------------------------------------------------------------------
// Inline create
// ---------------------------------------------------------------------------

async function onInlineAdd() {
  const id = newId.value.trim()
  const name = newName.value.trim()
  if (!id) return
  const payload: Record<string, unknown> = { id }
  if (name) payload.name = name
  try {
    await rpc.call('agents.create', payload)
    console.warn('Agent created: ' + id)
    newId.value = ''
    newName.value = ''
    await loadData()
  } catch (err: unknown) {
    const code = rpcErrorCode(err)
    if (code === 'agent.exists') console.warn(`Agent "${id}" already exists`)
    else console.warn('Failed to create agent: ' + errorMessage(err))
  }
}

function customizeFromBuiltin(builtinId?: string) {
  const seedId = (builtinId || 'main') + '-copy'
  newId.value = seedId
  newName.value = (builtinId || 'main') + ' (copy)'
  nextTick(() => {
    const input = document.querySelector('.ag-create__form input[name="id"]') as HTMLInputElement | null
    if (input) {
      input.focus()
      input.select()
    }
    document.querySelector('.ag-create')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  console.warn('Tweak the ID, then click Add to create your copy')
}

async function onSave() {
  if (saving.value) return
  saving.value = true
  try {
    const payload = buildSavePayload()
    if (Object.keys(payload).length <= 1) {
      console.warn('Nothing to save')
      saving.value = false
      return
    }
    await rpc.call('agents.update', payload)
    console.warn('Agent updated: ' + drawerAgentId.value)
    await loadData()
    const updated = agents.value.find(a => a.id === drawerAgentId.value)
    if (updated) {
      applyUpdatedAgent(updated)
    }
  } catch (err: unknown) {
    const code = rpcErrorCode(err)
    const msg = errorMessage(err)
    let friendly = 'Failed to save: ' + msg
    if (code === 'agent.not_found') friendly = `Agent "${drawerAgentId.value}" no longer exists.`
    if (code === 'agent.builtin_immutable') friendly = `"${drawerAgentId.value}" is a built-in agent and cannot be modified.`
    console.warn(friendly)
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

async function deleteAgent(id?: string) {
  if (!id) return
  const ok = await confirmModal(
    'Delete agent',
    `Delete agent ${id}? Existing chats with this agent will keep working but become unmanaged.`,
    'Delete',
    'btn--danger'
  )
  if (!ok) return
  try {
    await rpc.call('agents.delete', { id })
    console.warn('Agent deleted: ' + id)
    await loadData()
  } catch (err: unknown) {
    console.warn('Failed to delete agent: ' + errorMessage(err))
  }
}

// ---------------------------------------------------------------------------
// Confirm helpers
// ---------------------------------------------------------------------------

function confirmModal(title: string, bodyText: string, primaryLabel = 'Confirm', primaryCls = 'btn--danger'): Promise<boolean> {
  return new Promise((resolve) => {
    confirmTitle.value = title
    confirmBody.value = bodyText
    confirmPrimaryLabel.value = primaryLabel
    confirmPrimaryClass.value = primaryCls
    confirmOpen.value = true
    confirmResolve = resolve
  })
}

function onConfirmPrimary() {
  confirmOpen.value = false
  if (confirmResolve) {
    confirmResolve(true)
    confirmResolve = null
  }
}

function confirmDiscard(): Promise<boolean> {
  return confirmModal(
    'Discard unsaved changes?',
    'You have unsaved edits. Closing now will lose them.',
    'Discard',
    'btn--danger'
  )
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function rpcErrorCode(err: unknown): string {
  if (!err || typeof err !== 'object' || !('code' in err)) return ''
  const code = (err as { code?: unknown }).code
  return typeof code === 'string' ? code : ''
}
</script>

<style scoped>
.stat--hero {
  min-height: 116px;
}

.ag-link {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--accent);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-xs);
  font-weight: 600;
  justify-content: center;
  letter-spacing: 0.04em;
  min-height: 40px;
  padding: 0 var(--sp-1);
  white-space: nowrap;
}

.ag-link:hover {
  color: var(--accent-hover);
}

.ag-create {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.ag-create__form {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.ag-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 180px;
}

.ag-field span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.ag-field__optional {
  color: var(--text-dim);
  font-weight: 400;
}

.ag-input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

.ag-input:focus {
  border-color: var(--accent);
  outline: none;
}

.ag-input:disabled {
  opacity: 0.6;
}

.ag-create__hint {
  color: var(--text-dim);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0 0;
}

.ag-list__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.ag-list__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.ag-list__count {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
  padding: 2px 8px;
}

.ag-card {
  outline: none;
}

.ag-card.is-builtin {
  border-left: 3px solid var(--ok);
}

.ag-card__head {
  align-items: flex-start;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.ag-card__id-block {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.ag-card__id {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ag-card__actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.ag-iconbtn {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  padding: 4px 8px;
  font-size: 12px;
}

.ag-iconbtn:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.ag-iconbtn--danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.ag-card__name {
  font-size: var(--fs-md);
  font-weight: 600;
}

.ag-card__desc {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

.ag-card__meta {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
}

.ag-card__meta > div {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.ag-card__meta dt {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

.ag-card__meta dd {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  margin: 0;
}

.ag-mono {
  font-family: var(--font-mono);
}

.ag-card__chips {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ag-chips-label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  margin-right: 4px;
  text-transform: uppercase;
}

.ag-chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
}

.ag-chip--dim {
  opacity: 0.6;
}

.chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  text-transform: uppercase;
}

.chip-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.chip-info {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.state {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.state-icon {
  color: var(--text-dim);
}

.state-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.state-text {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
  max-width: 520px;
}

/* Drawer */
.drawer-overlay {
  align-items: flex-end;
  background: rgba(0, 0, 0, 0.4);
  bottom: 0;
  display: flex;
  justify-content: flex-end;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1000;
}

.drawer {
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 520px;
  width: 100%;
}

.drawer--wide {
  max-width: 520px;
}

.drawer__header {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: var(--sp-4);
}

.drawer__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
}

.drawer__close {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 32px;
  justify-content: center;
  width: 32px;
}

.drawer__close:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
}

.drawer__footer {
  align-items: center;
  border-top: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
  padding: var(--sp-4);
}

.ag-drawer__sections {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.ag-drawer__section {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin: 0;
  padding: var(--sp-4);
}

.ag-drawer__section legend,
.ag-drawer__section summary {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 600;
}

.ag-drawer__section--advanced summary {
  cursor: pointer;
  user-select: none;
}

.ag-field--inline {
  align-items: center;
  flex-direction: row;
  gap: 8px;
}

.ag-drawer__readonly-meta {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: grid;
  gap: var(--sp-2);
  padding: var(--sp-4);
}

.ag-drawer__readonly-meta > div {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.ag-drawer__readonly-meta dt {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

.ag-drawer__readonly-meta dd {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  margin: 0;
}

.ag-dim {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

/* Modal */
.modal-overlay {
  align-items: center;
  background: rgba(0, 0, 0, 0.5);
  bottom: 0;
  display: flex;
  justify-content: center;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1100;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  max-width: 420px;
  padding: var(--sp-5);
  width: 90%;
}

.modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.modal__body {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin-bottom: var(--sp-4);
}

.modal__footer {
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
}

/* Transitions */
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ag-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .ag-stage__header .btn {
    align-self: flex-start;
    width: auto;
  }

  .ag-cards {
    grid-template-columns: 1fr;
  }

  .drawer {
    max-width: 100%;
  }
}

@media (max-width: 480px) {
  .stat-row {
    grid-template-columns: 1fr;
  }
}
</style>
