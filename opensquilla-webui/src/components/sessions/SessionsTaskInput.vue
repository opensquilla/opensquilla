<template>
  <form class="hub-task" @submit.prevent="submit">
    <textarea
      ref="textareaRef"
      v-model="text"
      class="hub-task__input"
      rows="2"
      :placeholder="t('sessions.taskInput.placeholder')"
      :aria-label="t('sessions.taskInput.ariaLabel')"
      @keydown.enter.exact.prevent="submit"
    ></textarea>
    <div class="hub-task__bar">
      <span v-show="text.trim()" class="hub-task__hint">{{ t('sessions.taskInput.hint') }}</span>
      <button
        type="submit"
        class="btn btn--primary hub-task__send"
        :disabled="!text.trim()"
      >
        <Icon name="arrowUp" :size="16" />
        <span>{{ t('sessions.taskInput.start') }}</span>
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()

const emit = defineEmits<{
  submit: [text: string]
}>()

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function submit() {
  const value = text.value.trim()
  if (!value) return
  emit('submit', value)
  text.value = ''
}
</script>

<style scoped>
.hub-task {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-4);
  transition: border-color var(--transition), box-shadow var(--transition);
}

.hub-task:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

.hub-task__input {
  background: transparent;
  border: none;
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--fs-md);
  line-height: 1.5;
  outline: none;
  resize: none;
  width: 100%;
}

.hub-task__input::placeholder {
  color: var(--text-dim);
}

.hub-task__bar {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.hub-task__hint {
  color: var(--text-dim);
  font-size: var(--fs-xs);
}

.hub-task__send {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}

.hub-task__send:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 760px) {
  .hub-task__hint {
    display: none;
  }
}
</style>
