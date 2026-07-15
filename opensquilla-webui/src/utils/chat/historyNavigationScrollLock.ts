import type { Ref } from 'vue'

/**
 * Keeps live-edge following disabled while a minimap-triggered smooth scroll is
 * crossing the bottom threshold. Intermediate scroll frames must not be
 * mistaken for the reader returning to the live edge.
 */
export function createHistoryNavigationScrollLock(autoScroll: Ref<boolean>) {
  let locked = false

  return {
    start() {
      locked = true
      autoScroll.value = false
    },
    finish() {
      locked = false
    },
    updateFromScroll(bottomGap: number) {
      if (!locked) autoScroll.value = bottomGap < 60
    },
    get locked() {
      return locked
    },
  }
}
