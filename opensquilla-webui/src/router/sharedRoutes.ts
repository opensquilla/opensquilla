import type { RouteRecordRaw } from 'vue-router'

const OverviewView = () => import('@/views/OverviewView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const CronView = () => import('@/views/CronView.vue')
const AgentsView = () => import('@/views/AgentsView.vue')
const ApprovalsView = () => import('@/views/ApprovalsView.vue')
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
      return isMobile ? '/chat' : '/sessions'
    },
  },
  { path: '/chat',      name: 'chat',      component: ChatView,      meta: { title: 'Chat', group: 'Work', icon: 'chat', nav: 'primary', navOrder: 10, platforms: ['web', 'desktop'] } },
  // Draft state: a clean composer with no session key until the first send.
  { path: '/chat/new',  name: 'chat-new',  component: ChatView,      meta: { title: 'Chat', group: 'Work', icon: 'chat', platforms: ['web', 'desktop'] } },
  { path: '/sessions',  name: 'sessions',  component: SessionsView,  meta: { title: 'Sessions', group: 'Work', icon: 'sessions', nav: 'primary', navOrder: 20, platforms: ['web', 'desktop'] } },
  { path: '/approvals', name: 'approvals', component: ApprovalsView, meta: { title: 'Approvals', group: 'Work', icon: 'approvals', nav: 'primary', navOrder: 30, platforms: ['web', 'desktop'] } },
  { path: '/agents',    name: 'agents',    component: AgentsView,    meta: { title: 'Agents', group: 'Operate', icon: 'agents', nav: 'primary', navOrder: 40, platforms: ['web', 'desktop'] } },
  { path: '/channels',  name: 'channels',  component: ChannelsView,  meta: { title: 'Channels', group: 'Operate', icon: 'channels', nav: 'primary', navOrder: 50, platforms: ['web', 'desktop'] } },
  { path: '/cron',      name: 'cron',      component: CronView,      meta: { title: 'Cron', group: 'Operate', icon: 'cron', nav: 'primary', navOrder: 60, platforms: ['web', 'desktop'] } },
  { path: '/skills',    name: 'skills',    component: SkillsView,    meta: { title: 'Skills', group: 'Operate', icon: 'skills', nav: 'primary', navOrder: 70, platforms: ['web', 'desktop'] } },
  { path: '/overview',  name: 'overview',  component: OverviewView,  meta: { title: 'Overview', group: 'Observe', icon: 'home', nav: 'primary', navOrder: 80, platforms: ['web', 'desktop'] } },
  { path: '/usage',     name: 'usage',     component: UsageView,     meta: { title: 'Usage', group: 'Observe', icon: 'usage', nav: 'primary', navOrder: 90, platforms: ['web', 'desktop'] } },
  { path: '/logs',      name: 'logs',      component: LogsView,      meta: { title: 'Logs', group: 'Observe', icon: 'logs', nav: 'primary', navOrder: 100, platforms: ['web', 'desktop'] } },
  // Readiness/doctor moved inline into Overview; the old deep link stays valid.
  { path: '/health',    redirect: '/overview' },
]
