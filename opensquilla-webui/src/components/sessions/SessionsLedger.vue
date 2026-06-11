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
        :aria-label="'Open in chat: ' + entry.item.title"
        @click="emit('open', entry.item)"
      >
        <span class="hub-row__icon" aria-hidden="true">
          <Icon :name="surfaceIcon(entry.item)" :size="15" />
        </span>
        <span class="hub-row__body">
          <span class="hub-row__title">{{ entry.item.title }}</span>
          <span v-if="entry.item.subtitle" class="hub-row__subtitle">{{ entry.item.subtitle }}</span>
        </span>
        <span class="hub-row__agent">{{ agentName(entry.item) }}</span>
        <span
          v-if="statusBadge(entry.item)"
          class="hub-row__status"
          :class="statusBadge(entry.item)!.cls"
        >
          {{ statusBadge(entry.item)!.label }}
        </span>
        <span class="hub-row__meta">
          <span class="hub-row__count">{{ entry.item.messageCount != null ? entry.item.messageCount.toLocaleString() : '—' }} msg</span>
          <span class="hub-row__time">{{ relTime(entry.item.updatedAt) }}</span>
        </span>
      </button>
      <button
        type="button"
        class="hub-row__delete"
        :aria-label="'Delete session: ' + entry.item.title"
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

function relTime(timestamp: number | undefined): string {
  if (!timestamp) return '—'
  const d = new Date(timestamp)
  if (isNaN(d.getTime())) return '—'

  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString()
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
}

.hub-row:last-child {
  border-bottom: none;
}

.hub-row--child .hub-row__main {
  padding-left: calc(var(--sp-4) + var(--hub-row-depth, 1) * var(--sp-6));
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

.hub-row__status--running {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
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
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 35%, var(--border));
  color: var(--warn);
}

.hub-row__status--failed {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
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
</style>
