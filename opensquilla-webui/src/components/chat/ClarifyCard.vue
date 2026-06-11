<template>
  <!-- Collapsed outcome row after the reply is sent -->
  <div
    v-if="submitted"
    class="clarify-outcome"
    data-testid="clarify-outcome"
    role="status"
  >
    <Icon name="check" :size="14" />
    <span>Reply sent · run resumed</span>
  </div>

  <!-- Pending clarify card -->
  <article
    v-else
    class="clarify-card"
    data-testid="clarify-card"
    role="group"
    aria-label="The agent needs input"
  >
    <header class="clarify-card__head">
      <span class="clarify-card__eyebrow">Input needed</span>
      <p v-if="request.intro" class="clarify-card__intro">{{ request.intro }}</p>
    </header>

    <div class="clarify-card__body">
      <div v-for="field in request.fields" :key="field.name" class="clarify-field">
        <label class="clarify-field__label" :for="fieldId(field.name)">
          <span class="clarify-field__name">{{ field.name }}</span>
          <span v-if="field.prompt && field.prompt !== field.name" class="clarify-field__prompt">
            {{ field.prompt }}
          </span>
          <span class="clarify-field__req">{{ field.required ? 'required' : 'optional' }}</span>
        </label>

        <!-- Enum: numbered choices -->
        <div
          v-if="field.type === 'enum' && field.choices.length"
          class="clarify-field__choices"
          role="radiogroup"
          :aria-label="field.name"
        >
          <button
            v-for="(choice, idx) in field.choices"
            :key="choice"
            type="button"
            class="clarify-choice"
            :class="{ 'is-selected': values[field.name] === choice }"
            role="radio"
            :aria-checked="values[field.name] === choice"
            :disabled="busy"
            @click="values[field.name] = choice"
          >
            <span class="clarify-choice__num">{{ idx + 1 }}</span>
            <span class="clarify-choice__text">{{ choice }}</span>
          </button>
        </div>

        <!-- Bool: explicit true/false select -->
        <select
          v-else-if="field.type === 'bool'"
          :id="fieldId(field.name)"
          v-model="values[field.name]"
          class="clarify-field__input"
          :disabled="busy"
        >
          <option value="">—</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>

        <!-- Default: free text -->
        <input
          v-else
          :id="fieldId(field.name)"
          v-model="values[field.name]"
          class="clarify-field__input"
          type="text"
          :placeholder="field.defaultValue ? `default: ${field.defaultValue}` : ''"
          :disabled="busy"
        />
      </div>
    </div>

    <footer class="clarify-card__footer">
      <div class="clarify-card__actions">
        <button
          class="btn btn--primary"
          type="button"
          :disabled="busy || !canSubmit"
          @click="onSubmit"
        >
          Send reply
        </button>
        <button class="btn btn--ghost" type="button" :disabled="busy" @click="$emit('dismiss')">
          Dismiss
        </button>
      </div>
      <p v-if="error" class="clarify-card__error" role="alert">{{ error }}</p>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ChatClarifyRequest } from '@/composables/chat/useChatApprovals'

const props = defineProps<{
  request: ChatClarifyRequest
  submitted?: boolean
  busy?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [fields: Record<string, string>]
  dismiss: []
}>()

const values = reactive<Record<string, string>>({})

watch(() => props.request, request => {
  for (const key of Object.keys(values)) delete values[key]
  for (const field of request.fields) {
    values[field.name] = field.defaultValue || ''
  }
}, { immediate: true })

const canSubmit = computed(() =>
  props.request.fields.every(field => !field.required || (values[field.name] || '').trim() !== ''))

function fieldId(name: string): string {
  return `clarify-field-${name}`
}

function onSubmit() {
  if (!canSubmit.value || props.busy) return
  const fields: Record<string, string> = {}
  for (const field of props.request.fields) {
    const value = (values[field.name] || '').trim()
    if (value) fields[field.name] = value
  }
  if (Object.keys(fields).length === 0) return
  emit('submit', fields)
}
</script>

<style scoped>
.clarify-card {
  width: min(calc(100% - 48px), 980px);
  margin: var(--sp-2) auto;
  background: var(--bg-surface);
  border: 1px solid color-mix(in srgb, var(--info) 35%, var(--border));
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

.clarify-card__head {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-3) var(--sp-4) 0;
}

.clarify-card__eyebrow {
  color: var(--info);
  font-size: var(--fs-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.clarify-card__intro {
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

.clarify-card__body {
  max-height: 320px;
  overflow: auto;
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.clarify-field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.clarify-field__label {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.clarify-field__name {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
}

.clarify-field__prompt {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.clarify-field__req {
  color: var(--text-dim);
  font-size: var(--fs-xs);
}

.clarify-field__input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: var(--sp-2) var(--sp-3);
  width: 100%;
}

.clarify-field__input:focus-visible {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

.clarify-field__choices {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.clarify-choice {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
  transition: border-color var(--transition), background var(--transition);
}

.clarify-choice:hover:not(:disabled) {
  background: var(--bg-hover);
}

.clarify-choice:focus-visible {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

.clarify-choice.is-selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}

.clarify-choice__num {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.clarify-choice__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Sticky action bar below the scrollable body. */
.clarify-card__footer {
  position: sticky;
  bottom: 0;
  background: var(--bg-surface);
  border-top: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
}

.clarify-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.clarify-card__error {
  color: var(--danger);
  font-size: var(--fs-sm);
  margin: 0;
}

.clarify-outcome {
  width: min(calc(100% - 48px), 980px);
  margin: var(--sp-1) auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--ok);
  font-size: var(--fs-sm);
}

@media (max-width: 768px) {
  .clarify-card__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .clarify-card__actions .btn {
    justify-content: center;
  }
}
</style>
