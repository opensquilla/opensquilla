import type { RouteRecordRaw } from 'vue-router'

const ConfigView = () => import('@/views/web/ConfigView.vue')
const SetupView = () => import('@/views/web/SetupView.vue')

// Both routes stay valid as deep links but render thin shells that open the
// settings dialog over the default view: /config lands on the default
// section, /setup on the first section that still needs action.
export const webRoutes: RouteRecordRaw[] = [
  { path: '/config', name: 'config', component: ConfigView, meta: { title: 'Settings', group: 'Configure', icon: 'config', platforms: ['web'] } },
  { path: '/setup',  name: 'setup',  component: SetupView,  meta: { title: 'Settings', group: 'Configure', icon: 'config', platforms: ['web'] } },
]
