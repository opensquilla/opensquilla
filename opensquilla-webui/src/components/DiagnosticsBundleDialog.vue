<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-overlay" @click="emit('close')">
        <div
          ref="modalRef"
          class="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="diagnostics-bundle-title"
          @click.stop
        >
          <h3 id="diagnostics-bundle-title" class="modal__title">
            {{ t('usageLogs.logs.bundleTitle') }}
          </h3>
          <div class="modal__body">
            <p>{{ t('usageLogs.logs.bundleBody') }}</p>
            <label class="bundle-dialog__option">
              <input v-model="includeContent" type="checkbox" />
              <span>{{ t('usageLogs.logs.bundleIncludeContent') }}</span>
            </label>
          </div>
          <div class="modal__footer">
            <button class="btn btn--primary" @click="emit('confirm', { includeContent })">
              {{ t('usageLogs.logs.bundleConfirm') }}
            </button>
            <button ref="cancelBtn" class="btn btn--ghost" @click="emit('close')">
              {{ t('usageLogs.logs.bundleCancel') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDialogA11y } from '@/composables/useDialogA11y'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (event: 'close'): void
  (event: 'confirm', payload: { includeContent: boolean }): void
}>()

const { t } = useI18n()
const includeContent = ref(false)
const modalRef = ref<HTMLElement | null>(null)
const cancelBtn = ref<HTMLElement | null>(null)
const isOpen = computed(() => props.open)

// Privacy-sensitive opt-in: re-arm to unchecked every time the dialog opens so
// an earlier opt-in never silently carries over to the next download.
watch(isOpen, (open) => {
  if (open) includeContent.value = false
})

// Cancel is the initial focus target so the primary action is never
// auto-focused; Escape and Tab-trapping come from the shared a11y helper.
useDialogA11y(modalRef, isOpen, () => emit('close'), { initialFocus: cancelBtn })
</script>

<style scoped>
/* ConfirmModal's overlay/dialog skeleton is scoped to that component, so the
   same token-based block is repeated here rather than reaching into it. */
.modal-overlay {
  align-items: center;
  background: var(--scrim);
  bottom: 0;
  display: flex;
  justify-content: center;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1100;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-modal);
  max-width: 420px;
  padding: var(--sp-5);
  width: 90%;
}

.modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.modal__body {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin-bottom: var(--sp-4);
}

.modal__body p {
  margin: 0;
}

.modal__footer {
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
}

.bundle-dialog__option {
  align-items: center;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}

.bundle-dialog__option input {
  flex-shrink: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--dur-base);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
