import type { RouteRecordRaw } from 'vue-router'

const ConfigView = () => import('@/views/web/ConfigView.vue')
const SetupView = () => import('@/views/web/SetupView.vue')

export const webRoutes: RouteRecordRaw[] = [
  { path: '/config', name: 'config', component: ConfigView, meta: { title: 'Config', group: 'Settings', icon: 'config', nav: 'bottom', navOrder: 10, platforms: ['web'] } },
  { path: '/setup',  name: 'setup',  component: SetupView,  meta: { title: 'Setup', group: 'Settings', icon: 'config', platforms: ['web'] } },
]
