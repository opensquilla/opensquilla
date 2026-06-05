import type { RouteRecordRaw } from 'vue-router'

const OverviewView = () => import('@/views/OverviewView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const CronView = () => import('@/views/CronView.vue')
const AgentsView = () => import('@/views/AgentsView.vue')
const ApprovalsView = () => import('@/views/ApprovalsView.vue')
const HealthView = () => import('@/views/HealthView.vue')
const ChannelsView = () => import('@/views/ChannelsView.vue')
const LogsView = () => import('@/views/LogsView.vue')
const SessionsView = () => import('@/views/SessionsView.vue')
const UsageView = () => import('@/views/UsageView.vue')
const SkillsView = () => import('@/views/SkillsView.vue')

export const sharedRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: () => {
      const isMobile = window.matchMedia('(max-width: 768px)').matches
      return isMobile ? '/chat' : '/overview'
    },
  },
  { path: '/overview',  name: 'overview',  component: OverviewView,  meta: { title: 'Overview', group: 'Control', icon: 'home', nav: 'primary', navOrder: 10, platforms: ['web', 'desktop'] } },
  { path: '/health',    name: 'health',    component: HealthView,    meta: { title: 'Health', group: 'Control', icon: 'logs', nav: 'primary', navOrder: 20, platforms: ['web', 'desktop'] } },
  { path: '/chat',      name: 'chat',      component: ChatView,      meta: { title: 'Chat', group: 'Chat', icon: 'chat', platforms: ['web', 'desktop'] } },
  { path: '/agents',    name: 'agents',    component: AgentsView,    meta: { title: 'Agents', group: 'Control', icon: 'agents', nav: 'primary', navOrder: 30, platforms: ['web', 'desktop'] } },
  { path: '/skills',    name: 'skills',    component: SkillsView,    meta: { title: 'Skills', group: 'Control', icon: 'skills', nav: 'primary', navOrder: 40, platforms: ['web', 'desktop'] } },
  { path: '/channels',  name: 'channels',  component: ChannelsView,  meta: { title: 'Channels', group: 'Control', icon: 'channels', nav: 'primary', navOrder: 50, platforms: ['web', 'desktop'] } },
  { path: '/cron',      name: 'cron',      component: CronView,      meta: { title: 'Cron', group: 'Control', icon: 'cron', nav: 'primary', navOrder: 60, platforms: ['web', 'desktop'] } },
  { path: '/sessions',  name: 'sessions',  component: SessionsView,  meta: { title: 'Sessions', group: 'Control', icon: 'sessions', nav: 'primary', navOrder: 70, platforms: ['web', 'desktop'] } },
  { path: '/usage',     name: 'usage',     component: UsageView,     meta: { title: 'Usage', group: 'Control', icon: 'usage', nav: 'primary', navOrder: 80, platforms: ['web', 'desktop'] } },
  { path: '/logs',      name: 'logs',      component: LogsView,      meta: { title: 'Logs', group: 'Settings', icon: 'logs', nav: 'bottom', navOrder: 20, platforms: ['web', 'desktop'] } },
  { path: '/approvals', name: 'approvals', component: ApprovalsView, meta: { title: 'Approvals', group: 'Settings', icon: 'approvals', nav: 'bottom', navOrder: 30, platforms: ['web', 'desktop'] } },
]
