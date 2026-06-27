import { reactive } from 'vue'

/**
 * Self-contained open-state for the non-chat run-trace surfaces. Chat owns its
 * own toggle store (useChatToolToggles via ChatView); SessionInspect and Logs
 * have none, so this supplies two reactive sets plus the exact
 * isToolGroupOpen / isToolItemOpen predicate + toggle contract `<RunTrace>`
 * binds, so the same component props work on every surface.
 */
export function useRunTrace() {
  const openGroups = reactive(new Set<string>())
  const openItems = reactive(new Set<string>())
  return {
    isToolGroupOpen: (id: string) => openGroups.has(id),
    isToolItemOpen: (key: string) => openItems.has(key),
    toggleGroup: (id: string) => {
      openGroups.has(id) ? openGroups.delete(id) : openGroups.add(id)
    },
    toggleItem: (key: string) => {
      openItems.has(key) ? openItems.delete(key) : openItems.add(key)
    },
  }
}
