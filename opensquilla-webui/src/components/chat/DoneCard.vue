<template>
  <div class="done-card">
    <button type="button" class="done-card__btn" data-testid="done-continue" @click="onContinue">Continue</button>
    <span class="done-card__sep" aria-hidden="true">&middot;</span>
    <button type="button" class="done-card__btn" data-testid="done-new-task" @click="onNewTask">New task</button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function onContinue() {
  // The composer is owned by the chat view, outside this message subtree;
  // focus it directly so the follow-up lands in the same conversation.
  document.querySelector<HTMLTextAreaElement>('textarea.chat-textarea')?.focus()
}

function onNewTask() {
  void router.push('/chat/new')
}
</script>

<style scoped>
.done-card {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0.375rem 0 0.125rem;
}

.done-card__btn {
  padding: 0.125rem 0.375rem;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  font: inherit;
  font-size: 0.8125rem;
  line-height: 1.5;
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

.done-card__btn:hover {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.done-card__btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

.done-card__sep {
  color: var(--text-dim);
  font-size: 0.8125rem;
}

@media (max-width: 768px) {
  .done-card__btn {
    min-height: 2.75rem;
    padding: 0.375rem 0.625rem;
  }
}
</style>
