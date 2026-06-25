import { computed } from 'vue'
import { getConsoleNavigationItems, getNavigationItems } from '@/router/nav'

export function useNavigation() {
  const consoleRoutes = computed(() => getConsoleNavigationItems())
  const bottomRoutes = computed(() => getNavigationItems('bottom'))

  return {
    consoleRoutes,
    bottomRoutes,
  }
}
