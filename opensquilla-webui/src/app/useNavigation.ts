import { computed } from 'vue'
import { getNavigationItems } from '@/router/nav'

export function useNavigation() {
  const quickRoutes = computed(() => getNavigationItems('primary'))
  const bottomRoutes = computed(() => getNavigationItems('bottom'))

  return {
    quickRoutes,
    bottomRoutes,
  }
}
