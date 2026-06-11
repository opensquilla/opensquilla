<template>
  <!-- Collapsed outcome row after a decision -->
  <div
    v-if="resolution"
    class="approval-outcome"
    :class="resolution === 'denied' ? 'approval-outcome--denied' : 'approval-outcome--approved'"
    data-testid="approval-outcome"
    role="status"
  >
    <Icon :name="resolution === 'denied' ? 'x' : 'check'" :size="14" />
    <span class="approval-outcome__text">{{ outcomeText }}</span>
    <code v-if="summary" class="approval-outcome__summary" :title="summary">{{ summary }}</code>
  </div>

  <!-- Pending approval card -->
  <article
    v-else
    class="approval-card"
    data-testid="approval-card"
    role="group"
    :aria-label="`Approval required: ${approval.toolName}`"
  >
    <header class="approval-card__head">
      <span class="approval-card__eyebrow">Approval required</span>
      <span class="approval-card__tool">{{ approval.toolName }}</span>
      <span v-if="approval.namespace && approval.namespace !== 'exec'" class="approval-card__ns">
        {{ approval.namespace }}
      </span>
      <span v-if="approval.agent" class="approval-card__agent">{{ approval.agent }}</span>
    </header>

    <div class="approval-card__body">
      <template v-if="approval.command">
        <div class="approval-card__label">Command</div>
        <pre class="approval-card__pre approval-card__pre--cmd">{{ approval.command }}</pre>
      </template>
      <template v-else-if="formattedArgs">
        <div class="approval-card__label">Arguments</div>
        <pre class="approval-card__pre">{{ formattedArgs }}</pre>
      </template>
      <p v-if="approval.warning" class="approval-card__warning">{{ approval.warning }}</p>
    </div>

    <footer class="approval-card__footer">
      <input
        v-model="denyNote"
        class="approval-card__note"
        type="text"
        placeholder="Deny reason (optional) — sent to the agent"
        aria-label="Deny reason, optional, sent to the agent"
        :disabled="busy"
        @keydown.enter.prevent="emitDeny"
      />
      <div class="approval-card__actions">
        <button class="btn btn--primary" type="button" :disabled="busy" @click="$emit('allow-once')">
          Allow once
        </button>
        <button
          v-if="canAllowAlways"
          class="btn btn--ghost"
          type="button"
          :disabled="busy"
          @click="$emit('allow-always')"
        >
          Always allow this
        </button>
        <button
          class="btn approval-card__deny"
          type="button"
          :disabled="busy"
          @click="emitDeny"
        >
          Deny
        </button>
      </div>
      <p v-if="error" class="approval-card__error" role="alert">{{ error }}</p>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ChatApprovalItem, ChatApprovalResolution } from '@/composables/chat/useChatApprovals'

const props = defineProps<{
  approval: ChatApprovalItem
  resolution: ChatApprovalResolution | null
  busy?: boolean
  error?: string
}>()

const emit = defineEmits<{
  'allow-once': []
  'allow-always': []
  deny: [note: string]
}>()

const denyNote = ref('')

const canAllowAlways = computed(() =>
  props.approval.namespace === 'exec' && !!props.approval.command)

const formattedArgs = computed(() => {
  if (!props.approval.args) return ''
  try {
    return JSON.stringify(props.approval.args, null, 2)
  } catch {
    return String(props.approval.args)
  }
})

const outcomeText = computed(() => {
  if (props.resolution === 'denied') return 'Denied'
  if (props.resolution === 'approved_always') return 'Approved · always allowed'
  return 'Approved · run resumed'
})

const summary = computed(() => {
  const text = props.approval.command || props.approval.toolName || ''
  return text.length > 60 ? text.slice(0, 60) + '…' : text
})

function emitDeny() {
  if (props.busy) return
  emit('deny', denyNote.value)
}
</script>

<style scoped>
.approval-card {
  width: min(calc(100% - 48px), 980px);
  margin: var(--sp-2) auto;
  background: var(--bg-surface);
  border: 1px solid color-mix(in srgb, var(--warn) 35%, var(--border));
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* Direct child of the .chat-thread flex column: overflow:hidden drops the
     automatic min-height, so without this the card collapses when the thread
     scrolls. */
  flex-shrink: 0;
}

.approval-card__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4) 0;
}

.approval-card__eyebrow {
  color: var(--warn);
  font-size: var(--fs-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.approval-card__tool {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.approval-card__ns,
.approval-card__agent {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  padding: 1px var(--sp-2);
}

.approval-card__body {
  max-height: 280px;
  overflow: auto;
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.approval-card__label {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.approval-card__pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.5;
  margin: 0;
  padding: var(--sp-3);
  white-space: pre-wrap;
  word-break: break-word;
}

.approval-card__pre--cmd {
  background: color-mix(in srgb, var(--warn) 6%, var(--bg));
}

.approval-card__warning {
  color: var(--warn);
  font-size: var(--fs-sm);
  margin: 0;
}

/* Sticky action bar: the body above scrolls, this footer stays visible. */
.approval-card__footer {
  position: sticky;
  bottom: 0;
  background: var(--bg-surface);
  border-top: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
}

.approval-card__note {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: var(--sp-2) var(--sp-3);
  width: 100%;
}

.approval-card__note:focus-visible {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

.approval-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.approval-card__deny {
  border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
  color: var(--danger);
}

.approval-card__deny:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, var(--bg-surface));
}

.approval-card__error {
  color: var(--danger);
  font-size: var(--fs-sm);
  margin: 0;
}

.approval-outcome {
  width: min(calc(100% - 48px), 980px);
  margin: var(--sp-1) auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  min-width: 0;
}

.approval-outcome--approved {
  color: var(--ok);
}

.approval-outcome--denied {
  color: var(--danger);
}

.approval-outcome__text {
  flex-shrink: 0;
}

.approval-outcome__summary {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 768px) {
  .approval-card__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .approval-card__actions .btn {
    justify-content: center;
  }
}
</style>
