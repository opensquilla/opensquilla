import type { RouteRecordRaw } from 'vue-router'

const SettingsView = () => import('@/views/web/SettingsView.vue')

// Web Settings is a deep-linkable overlay route that renders the settings
// dialog over the default view. `/settings/:section` selects a rail section;
// the legacy `/config` and `/setup` deep links redirect into it (`/setup` lands
// on the first not-ready section via the `auto` sentinel param).
//
// This route set is registered ONLY on the web platform (router/index.ts gates
// it behind capabilities.hasWebConfig), so it never collides with the desktop
// platform's own `/settings` → DesktopSettingsView.
export const webRoutes: RouteRecordRaw[] = [
  { path: '/settings', name: 'settings', component: SettingsView, meta: { title: 'Settings', icon: 'settings', platforms: ['web'] } },
  { path: '/settings/:section', name: 'settings-section', component: SettingsView, meta: { title: 'Settings', icon: 'settings', platforms: ['web'] } },
  { path: '/config', redirect: '/settings' },
  { path: '/setup',  redirect: '/settings/auto' },
]
