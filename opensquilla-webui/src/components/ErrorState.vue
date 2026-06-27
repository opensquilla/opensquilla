<template>
  <div class="error-state" role="alert">
    <p class="error-state__message">{{ message }}</p>
    <button
      v-if="onRetry"
      type="button"
      class="error-state__retry btn btn--primary"
      @click="onRetry"
    >
      Retry
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: string
  onRetry?: () => void
}>()
</script>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-6);
  text-align: center;
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  border: 1px solid color-mix(in srgb, var(--danger) 25%, var(--border));
  border-radius: var(--radius-md);
}

.error-state__message {
  font-size: var(--fs-sm);
  font-weight: 500;
  line-height: 1.5;
  margin: 0;
}

.error-state__retry {
  min-width: 80px;
}
</style>
