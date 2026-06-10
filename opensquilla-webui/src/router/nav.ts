import { getPlatform } from '@/platform'
import type { PlatformId } from '@/platform'
import type { IconName } from '@/utils/icons'
import { desktopRoutes } from './desktopRoutes'
import { sharedRoutes } from './sharedRoutes'
import { webRoutes } from './webRoutes'

type NavigationSlot = 'primary' | 'bottom'

export interface NavigationItem {
  path: string
  title: string
  icon: IconName
  group: string
}

export interface NavigationGroup {
  label: string
  items: NavigationItem[]
}

const GROUP_ORDER = ['Work', 'Operate', 'Observe', 'Configure']

const navRoutes = [
  ...sharedRoutes,
  ...webRoutes,
  ...desktopRoutes,
]

function routePlatforms(platforms: unknown): PlatformId[] {
  if (!Array.isArray(platforms)) return ['web', 'desktop']
  return platforms.filter((item): item is PlatformId => item === 'web' || item === 'desktop')
}

export function getNavigationItems(slot: NavigationSlot): NavigationItem[] {
  const platform = getPlatform()
  return navRoutes
    .filter((route) => route.meta?.nav === slot)
    .filter((route) => routePlatforms(route.meta?.platforms).includes(platform.id))
    .sort((a, b) => Number(a.meta?.navOrder || 0) - Number(b.meta?.navOrder || 0))
    .map((route) => ({
      path: route.path,
      title: String(route.meta?.title || route.name || route.path),
      icon: (route.meta?.icon || 'home') as IconName,
      group: String(route.meta?.group || 'Work'),
    }))
}

export function getNavigationGroups(): NavigationGroup[] {
  const groups = new Map<string, NavigationGroup>()
  for (const item of getNavigationItems('primary')) {
    const existing = groups.get(item.group)
    if (existing) existing.items.push(item)
    else groups.set(item.group, { label: item.group, items: [item] })
  }
  const orderIndex = (label: string) => {
    const index = GROUP_ORDER.indexOf(label)
    return index === -1 ? GROUP_ORDER.length : index
  }
  return Array.from(groups.values()).sort((a, b) => orderIndex(a.label) - orderIndex(b.label))
}
