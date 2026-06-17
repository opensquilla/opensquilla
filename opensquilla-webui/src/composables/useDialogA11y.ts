import { nextTick, watch, type Ref } from 'vue'
import { useDocumentEvent } from '@/composables/useDocumentEvent'

const FOCUSABLE = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  'summary',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

interface DialogA11yOptions {
  // Element to focus when the dialog opens. Defaults to the first focusable
  // inside the dialog — pass an explicit ref for confirm dialogs so a
  // destructive primary button is not auto-focused.
  initialFocus?: Ref<HTMLElement | null>
}

/**
 * Modal-dialog accessibility for an open/close-driven overlay: traps Tab focus
 * inside `rootRef`, closes on Escape, moves focus into the dialog on open, and
 * restores focus to the invoking element on close. Mirrors the pattern already
 * used by SettingsDialog and SessionInspectDrawer.
 */
export function useDialogA11y(
  rootRef: Ref<HTMLElement | null>,
  isOpen: Ref<boolean>,
  onClose: () => void,
  options: DialogA11yOptions = {},
) {
  let invokerEl: HTMLElement | null = null

  function onKeydown(event: KeyboardEvent) {
    if (!isOpen.value) return
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const root = rootRef.value
    if (!root) return
    const focusables = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const active = document.activeElement as HTMLElement | null
    const inside = !!active && root.contains(active)
    if (event.shiftKey && (!inside || active === first)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (!inside || active === last)) {
      event.preventDefault()
      first.focus()
    }
  }

  useDocumentEvent('keydown', onKeydown)

  watch(isOpen, (open, wasOpen) => {
    if (open && !wasOpen) {
      invokerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
      void nextTick(() => {
        const target = options.initialFocus?.value
          ?? rootRef.value?.querySelector<HTMLElement>(FOCUSABLE)
          ?? null
        target?.focus()
      })
    } else if (!open && wasOpen) {
      if (invokerEl && document.contains(invokerEl)) invokerEl.focus()
      invokerEl = null
    }
  })
}
