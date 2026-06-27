import { computed, onBeforeUnmount, ref } from 'vue'
import type { IconName } from '@/utils/icons'

const COPY_FEEDBACK_RESET_MS = 1200

export function useCopyFeedback(copy: () => Promise<boolean>) {
  const copyState = ref<'ok' | 'err' | null>(null)
  let resetTimer: ReturnType<typeof setTimeout> | null = null

  async function onCopyClick() {
    const ok = await copy()
    copyState.value = ok ? 'ok' : 'err'
    if (resetTimer) clearTimeout(resetTimer)
    resetTimer = setTimeout(() => {
      copyState.value = null
    }, COPY_FEEDBACK_RESET_MS)
  }

  onBeforeUnmount(() => {
    if (resetTimer) clearTimeout(resetTimer)
  })

  const copyIconName = computed<IconName>(() =>
    copyState.value === 'ok' ? 'check' : copyState.value === 'err' ? 'x' : 'copy',
  )
  const copyTitle = computed(() =>
    copyState.value === 'ok' ? 'Copied' : copyState.value === 'err' ? 'Copy failed' : 'Copy',
  )
  const copyLiveText = computed(() =>
    copyState.value === 'ok' ? 'Copied' : copyState.value === 'err' ? 'Copy failed' : '',
  )

  return { copyState, copyIconName, copyTitle, copyLiveText, onCopyClick }
}
