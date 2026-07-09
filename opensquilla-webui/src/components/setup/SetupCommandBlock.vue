<template>
  <div class="setup-command-block">
    <span v-if="label" class="setup-cli__label">{{ label }}</span>
    <code>{{ formattedCommand }}</code>
    <button
      class="setup-cli__copy"
      type="button"
      :title="copyTitle"
      :aria-label="copyTitle"
      @click="emit('copy', formattedCommand)"
    >
      <Icon name="copy" :size="14" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useCliInvocation } from '@/composables/useCliInvocation'

const props = defineProps<{
  command: string
  label?: string
  copyLabel?: string
}>()

const emit = defineEmits<{
  copy: [command: string]
}>()

// On the desktop shell `opensquilla …` commands are rewritten to the bundled
// CLI invocation so pasting them actually works; identity everywhere else.
const { format } = useCliInvocation()
const formattedCommand = computed(() => format(props.command))

const copyTitle = computed(() => props.copyLabel || (props.label ? `Copy ${props.label} command` : 'Copy command'))
</script>

<style scoped>
.setup-command-block {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  min-width: 0;
}

.setup-command-block code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  flex: 1;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  min-width: 0;
  overflow-x: auto;
  padding: var(--sp-2) var(--sp-3);
  white-space: nowrap;
}

.setup-cli__label {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  min-width: 7rem;
}

.setup-cli__copy {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 2rem;
  justify-content: center;
  width: 2rem;
}

.setup-cli__copy:hover {
  border-color: var(--accent);
  color: var(--accent);
}
</style>
