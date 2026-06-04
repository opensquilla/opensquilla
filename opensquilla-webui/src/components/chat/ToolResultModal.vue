<template>
  <div v-if="open" class="tool-modal-overlay" @click.self="$emit('close')">
    <div class="tool-modal">
      <div class="tool-modal__header">
        <h3 class="tool-modal__title">{{ title }}</h3>
        <button class="btn btn--icon btn--ghost" title="Close" aria-label="Close" @click="$emit('close')">
          <Icon name="x" :size="16" />
        </button>
      </div>
      <pre class="tool-modal__body">{{ content }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'

defineProps<{
  open: boolean
  title: string
  content: string
}>()

defineEmits<{
  close: []
}>()
</script>

<style scoped>
.tool-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
}

.tool-modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 100%;
  max-width: 720px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.tool-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
}

.tool-modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
  color: var(--text);
}

.tool-modal__body {
  flex: 1;
  padding: var(--sp-4);
  margin: 0;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg-primary);
  color: var(--text);
}
</style>
