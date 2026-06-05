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
}

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
    }))
}
