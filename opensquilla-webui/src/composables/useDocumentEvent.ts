import { onMounted, onUnmounted } from 'vue'

export function useDocumentEvent<K extends keyof DocumentEventMap>(
  event: K,
  handler: (event: DocumentEventMap[K]) => void,
  options?: boolean | AddEventListenerOptions
) {
  onMounted(() => {
    document.addEventListener(event, handler, options)
  })

  onUnmounted(() => {
    document.removeEventListener(event, handler, options)
  })
}
