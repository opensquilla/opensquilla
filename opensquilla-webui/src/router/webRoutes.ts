import type { RouteRecordRaw } from 'vue-router'

const ConfigView = () => import('@/views/web/ConfigView.vue')
const SetupView = () => import('@/views/web/SetupView.vue')

export const webRoutes: RouteRecordRaw[] = [
  { path: '/config', name: 'config', component: ConfigView, meta: { title: 'Config', group: 'Configure', icon: 'config', nav: 'primary', navOrder: 120, platforms: ['web'] } },
  { path: '/setup',  name: 'setup',  component: SetupView,  meta: { title: 'Setup', group: 'Configure', icon: 'config', platforms: ['web'] } },
]
