import type { RouteRecordRaw } from 'vue-router'

const DesktopSettingsView = () => import('@/views/desktop/DesktopSettingsView.vue')

export const desktopRoutes: RouteRecordRaw[] = [
  { path: '/settings', name: 'settings', component: DesktopSettingsView, meta: { title: 'Settings', group: 'Settings', icon: 'settings', nav: 'bottom', navOrder: 10, platforms: ['desktop'] } },
]
