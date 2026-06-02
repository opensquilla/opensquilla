<template>
  <div v-if="hasError" class="error-boundary">
    <div class="error-boundary__content">
      <h2>Something went wrong</h2>
      <p class="error-boundary__message">{{ errorMessage }}</p>
      <div class="error-boundary__actions">
        <button class="btn btn--primary" @click="reload">Reload page</button>
        <button class="btn btn--ghost" @click="clearError">Dismiss</button>
      </div>
    </div>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const hasError = ref(false)
const errorMessage = ref('An unexpected error occurred.')

onErrorCaptured((err: unknown) => {
  hasError.value = true
  errorMessage.value = err instanceof Error ? err.message : String(err)
  console.error('[ErrorBoundary]', err)
  return false // Prevent error from propagating
})

function reload() {
  window.location.reload()
}

function clearError() {
  hasError.value = false
  errorMessage.value = ''
}
</script>

<style scoped>
.error-boundary {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  padding: 2rem;
}

.error-boundary__content {
  text-align: center;
  max-width: 480px;
}

.error-boundary__content h2 {
  margin-bottom: 0.75rem;
  color: var(--text);
}

.error-boundary__message {
  color: var(--text-muted);
  margin-bottom: 1.5rem;
  font-size: var(--fs-sm);
  word-break: break-word;
}

.error-boundary__actions {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
}
</style>
