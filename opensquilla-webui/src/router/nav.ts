import { getPlatform } from '@/platform'
import type { PlatformId } from '@/platform'
import type { RouteRecordRaw } from 'vue-router'
import type { IconName } from '@/utils/icons'
import i18n from '@/i18n'
import { desktopRoutes } from './desktopRoutes'
import { CONSOLE_GROUP_ORDER, type NavGroup } from './meta'
import { sharedRoutes } from './sharedRoutes'
import { webRoutes } from './webRoutes'

type NavigationSlot = 'primary' | 'bottom'

export interface NavigationItem {
  path: string
  title: string
  icon: IconName
}

export interface NavGroupSection {
  group: NavGroup
  label: string
  items: NavigationItem[]
}

const navRoutes = [
  ...sharedRoutes,
  ...webRoutes,
  ...desktopRoutes,
]

// Operator-facing band labels for the console fold, decoupled from the routing
// `group` key so the wording reads as goals (Manage / Monitor) without renaming
// the taxonomy the routes are keyed on.
const CONSOLE_GROUP_LABELS: Partial<Record<NavGroup, string>> = {
  Operate: 'Manage',
  Observe: 'Monitor',
}

function routePlatforms(platforms: unknown): PlatformId[] {
  if (!Array.isArray(platforms)) return ['web', 'desktop']
  return platforms.filter((item): item is PlatformId => item === 'web' || item === 'desktop')
}

// Localize a nav row title from its route name token (e.g. `nav.sessions`),
// falling back to the English meta.title literal when no key exists. Called
// inside the useNavigation() computeds, so reading the reactive i18n locale here
// makes the rail/drawer/palette re-render on a language switch.
function navTitle(route: RouteRecordRaw): string {
  const name = typeof route.name === 'string' ? route.name : ''
  if (name) {
    const key = `nav.${name}`
    const translated = i18n.global.t(key)
    if (translated !== key) return translated
  }
  return String(route.meta?.title || route.name || route.path)
}

export function getNavigationItems(slot: NavigationSlot): NavigationItem[] {
  const platform = getPlatform()
  return navRoutes
    .filter((route) => route.meta?.nav === slot)
    .filter((route) => routePlatforms(route.meta?.platforms).includes(platform.id))
    .sort((a, b) => Number(a.meta?.navOrder || 0) - Number(b.meta?.navOrder || 0))
    .map((route) => ({
      path: route.path,
      title: navTitle(route),
      icon: (route.meta?.icon || 'home') as IconName,
    }))
}

// Console fold, grouped by meta.group and ordered by CONSOLE_GROUP_ORDER. The
// primary slot is already platform-filtered and navOrder-sorted, so intra-band
// order is correct for free; CONSOLE_GROUP_ORDER excludes Work (the fixed top
// rows), leaving the same Operate-then-Observe row set the fold renders today.
export function getConsoleNavigationSections(): NavGroupSection[] {
  const primary = getNavigationItems('primary')
  const groupOf = new Map(
    navRoutes
      .filter((route) => route.meta?.nav === 'primary')
      .map((route) => [route.path, route.meta?.group ?? 'Operate']),
  )
  return CONSOLE_GROUP_ORDER
    .map((group) => ({
      group,
      label: CONSOLE_GROUP_LABELS[group] ?? group,
      items: primary.filter((item) => groupOf.get(item.path) === group),
    }))
    .filter((section) => section.items.length > 0)
}

// The Work band: the always-visible level-1 destinations that pin to the rail
// (and to the mobile drawer). Same platform-filtered, navOrder-sorted primary
// source as the console fold, so the rail, the drawer, and the command palette
// all read one taxonomy instead of drifting hardcoded lists. Chat is excluded
// because it is the dedicated New-chat action, not a navigation row.
export function getWorkNavigationSection(): NavigationItem[] {
  const groupOf = new Map(
    navRoutes
      .filter((route) => route.meta?.nav === 'primary')
      .map((route) => [route.path, route.meta?.group ?? 'Operate']),
  )
  return getNavigationItems('primary').filter(
    (item) => groupOf.get(item.path) === 'Work' && item.path !== '/chat',
  )
}
