<template>
  <div v-if="hasError" class="error-boundary">
    <div class="error-boundary__content">
      <h2>{{ t('errorBoundary.title') }}</h2>
      <p class="error-boundary__message">{{ errorMessage || t('errorBoundary.defaultMessage') }}</p>
      <div class="error-boundary__actions">
        <button class="btn btn--primary" @click="reload">{{ t('errorBoundary.reload') }}</button>
        <button class="btn btn--ghost" @click="clearError">{{ t('errorBoundary.dismiss') }}</button>
      </div>
    </div>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'
import { useI18n } from 'vue-i18n'

// useScope:'global' so the outermost error boundary never depends on a scoped
// i18n instance being present when it has to render.
const { t } = useI18n({ useScope: 'global' })

const hasError = ref(false)
const errorMessage = ref('')

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
