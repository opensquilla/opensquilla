<template>
  <div v-if="appStore.settingsOpen" class="settings-overlay" @click.self="requestClose()">
    <section
      ref="modalRef"
      class="settings-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <header class="settings-modal__head">
        <h2 id="settings-modal-title" class="settings-modal__title">Settings</h2>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          aria-label="Close"
          title="Close"
          @click="requestClose()"
        >
          <Icon name="x" :size="16" />
        </button>
      </header>
      <div class="settings-modal__body">
        <ConfigPanel ref="panelRef" @open-setup="onOpenSetup" />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import Icon from '@/components/Icon.vue'
import ConfigPanel from './ConfigPanel.vue'

const appStore = useAppStore()
const router = useRouter()

const modalRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const panelRef = ref<InstanceType<typeof ConfigPanel> | null>(null)

let invokerEl: HTMLElement | null = null

// Closes unless the form carries unsaved edits and the user keeps them.
function requestClose(): boolean {
  if (panelRef.value?.hasUnsavedChanges && !confirm('Discard unsaved changes?')) {
    return false
  }
  appStore.setSettingsOpen(false)
  return true
}

function onOpenSetup() {
  if (requestClose()) router.push('/setup')
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (!appStore.settingsOpen) return
  if (event.key === 'Escape') {
    event.preventDefault()
    requestClose()
    return
  }
  if (event.key !== 'Tab') return
  const rootEl = modalRef.value
  if (!rootEl) return
  const focusables = Array.from(rootEl.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'))
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement as HTMLElement | null
  const inside = !!active && rootEl.contains(active)
  if (event.shiftKey && (!inside || active === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => appStore.settingsOpen,
  (open, wasOpen) => {
    if (open && !wasOpen) {
      invokerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', onDocumentKeydown)
      nextTick(() => closeBtn.value?.focus())
    } else if (wasOpen && !open) {
      document.removeEventListener('keydown', onDocumentKeydown)
      if (invokerEl && document.contains(invokerEl)) invokerEl.focus()
      invokerEl = null
    }
  },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<style scoped>
.settings-overlay {
  align-items: center;
  background: var(--scrim);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: var(--sp-6);
  position: fixed;
  z-index: 300;
}

.settings-modal {
  animation: settingsIn 0.18s ease;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  height: min(85vh, 100%);
  overflow: hidden;
  width: min(1200px, 100%);
}

@keyframes settingsIn {
  from { transform: translateY(12px); opacity: 0.4; }
  to { transform: translateY(0); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .settings-modal {
    animation: none;
  }
}

.settings-modal__head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-shrink: 0;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}

.settings-modal__title {
  flex: 1;
  font-size: var(--fs-lg);
  font-weight: 700;
  margin: 0;
}

.settings-modal__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

@media (max-width: 768px) {
  .settings-overlay {
    padding: 0;
  }

  .settings-modal {
    border: none;
    border-radius: 0;
    height: 100%;
    width: 100%;
  }
}
</style>
