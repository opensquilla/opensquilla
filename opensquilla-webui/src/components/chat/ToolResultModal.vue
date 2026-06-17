<template>
  <div v-if="open" class="tool-sheet-overlay" @click.self="$emit('close')">
    <aside class="tool-sheet" role="dialog" aria-modal="true" :aria-label="title">
      <div class="tool-sheet__header">
        <h3 class="tool-sheet__title">{{ title }}</h3>
        <div class="tool-sheet__actions">
          <button
            v-if="treeHtml"
            type="button"
            class="btn btn--ghost tool-sheet__mode"
            @click="rawMode = !rawMode"
          >
            {{ rawMode ? 'Tree' : 'Raw' }}
          </button>
          <button ref="closeBtn" class="btn btn--icon btn--ghost" title="Close" aria-label="Close" @click="$emit('close')">
            <Icon name="x" :size="16" />
          </button>
        </div>
      </div>
      <div class="tool-sheet__body">
        <div v-if="treeHtml && !rawMode" class="tool-sheet__tree" v-html="treeHtml" />
        <pre v-else class="tool-sheet__pre">{{ content }}</pre>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'

const props = defineProps<{
  open: boolean
  title: string
  content: string
}>()

const emit = defineEmits<{
  close: []
}>()

const rawMode = ref(false)
const closeBtn = ref<HTMLButtonElement | null>(null)

// Guardrails: very large payloads fall back to plain text, long string leaves
// are clipped, and the tree stops after a node budget.
const MAX_TREE_SOURCE_CHARS = 300000
const MAX_LEAF_STRING_CHARS = 2000
const MAX_TREE_NODES = 4000
const AUTO_OPEN_DEPTH = 2

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch] as string
  ))
}

function leafHtml(value: unknown): string {
  if (typeof value === 'string') {
    const shown = value.length > MAX_LEAF_STRING_CHARS
      ? `${value.slice(0, MAX_LEAF_STRING_CHARS)}… (${value.length} chars)`
      : value
    return `<span class="jt-string">"${escapeHtml(shown)}"</span>`
  }
  if (value === null) return '<span class="jt-null">null</span>'
  return `<span class="jt-${typeof value}">${escapeHtml(String(value))}</span>`
}

function nodeHtml(value: unknown, key: string, depth: number, budget: { left: number }): string {
  if (budget.left-- <= 0) return ''
  const keyHtml = key === '' ? '' : `<span class="jt-key">${escapeHtml(key)}</span><span class="jt-colon">: </span>`
  if (value === null || typeof value !== 'object') {
    return `<div class="jt-row">${keyHtml}${leafHtml(value)}</div>`
  }
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>)
  if (entries.length === 0) {
    return `<div class="jt-row">${keyHtml}<span class="jt-badge">${Array.isArray(value) ? '[]' : '{}'}</span></div>`
  }
  const badge = Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`
  const children = entries.map(([childKey, childValue]) => nodeHtml(childValue, childKey, depth + 1, budget)).join('')
  const truncated = budget.left <= 0 ? '<div class="jt-row jt-truncated">…</div>' : ''
  const openAttr = depth < AUTO_OPEN_DEPTH ? ' open' : ''
  return `<details class="jt-node"${openAttr}><summary class="jt-summary">${keyHtml}<span class="jt-badge">${badge}</span></summary><div class="jt-children">${children}${truncated}</div></details>`
}

// Pre-rendered, fully escaped fold tree; empty string means "not JSON".
const treeHtml = computed(() => {
  const text = (props.content || '').trim()
  if (!text || text.length > MAX_TREE_SOURCE_CHARS) return ''
  if (!/^[[{]/.test(text)) return ''
  try {
    const parsed: unknown = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object') return ''
    return nodeHtml(parsed, '', 0, { left: MAX_TREE_NODES })
  } catch {
    return ''
  }
})

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) {
    event.preventDefault()
    emit('close')
  }
}

watch(() => props.open, open => {
  if (open) {
    rawMode.value = false
    document.addEventListener('keydown', onDocumentKeydown)
    nextTick(() => closeBtn.value?.focus())
  } else {
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<style scoped>
.tool-sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: var(--scrim);
  display: flex;
  justify-content: flex-end;
}

.tool-sheet {
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  width: min(560px, 100%);
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
  animation: toolSheetIn 0.18s ease;
}

@keyframes toolSheetIn {
  from { transform: translateX(24px); opacity: 0.4; }
  to { transform: translateX(0); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .tool-sheet {
    animation: none;
  }
}

.tool-sheet__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
}

.tool-sheet__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
  color: var(--text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-sheet__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}

.tool-sheet__mode {
  font-size: var(--fs-xs);
}

.tool-sheet__body {
  flex: 1;
  overflow-y: auto;
  background: var(--bg);
}

.tool-sheet__pre {
  padding: var(--sp-4);
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
}

.tool-sheet__tree {
  padding: var(--sp-4);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
}

.tool-sheet__tree :deep(.jt-node) {
  margin: 0;
}

.tool-sheet__tree :deep(.jt-summary) {
  cursor: pointer;
  list-style-position: outside;
  color: var(--text-muted);
}

.tool-sheet__tree :deep(.jt-summary:hover) {
  color: var(--text);
}

.tool-sheet__tree :deep(.jt-children) {
  margin-left: var(--sp-4);
  border-left: 1px solid var(--hairline);
  padding-left: var(--sp-2);
}

.tool-sheet__tree :deep(.jt-key) {
  color: var(--accent-secondary);
}

.tool-sheet__tree :deep(.jt-string) {
  color: var(--text);
}

.tool-sheet__tree :deep(.jt-number),
.tool-sheet__tree :deep(.jt-boolean) {
  color: var(--info);
}

.tool-sheet__tree :deep(.jt-null) {
  color: var(--text-dim);
}

.tool-sheet__tree :deep(.jt-badge) {
  color: var(--text-dim);
  font-size: var(--fs-xs);
}

.tool-sheet__tree :deep(.jt-truncated) {
  color: var(--text-dim);
}
</style>
