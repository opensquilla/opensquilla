import { computed } from 'vue'
import { getNavigationGroups, getNavigationItems } from '@/router/nav'

export function useNavigation() {
  const navGroups = computed(() => getNavigationGroups())
  const bottomRoutes = computed(() => getNavigationItems('bottom'))

  return {
    navGroups,
    bottomRoutes,
  }
}
