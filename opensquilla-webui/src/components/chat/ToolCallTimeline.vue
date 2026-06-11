<template>
  <template v-for="item in visibleItems" :key="item.key">
    <div v-if="item.type === 'text'" class="msg-ai-text" v-html="item.html" />
    <button
      v-else-if="item.type === 'overflow'"
      type="button"
      class="tool-overflow-note"
      title="Show all calls"
      @click="showAllRows = true"
    >
      …{{ item.hiddenCount }} earlier calls
    </button>
    <div v-else class="step-card">
      <div
        class="step-group"
        :class="{
          'step-group--running': item.group.isRunning,
          'step-group--error': item.group.isError,
          'is-open': groupOpen(item.group),
        }"
      >
        <!-- Multi-call batches keep a group header; single calls render as one row. -->
        <template v-if="item.group.calls.length > 1">
          <button
            type="button"
            class="tool-row tool-row--group"
            :aria-expanded="groupOpen(item.group)"
            @click="$emit('toggleGroup', item.group.groupId)"
          >
            <span class="tool-row__bullet" :class="groupBulletClass(item.group)" aria-hidden="true" />
            <span class="tool-row__label">{{ item.group.label }}</span>
            <span class="step-count">{{ item.group.calls.length }} calls</span>
            <span v-if="item.group.secondary" class="tool-row__arg">{{ item.group.secondary }}</span>
            <span class="tool-row__trailing">
              <span class="tool-row__status">{{ toolGroupStatusText(item.group) }}</span>
              <Icon class="step-chevron" name="chevronRight" :size="14" />
            </span>
          </button>
          <div v-if="groupOpen(item.group)" class="step-group-members">
            <div v-for="call in item.group.calls" :key="call.renderKey" class="tool-row-wrap">
              <button
                type="button"
                class="tool-row tool-row--member"
                :class="rowClass(call)"
                :data-op="operationKey(call)"
                :aria-expanded="callOpen(call)"
                @click="$emit('toggleItem', call.renderKey)"
              >
                <span class="tool-row__bullet" :class="bulletClass(call)" aria-hidden="true" />
                <span class="tool-row__label tool-row__label--member">{{ call.displayName }}</span>
                <span v-if="toolSecondaryText(call)" class="tool-row__arg">{{ toolSecondaryText(call) }}</span>
                <span class="tool-row__trailing">
                  <span v-if="resultCountText(call)" class="tool-row__status">{{ resultCountText(call) }}</span>
                  <span v-if="elapsedFor(call)" class="tool-row__elapsed">{{ elapsedFor(call) }}</span>
                  <Icon v-if="call.status === 'success'" class="tool-row__state-icon tool-row__state-icon--ok" name="check" :size="13" />
                  <Icon v-else-if="call.status === 'error'" class="tool-row__state-icon tool-row__state-icon--err" name="x" :size="13" />
                  <Icon class="step-chevron" name="chevronRight" :size="14" />
                </span>
              </button>
              <div v-if="callOpen(call)" class="tool-row-body">
                <ToolRowSections :call="call" :label="call.displayName" @show-result="forwardShowResult" />
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <div v-for="call in item.group.calls" :key="call.renderKey" class="tool-row-wrap">
            <button
              type="button"
              class="tool-row"
              :class="rowClass(call)"
              :data-op="operationKey(call)"
              :aria-expanded="callOpen(call)"
              @click="$emit('toggleItem', call.renderKey)"
            >
              <span class="tool-row__bullet" :class="bulletClass(call)" aria-hidden="true" />
              <span class="tool-row__label">{{ item.group.label }}</span>
              <span v-if="toolSecondaryText(call)" class="tool-row__arg">{{ toolSecondaryText(call) }}</span>
              <span class="tool-row__trailing">
                <span v-if="resultCountText(call)" class="tool-row__status">{{ resultCountText(call) }}</span>
                <span v-if="elapsedFor(call)" class="tool-row__elapsed">{{ elapsedFor(call) }}</span>
                <Icon v-if="call.status === 'success'" class="tool-row__state-icon tool-row__state-icon--ok" name="check" :size="13" />
                <Icon v-else-if="call.status === 'error'" class="tool-row__state-icon tool-row__state-icon--err" name="x" :size="13" />
                <Icon class="step-chevron" name="chevronRight" :size="14" />
              </span>
            </button>
            <div v-if="callOpen(call)" class="tool-row-body">
              <ToolRowSections :call="call" :label="item.group.label" @show-result="forwardShowResult" />
            </div>
          </div>
        </template>
      </div>
    </div>
  </template>
</template>

<script lang="ts">
import { defineComponent, h, type PropType } from 'vue'
import type { ChatToolCallRenderItem } from '@/types/chat'

const SECTION_PREVIEW_LIMIT = 200

// Labeled input / result / error sections shown in an expanded row body.
const ToolRowSections = defineComponent({
  name: 'ToolRowSections',
  props: {
    call: { type: Object as PropType<ChatToolCallRenderItem>, required: true },
    label: { type: String, required: true },
  },
  emits: ['showResult'],
  setup(props, { emit }) {
    return () => {
      const call = props.call
      const sections = []
      if (call.inputPreview) {
        const fullInput = call.inputRaw || ''
        sections.push(h('section', { class: 'tool-row-section' }, [
          h('div', { class: 'tool-row-section__label' }, 'input'),
          h('pre', { class: 'tool-row-section__pre' }, call.inputPreview),
          fullInput.length > SECTION_PREVIEW_LIMIT
            ? h('button', {
                type: 'button',
                class: 'step-view-btn',
                onClick: (event: Event) => {
                  event.stopPropagation()
                  emit('showResult', fullInput, `${props.label} · input`)
                },
              }, 'view full')
            : null,
        ]))
      }
      if (call.result) {
        const kind = call.isError ? 'error' : 'result'
        sections.push(h('section', {
          class: ['tool-row-section', { 'tool-row-section--error': call.isError }],
        }, [
          h('div', { class: 'tool-row-section__label' }, kind),
          h('pre', { class: 'tool-row-section__pre' }, call.resultPreview),
          call.result.length > SECTION_PREVIEW_LIMIT
            ? h('button', {
                type: 'button',
                class: 'step-view-btn',
                onClick: (event: Event) => {
                  event.stopPropagation()
                  emit('showResult', call.result, `${props.label} · ${kind}`)
                },
              }, 'view full')
            : null,
        ]))
      }
      return sections
    }
  },
})

export default { components: { ToolRowSections } }
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type {
  ChatStreamTimelineItem,
  ChatToolCallGroup,
} from '@/types/chat'
import { toolOperationKey, toolResultCount } from '@/utils/chat/toolDisplay'

const MAX_TOOL_ROWS = 30

// Reads and searches collapse to a pill by default; writes, exec, and unknown
// tools stay expanded; error rows auto-expand. Manual toggles invert the
// default, so a user collapse is always respected.
const COLLAPSED_BY_DEFAULT = new Set(['web.search', 'web.read', 'file.inspect', 'memory.search'])

type TimelineRenderItem =
  | ChatStreamTimelineItem
  | { type: 'overflow'; key: string; hiddenCount: number }

const props = defineProps<{
  items: ChatStreamTimelineItem[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
  // Live streams provide real per-call timings; replayed history omits this
  // prop, so no fabricated elapsed badges appear.
  toolElapsedText?: (call: ChatToolCallRenderItem) => string
}>()

const emit = defineEmits<{
  toggleGroup: [groupId: string]
  toggleItem: [renderKey: string]
  showResult: [content: string, title: string]
}>()

const showAllRows = ref(false)

const totalCalls = computed(() => props.items.reduce(
  (count, item) => item.type === 'tool-group' ? count + item.group.calls.length : count,
  0,
))

// Cap rendered tool rows per turn; earliest calls collapse into one note.
const visibleItems = computed<TimelineRenderItem[]>(() => {
  if (showAllRows.value || totalCalls.value <= MAX_TOOL_ROWS) return props.items
  let toHide = totalCalls.value - MAX_TOOL_ROWS
  const out: TimelineRenderItem[] = [{ type: 'overflow', key: 'overflow', hiddenCount: toHide }]
  for (const item of props.items) {
    if (item.type !== 'tool-group' || toHide <= 0) {
      out.push(item)
      continue
    }
    if (item.group.calls.length <= toHide) {
      toHide -= item.group.calls.length
      continue
    }
    out.push({ ...item, group: { ...item.group, calls: item.group.calls.slice(toHide) } })
    toHide = 0
  }
  return out
})

function operationKey(call: ChatToolCallRenderItem): string {
  return toolOperationKey(call.name)
}

function callDefaultOpen(call: ChatToolCallRenderItem): boolean {
  if (call.isError || call.status === 'error') return true
  return !COLLAPSED_BY_DEFAULT.has(operationKey(call))
}

function callOpen(call: ChatToolCallRenderItem): boolean {
  // A recorded toggle inverts the default, so error auto-expand still honors
  // an explicit user collapse.
  return callDefaultOpen(call) !== props.isToolItemOpen(call.renderKey)
}

function groupOpen(group: ChatToolCallGroup): boolean {
  const defaultOpen = group.calls.some(callDefaultOpen)
  return defaultOpen !== props.isToolGroupOpen(group.groupId)
}

function rowClass(call: ChatToolCallRenderItem) {
  return {
    'tool-row--running': call.isRunning,
    'tool-row--error': call.status === 'error' || call.isError,
    'is-open': callOpen(call),
  }
}

function bulletClass(call: ChatToolCallRenderItem) {
  return {
    'tool-row__bullet--running': call.isRunning,
    'tool-row__bullet--ok': call.status === 'success',
    'tool-row__bullet--err': call.status === 'error' || call.isError,
  }
}

function groupBulletClass(group: ChatToolCallGroup) {
  return {
    'tool-row__bullet--running': group.isRunning,
    'tool-row__bullet--ok': group.status === 'success',
    'tool-row__bullet--err': group.isError,
  }
}

function resultCountText(call: ChatToolCallRenderItem): string {
  if (call.isRunning || call.isError) return ''
  const count = toolResultCount(call.result)
  return count === null ? '' : `${count} results`
}

function elapsedFor(call: ChatToolCallRenderItem): string {
  return props.toolElapsedText?.(call) || ''
}

function forwardShowResult(content: string, title: string) {
  emit('showResult', content, title)
}
</script>

<style scoped>
.msg-ai-text {
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
  margin-bottom: 0.5rem;
}

.msg-ai-text :deep(p) { margin: 0.375rem 0; }
.msg-ai-text :deep(p:first-child) { margin-top: 0; }
.msg-ai-text :deep(ul), .msg-ai-text :deep(ol) { margin: 0.375rem 0; padding-left: 1.25rem; }
.msg-ai-text :deep(li) { margin: 0.125rem 0; }
.msg-ai-text :deep(code) {
  background: var(--bg-hover);
  padding: 0.0625rem 0.25rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.msg-ai-text :deep(pre) {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.625rem;
  overflow-x: auto;
  margin: 0.375rem 0;
}
.msg-ai-text :deep(pre code) {
  background: transparent;
  padding: 0;
}

.step-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.25rem;
  overflow: hidden;
  margin: 0.625rem 0;
  box-shadow: var(--shadow-xs);
}

.step-group {
  border-radius: 7px;
}

.tool-overflow-note {
  display: block;
  margin: 0.375rem 0;
  padding: 0.25rem 0.5rem;
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 0.8125rem;
  color: var(--text-dim);
  cursor: pointer;
  text-align: left;
}

.tool-overflow-note:hover {
  color: var(--text-muted);
  text-decoration: underline;
}

.tool-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.625rem 0.875rem;
  cursor: pointer;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font: inherit;
  text-align: left;
  transition: background 0.12s ease, color 0.12s ease;
  min-height: 2.5rem;
  color: inherit;
}

.tool-row:hover {
  background: var(--bg-hover);
}

.tool-row.is-open,
.step-group.is-open > .tool-row--group {
  background: var(--bg-elevated);
}

.tool-row--running {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.tool-row--member {
  padding: 0.5625rem 0.75rem;
}

.tool-row__bullet {
  width: 0.4375rem;
  height: 0.4375rem;
  border-radius: 999px;
  background: var(--text-dim);
  flex-shrink: 0;
}

.tool-row__bullet--running {
  background: var(--accent);
  animation: toolRowPulse 1.4s ease-out infinite;
}

.tool-row__bullet--ok {
  background: var(--ok);
}

.tool-row__bullet--err {
  background: var(--danger);
}

.tool-row__label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text);
  line-height: 1.4;
  flex-shrink: 0;
}

.tool-row__label--member {
  font-size: 0.765625rem;
  color: var(--text-muted);
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row--error .tool-row__label,
.tool-row--error .tool-row__status {
  color: var(--danger);
}

.tool-row__arg {
  min-width: 0;
  flex: 1;
  color: var(--text-dim);
  font-size: 0.8125rem;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row__trailing {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  margin-left: auto;
  color: var(--text-dim);
}

.tool-row__status {
  font-size: 0.8125rem;
  color: var(--text-dim);
  white-space: nowrap;
}

.tool-row__elapsed {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
  white-space: nowrap;
}

.tool-row--running .tool-row__elapsed {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.tool-row__state-icon--ok {
  color: var(--ok);
}

.tool-row__state-icon--err {
  color: var(--danger);
}

.step-count {
  flex-shrink: 0;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
}

.step-group-members {
  margin: 0.125rem 0 0.25rem;
  padding-left: 1.25rem;
}

.step-group-members::before {
  content: '';
  display: block;
  width: calc(100% - 1.25rem);
  height: 1px;
  margin: 0 0 0.125rem 1.25rem;
  background: var(--hairline);
}

.tool-row-body {
  padding: 0 0.875rem 0.5rem;
}

.tool-row-section {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.tool-row-section--error {
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--danger) 30%, var(--border));
}

.tool-row-section__label {
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-dim);
  margin-bottom: 0.25rem;
}

.tool-row-section--error .tool-row-section__label {
  color: var(--danger);
}

.tool-row-section__pre {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
  margin: 0;
}

.step-view-btn {
  margin-top: 0.25rem;
  padding: 0.125rem 0.375rem;
  font-size: 0.6875rem;
  color: var(--accent);
  background: transparent;
  border: none;
  cursor: pointer;
}

.step-view-btn:hover {
  text-decoration: underline;
}

.step-chevron {
  transition: transform 0.12s ease;
}

.tool-row.is-open .step-chevron,
.step-group.is-open > .tool-row--group .step-chevron {
  transform: rotate(90deg);
}

@keyframes toolRowPulse {
  0% { transform: scale(0.85); opacity: 0.6; }
  55% { transform: scale(1.05); opacity: 1; }
  100% { transform: scale(0.85); opacity: 0.65; }
}

@media (prefers-reduced-motion: reduce) {
  .tool-row__bullet--running {
    animation: none;
  }
}
</style>
