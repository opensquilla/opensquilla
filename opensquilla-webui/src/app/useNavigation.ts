import { computed } from 'vue'
import { getConsoleNavigationSections, getMoreNavigationSections, getNavigationItems, getWorkNavigationSection } from '@/router/nav'

export function useNavigation() {
  const consoleSections = computed(() => getConsoleNavigationSections())
  const moreSections = computed(() => getMoreNavigationSections())
  const bottomRoutes = computed(() => getNavigationItems('bottom'))
  // The pinned level-1 rail rows (Sessions / Cron / Skills), single-sourced from
  // the route taxonomy so the rail tracks meta.group without a hardcoded list.
  const workNav = computed(() => getWorkNavigationSection())

  return {
    consoleSections,
    moreSections,
    bottomRoutes,
    workNav,
  }
}
