<template>
  <ul class="hub-ledger" aria-label="Sessions">
    <li
      v-for="entry in entries"
      :key="entry.item.key"
      class="hub-row"
      :class="{ 'hub-row--child': entry.depth > 0 }"
      :style="entry.depth > 0 ? { '--hub-row-depth': entry.depth } : undefined"
      :data-kind="entry.item.sessionKind"
    >
      <button
        type="button"
        class="hub-row__main"
        :class="{ 'hub-row__main--running': channel(entry.item).running }"
        :style="{ '--readout-ch': channel(entry.item).token }"
        :aria-label="rowAccessibleName('Inspect', entry)"
        @click="emit('open', entry.item)"
      >
        <span
          class="control-readout__dot hub-row__channel"
          :class="{ 'control-readout__dot--pulse': channel(entry.item).running }"
          aria-hidden="true"
        ></span>
        <span class="hub-row__icon" aria-hidden="true">
          <Icon :name="surfaceIcon(entry.item)" :size="15" />
        </span>
        <span class="hub-row__body">
          <span class="hub-row__title">{{ rowTitle(entry) }}</span>
          <span v-if="entry.item.subtitle" class="hub-row__subtitle">{{ entry.item.subtitle }}</span>
        </span>
        <span v-if="entry.item.forkedFromParent" class="hub-row__fork-badge">Fork</span>
        <span class="hub-row__agent">{{ agentName(entry.item) }}</span>
        <span
          v-if="statusBadge(entry.item)"
          class="control-readout__trace hub-row__trace"
          aria-hidden="true"
        >
          <span
            class="control-readout__trace-fill"
            :style="{ width: channel(entry.item).trace }"
          ></span>
        </span>
        <span
          v-if="statusBadge(entry.item)"
          class="hub-row__status"
          :class="statusBadge(entry.item)!.cls"
        >
          {{ statusBadge(entry.item)!.label }}
        </span>
        <span class="hub-row__meta">
          <span class="hub-row__count">{{ entry.item.messageCount ? entry.item.messageCount.toLocaleString() + ' msg' : '—' }}</span>
          <span class="hub-row__time">{{ formatRelativeTime(entry.item.updatedAt) }}</span>
        </span>
      </button>
      <button
        type="button"
        class="hub-row__delete"
        :aria-label="rowAccessibleName('Delete', entry)"
        @click="emit('remove', entry.item)"
      >
        <Icon name="trash" :size="14" />
      </button>
    </li>
  </ul>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { IconName } from '@/utils/icons'
import type { SessionItem, SessionLedgerEntry } from '@/composables/useSessions'
import { formatRelativeTime, subagentRowTitle } from './sessionDisplay'

const props = defineProps<{
  entries: SessionLedgerEntry[]
  agentNames: Map<string, string>
  needsInputKeys: Set<string>
}>()

const emit = defineEmits<{
  open: [item: SessionItem]
  remove: [item: SessionItem]
}>()

function surfaceIcon(item: SessionItem): IconName {
  if (item.sessionKind === 'cron') return 'cron'
  if (item.sessionKind === 'channel') return 'channels'
  if (item.sessionKind === 'task' || item.surface === 'subagent') return 'agents'
  if (item.sessionKind === 'chat') return 'chat'
  return 'sessions'
}

function agentName(item: SessionItem): string {
  const id = item.effectiveAgentId
  if (!id || id === 'unknown') return 'Unknown agent'
  return props.agentNames.get(id) || id
}

function statusBadge(item: SessionItem): { label: string; cls: string } | null {
  if (props.needsInputKeys.has(item.key)) {
    return { label: 'Needs input', cls: 'hub-row__status--needs-input' }
  }
  const map: Record<string, { label: string; cls: string }> = {
    running: { label: 'Running', cls: 'hub-row__status--running' },
    queued: { label: 'Queued', cls: 'hub-row__status--queued' },
    failed: { label: 'Failed', cls: 'hub-row__status--failed' },
    timeout: { label: 'Timed out', cls: 'hub-row__status--failed' },
    interrupted: { label: 'Interrupted', cls: 'hub-row__status--queued' },
    cancelled: { label: 'Cancelled', cls: 'hub-row__status--off' },
  }
  return map[item.runStatus] || null
}

// The Stomatopod channel readout, applied to existing row data (no new wiring):
// map each row's run-state onto one calibrated spectrum channel — the leading
// dot + the trace bar both read --readout-ch. running reuses the strike pulse.
function channel(item: SessionItem): { token: string; trace: string; running: boolean } {
  if (props.needsInputKeys.has(item.key)) {
    return { token: 'var(--warn)', trace: '60%', running: false }
  }
  const map: Record<string, { token: string; trace: string; running: boolean }> = {
    running: { token: 'var(--accent)', trace: '72%', running: true },
    queued: { token: 'var(--queued)', trace: '18%', running: false },
    interrupted: { token: 'var(--queued)', trace: '40%', running: false },
    failed: { token: 'var(--danger)', trace: '100%', running: false },
    timeout: { token: 'var(--danger)', trace: '100%', running: false },
    cancelled: { token: 'var(--text-dim)', trace: '100%', running: false },
  }
  return map[item.runStatus] || { token: 'var(--ok)', trace: '100%', running: false }
}

function rowTitle(entry: SessionLedgerEntry): string {
  // Subagent rows read as lineage ("↳ Subagent · {parent}") instead of a flat
  // title; forked conversations keep their own (copied) title behind the
  // lineage arrow; root rows keep their human title.
  if (entry.depth <= 0) return entry.item.title
  if (entry.item.forkedFromParent) return `↳ ${entry.item.title}`
  return subagentRowTitle(entry.parentTitle)
}

// Screen readers announce "↳" as "right-pointing arrow" noise; the accessible
// name carries the lineage in words instead.
function rowAccessibleName(verb: string, entry: SessionLedgerEntry): string {
  const plain = rowTitle(entry).replace(/^↳\s*/, '')
  const kind = entry.depth > 0
    ? (entry.item.forkedFromParent ? 'forked session' : 'subagent session')
    : 'session'
  return `${verb} ${kind}: ${plain}`
}
</script>

<style scoped>
.hub-ledger {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  list-style: none;
  margin: 0;
  overflow: hidden;
  padding: 0;
}

.hub-row {
  align-items: center;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  display: flex;
  gap: var(--sp-1);
  position: relative;
}

.hub-row:last-child {
  border-bottom: none;
}

.hub-row--child .hub-row__main {
  padding-left: calc(var(--sp-4) + var(--hub-row-depth, 1) * var(--sp-4));
}

/* Thin guide line marking subagent lineage under its parent. */
.hub-row--child::before {
  background: var(--border);
  bottom: 0;
  content: '';
  left: calc(var(--sp-4) + (var(--hub-row-depth, 1) - 0.5) * var(--sp-4));
  position: absolute;
  top: 0;
  width: 1px;
}

.hub-row__main {
  align-items: center;
  background: transparent;
  border: none;
  color: var(--text);
  cursor: pointer;
  display: flex;
  flex: 1;
  font: inherit;
  gap: var(--sp-3);
  min-width: 0;
  padding: var(--sp-3) var(--sp-2) var(--sp-3) var(--sp-4);
  text-align: left;
  transition: background var(--transition);
}

.hub-row__main:hover {
  background: color-mix(in srgb, var(--bg-elevated) 60%, transparent);
}

.hub-row__main:focus-visible {
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--accent) 50%, transparent);
  outline: none;
}

/* Leading spectral channel dot — the Stomatopod readout applied to the row.
   Its color comes from --readout-ch, set inline per row from the run-state. */
.hub-row__main {
  --readout-ch: var(--text-muted);
}

.hub-row__channel {
  flex-shrink: 0;
}

/* Thin token-colored trace bar before the status label — the readout's
   oscilloscope trace, encoding progress/severity in the row's channel color. */
.hub-row__trace {
  flex: 0 0 auto;
  width: 48px;
  min-width: 48px;
}

.hub-row__icon {
  align-items: center;
  color: var(--text-dim);
  display: inline-flex;
  flex-shrink: 0;
}

.hub-row--child .hub-row__icon {
  color: var(--text-muted);
}

.hub-row__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.hub-row__title {
  font-size: var(--fs-sm);
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hub-row__subtitle {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Accent-tinted lineage badge: this row is a forked conversation, not a subagent. */
.hub-row__fork-badge {
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  border-radius: var(--radius-sm);
  color: var(--accent);
  flex-shrink: 0;
  font-size: var(--fs-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 1px var(--sp-2);
  text-transform: uppercase;
  white-space: nowrap;
}

.hub-row__agent {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  flex-shrink: 0;
  font-size: var(--fs-xs);
  font-weight: 650;
  max-width: 140px;
  overflow: hidden;
  padding: 2px var(--sp-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hub-row__status {
  border: 1px solid var(--border);
  border-radius: 999px;
  flex-shrink: 0;
  font-size: var(--fs-xs);
  font-weight: 650;
  padding: 2px var(--sp-2);
  white-space: nowrap;
}

/* running reuses the strike channel (orange) per the spectrum. */
.hub-row__status--running {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
  animation: pulse 1.5s ease-in-out infinite;
}

.hub-row__status--needs-input {
  background: color-mix(in srgb, var(--warn) 14%, transparent);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--border));
  color: var(--warn);
  animation: hub-row-glow 2s ease-in-out infinite;
}

@keyframes hub-row-glow {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 0%, transparent); }
  50% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 30%, transparent); }
}

.hub-row__status--queued {
  background: color-mix(in srgb, var(--queued) 12%, transparent);
  border-color: color-mix(in srgb, var(--queued) 38%, var(--border));
  color: var(--queued);
}

.hub-row__status--failed {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

@media (prefers-reduced-motion: reduce) {
  .hub-row__status--running,
  .hub-row__status--needs-input {
    animation: none;
  }
}

.hub-row__status--off {
  color: var(--text-dim);
}

.hub-row__meta {
  align-items: flex-end;
  color: var(--text-dim);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  gap: 2px;
  min-width: 64px;
  text-align: right;
}

.hub-row__delete {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  cursor: pointer;
  display: inline-flex;
  flex-shrink: 0;
  height: 32px;
  justify-content: center;
  margin-right: var(--sp-2);
  transition: background var(--transition), color var(--transition);
  width: 32px;
}

.hub-row__delete:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: var(--danger);
}

.hub-row__delete:focus-visible {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

@media (max-width: 760px) {
  .hub-row__agent {
    display: none;
  }

  .hub-row__meta {
    min-width: 52px;
  }
}

/* Phone widths: the badge + meta + delete columns crush the title to a couple
   of characters; drop the secondary time line and slim the badge so the row's
   identity stays readable. */
@media (max-width: 760px) {
  .hub-row__trace {
    display: none;
  }
}

@media (max-width: 480px) {
  .hub-row__time {
    display: none;
  }

  .hub-row__meta {
    min-width: 0;
  }

  .hub-row__fork-badge {
    padding: 1px var(--sp-1);
    letter-spacing: 0;
  }
}
</style>
