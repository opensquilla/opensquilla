import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// Views
const OverviewView = () => import('@/views/OverviewView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const CronView = () => import('@/views/CronView.vue')
const SetupView = () => import('@/views/SetupView.vue')
const AgentsView = () => import('@/views/AgentsView.vue')
const ApprovalsView = () => import('@/views/ApprovalsView.vue')
const HealthView = () => import('@/views/HealthView.vue')
const ChannelsView = () => import('@/views/ChannelsView.vue')
const LogsView = () => import('@/views/LogsView.vue')
const ConfigView = () => import('@/views/ConfigView.vue')
const SessionsView = () => import('@/views/SessionsView.vue')
const UsageView = () => import('@/views/UsageView.vue')
const SkillsView = () => import('@/views/SkillsView.vue')

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: () => {
      const isMobile = window.matchMedia('(max-width: 768px)').matches
      return isMobile ? '/chat' : '/overview'
    },
  },
  { path: '/overview',  name: 'overview',  component: OverviewView,    meta: { title: 'Overview', group: 'Control', icon: 'home' } },
  { path: '/health',    name: 'health',    component: HealthView,      meta: { title: 'Health', group: 'Control', icon: 'logs' } },
  { path: '/chat',      name: 'chat',      component: ChatView,      meta: { title: 'Chat', group: 'Chat', icon: 'chat' } },
  { path: '/sessions',  name: 'sessions',  component: SessionsView,  meta: { title: 'Sessions', group: 'Control', icon: 'sessions' } },
  { path: '/agents',    name: 'agents',    component: AgentsView,    meta: { title: 'Agents', group: 'Control', icon: 'agents' } },
  { path: '/cron',      name: 'cron',      component: CronView,      meta: { title: 'Cron', group: 'Control', icon: 'cron' } },
  { path: '/usage',     name: 'usage',     component: UsageView,       meta: { title: 'Usage', group: 'Control', icon: 'usage' } },
  { path: '/config',    name: 'config',    component: ConfigView,    meta: { title: 'Config', group: 'Settings', icon: 'config' } },
  { path: '/setup',     name: 'setup',     component: SetupView,       meta: { title: 'Setup', group: 'Settings', icon: 'config' } },
  { path: '/channels',  name: 'channels',  component: ChannelsView,  meta: { title: 'Channels', group: 'Control', icon: 'channels' } },
  { path: '/approvals', name: 'approvals', component: ApprovalsView,  meta: { title: 'Approvals', group: 'Settings', icon: 'approvals' } },
  { path: '/skills',    name: 'skills',    component: SkillsView,      meta: { title: 'Skills', group: 'Control', icon: 'skills' } },
  { path: '/logs',      name: 'logs',      component: LogsView,      meta: { title: 'Logs', group: 'Settings', icon: 'logs' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Navigation guard to sync document title
router.afterEach((to) => {
  const title = (to.meta?.title as string) || 'OpenSquilla'
  document.title = `${title} — OpenSquilla`
})
