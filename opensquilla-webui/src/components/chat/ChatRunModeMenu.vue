<template>
  <div class="composer-run-mode" ref="rootEl">
    <button
      type="button"
      class="btn btn--icon btn--ghost composer-run-mode__trigger"
      :class="{ 'is-danger': normalizedRunMode === 'full' }"
      :title="`Run Mode: ${activeLabel}`"
      aria-label="Run Mode"
      :aria-expanded="open ? 'true' : 'false'"
      @click="open = !open"
    >
      <Icon name="shield" :size="17" />
    </button>

    <section v-if="open" class="composer-run-mode__menu" role="dialog" aria-label="Run Mode">
      <div class="composer-run-mode__head">
        <span class="composer-run-mode__title">
          <Icon name="shield" :size="14" />
          <span>Run Mode</span>
        </span>
        <span class="composer-run-mode__badge">{{ activeLabel }}</span>
        <button type="button" class="composer-run-mode__close" aria-label="Close Run Mode" @click="open = false">
          <Icon name="x" :size="14" />
        </button>
      </div>

      <div class="composer-run-mode__options" role="listbox" aria-label="Run Mode">
        <button
          v-for="option in runModeOptions"
          :key="option.value"
          type="button"
          class="composer-run-mode__option"
          :class="{ 'is-active': normalizedRunMode === option.value, 'is-danger': option.value === 'full' && normalizedRunMode === option.value }"
          role="option"
          :aria-selected="normalizedRunMode === option.value ? 'true' : 'false'"
          @click="selectMode(option.value)"
        >
          <span class="composer-run-mode__option-mark" aria-hidden="true">
            <Icon v-if="normalizedRunMode === option.value" name="check" :size="13" />
          </span>
          <span class="composer-run-mode__option-copy">
            <span>{{ option.label }}</span>
            <small>{{ option.caption }}</small>
          </span>
        </button>
      </div>

      <div v-if="sandboxSetupVisible" class="composer-run-mode__setup" role="status">
        <p>{{ sandboxSetupMessage || 'Limit tool access before switching to sandbox modes.' }}</p>
        <div class="composer-run-mode__setup-actions">
          <button type="button" class="btn btn--ghost btn--sm" @click="$emit('dismissSandboxSetup')">Not now</button>
          <button type="button" class="btn btn--primary btn--sm" :disabled="sandboxSetupBusy" @click="$emit('ensureSandboxSetup')">
            {{ sandboxSetupBusy ? 'Establishing...' : 'Establish sandbox' }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { RunMode } from '@/types/rpc'
import { useDocumentEvent } from '@/composables/useDocumentEvent'

const runModeOptions: Array<{ value: RunMode; label: string; caption: string }> = [
  { value: 'standard', label: 'Standard-Sandbox', caption: 'Ask before risky actions' },
  { value: 'trusted', label: 'Trusted-Sandbox', caption: 'Managed sandbox' },
  { value: 'full', label: 'Full Host Access', caption: 'Direct host access' },
]

const props = defineProps<{
  runMode: RunMode
  sandboxSetupBusy: boolean
  sandboxSetupMessage: string
  sandboxSetupVisible: boolean
}>()

const emit = defineEmits<{
  dismissSandboxSetup: []
  ensureSandboxSetup: []
  setRunMode: [mode: RunMode]
}>()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)

const normalizedRunMode = computed<RunMode>(() => {
  return runModeOptions.some(option => option.value === props.runMode) ? props.runMode : 'full'
})

const activeLabel = computed(() => {
  return runModeOptions.find(option => option.value === normalizedRunMode.value)?.label || 'Full Host Access'
})

function selectMode(mode: RunMode) {
  open.value = false
  emit('setRunMode', mode)
}

useDocumentEvent('mousedown', (event: MouseEvent) => {
  if (!open.value) return
  if (rootEl.value?.contains(event.target as Node)) return
  open.value = false
}, { capture: true })

useDocumentEvent('keydown', (event: KeyboardEvent) => {
  if (!open.value || event.key !== 'Escape') return
  event.stopPropagation()
  open.value = false
})
</script>

<style scoped>
.composer-run-mode {
  position: relative;
  display: inline-flex;
}

.composer-run-mode__trigger.is-danger {
  color: var(--warn);
}

.composer-run-mode__trigger[aria-expanded='true'] {
  background: var(--bg-hover);
  color: var(--text);
}

.composer-run-mode__menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  width: min(312px, calc(100vw - 48px));
  padding: 0.5rem;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-xl);
  z-index: 30;
}

.composer-run-mode__head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.5rem;
  min-height: 30px;
  margin-bottom: 0.25rem;
  padding: 0 0.125rem 0 0.25rem;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--text);
}

.composer-run-mode__title {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}

.composer-run-mode__badge {
  max-width: 132px;
  margin-left: auto;
  padding: 0.125rem 0.375rem;
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 0.6875rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-run-mode__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.composer-run-mode__close:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.composer-run-mode__options {
  display: grid;
  gap: 0.125rem;
  padding: 0.25rem 0;
  border-top: 1px solid var(--border);
}

.composer-run-mode__option {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  min-height: 42px;
  padding: 0.375rem 0.5rem;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.composer-run-mode__option:hover {
  background: var(--bg-hover);
}

.composer-run-mode__option.is-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.composer-run-mode__option.is-danger {
  background: color-mix(in srgb, var(--warn) 11%, transparent);
}

.composer-run-mode__option-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  border-radius: 999px;
  color: var(--accent);
}

.composer-run-mode__option-copy {
  display: grid;
  gap: 0.0625rem;
  min-width: 0;
}

.composer-run-mode__option-copy > span {
  font-size: 0.8125rem;
  font-weight: 700;
}

.composer-run-mode__option-copy > small {
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.35;
}

.composer-run-mode__setup {
  display: grid;
  gap: 0.5rem;
  margin-top: 0.25rem;
  padding: 0.625rem;
  border-top: 1px solid var(--border);
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}

.composer-run-mode__setup p {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.4;
}

.composer-run-mode__setup-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>
