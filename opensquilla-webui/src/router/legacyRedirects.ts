import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'
import { parseChannelHash } from '@/composables/setup/useSettingsSection'

// Legacy channel deep links: channel setup moved from the Settings dialog to
// the /channels workspace, and the old `#channel-…` hash contract moved with
// it. This safety net rewrites stale bookmarks; live code mints /channels
// URLs directly.
//
//   /settings/channels#channel-new     → /channels?compose=1
//   /settings/channels#channel-<name>  → /channels?channel=<name>&tab=configuration&edit=1
//
// The bare /settings/channels (no hash) still resolves — it renders the
// jump card into the workspace.
export function legacyChannelHashRedirect(
  to: Pick<RouteLocationNormalized, 'path' | 'hash'>,
): RouteLocationRaw | null {
  if (to.path !== '/settings/channels' || !to.hash) return null
  const target = parseChannelHash(to.hash)
  if (!target) return null
  if (target.kind === 'new') {
    return { path: '/channels', query: { compose: '1' }, replace: true }
  }
  return {
    path: '/channels',
    query: { channel: target.name, tab: 'configuration', edit: '1' },
    replace: true,
  }
}
