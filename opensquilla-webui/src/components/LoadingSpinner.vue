<template>
  <span class="loading-spinner" :aria-label="t('shared.loading')" role="status"></span>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// Pure presentational spinner; i18n only supplies the screen-reader label.
const { t } = useI18n()
</script>

<style scoped>
.loading-spinner {
  display: inline-block;
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner {
    animation-duration: 1.6s;
  }
}
</style>
