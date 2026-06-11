import type { RouteRecordRaw } from 'vue-router'

const ConfigView = () => import('@/views/web/ConfigView.vue')
const SetupView = () => import('@/views/web/SetupView.vue')

export const webRoutes: RouteRecordRaw[] = [
  // /config stays valid as a deep link, but ConfigView is now a thin shell:
  // it opens the settings modal over the default view and renders no page.
  { path: '/config', name: 'config', component: ConfigView, meta: { title: 'Settings', group: 'Configure', icon: 'config', platforms: ['web'] } },
  { path: '/setup',  name: 'setup',  component: SetupView,  meta: { title: 'Setup', group: 'Configure', icon: 'config', platforms: ['web'] } },
]
