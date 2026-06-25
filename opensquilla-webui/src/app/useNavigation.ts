import { computed } from 'vue'
import { getConsoleNavigationSections, getNavigationItems, getWorkNavigationSection } from '@/router/nav'

export function useNavigation() {
  const consoleSections = computed(() => getConsoleNavigationSections())
  const bottomRoutes = computed(() => getNavigationItems('bottom'))
  // The pinned level-1 rail rows (Sessions / Cron / Skills), single-sourced from
  // the route taxonomy so the rail tracks meta.group without a hardcoded list.
  const workNav = computed(() => getWorkNavigationSection())

  return {
    consoleSections,
    bottomRoutes,
    workNav,
  }
}
