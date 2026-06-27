<template>
  <div ref="rootEl" class="msg-ai-text" v-html="part.html" />
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { ChatPart, SourcePart } from '@/types/parts'
import { decorateCitations } from '@/utils/chat/citations'

const props = withDefaults(
  defineProps<{
    part: Extract<ChatPart, { type: 'text' }>
    sources?: SourcePart[]
  }>(),
  { sources: () => [] },
)

const emit = defineEmits<{ citation: [sourceId: number] }>()

const rootEl = ref<HTMLDivElement | null>(null)

function labelFor(sourceId: number): string {
  const source = props.sources[sourceId - 1]
  return source ? source.title || source.domain : ''
}

// After `v-html` has applied the sanitized body, upgrade any `[n]` that maps to
// a real source into a focusable citation pill. The pass works on already-clean
// text nodes only (createElement/textContent — never innerHTML), so it adds no
// HTML sink and re-runs idempotently when the body re-renders during streaming.
function decorate() {
  const root = rootEl.value
  if (!root) return
  decorateCitations(root, props.sources, {
    onActivate: n => emit('citation', n),
    labelFor,
  })
}

onMounted(decorate)
watch(() => props.part.html, decorate, { flush: 'post' })
watch(() => props.sources, decorate, { flush: 'post' })
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

/* Citation pills are injected outside Vue's template (built by decorateCitations
   with createElement), so the scoped data-v hash never lands on them — target
   them through :deep, the same mechanism the markdown elements above use. */
.msg-ai-text :deep(.citation-pill) {
  display: inline-flex;
  align-items: center;
  padding: 0 0.25rem;
  margin: 0 0.0625rem;
  font: inherit;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  line-height: 1.2;
  vertical-align: baseline;
  color: var(--text-muted);
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: color var(--transition), background var(--transition), border-color var(--transition);
}

.msg-ai-text :deep(.citation-pill:hover) {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong));
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-hover));
}

.msg-ai-text :deep(.citation-pill:focus-visible) {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

@media (prefers-reduced-motion: reduce) {
  .msg-ai-text :deep(.citation-pill) {
    transition: none;
  }
}
</style>
