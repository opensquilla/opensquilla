import type { RouteRecordRaw } from 'vue-router'
import { detectPlatformId } from '@/platform/capabilities'
import { readLastRoute } from './lastRoute'

const OverviewView = () => import('@/views/OverviewView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const CronView = () => import('@/views/CronView.vue')
const RagView = () => import('@/views/KnowledgeView.vue')
const AgentsView = () => import('@/views/AgentsView.vue')
const ApprovalsView = () => import('@/views/ApprovalsView.vue')
const ChannelsView = () => import('@/views/ChannelsView.vue')
const LogsView = () => import('@/views/LogsView.vue')
const SessionsView = () => import('@/views/SessionsView.vue')
const UsageView = () => import('@/views/UsageView.vue')
const SkillsView = () => import('@/views/SkillsView.vue')

export function defaultRootRedirect(): string {
  if (detectPlatformId() === 'desktop') return '/chat'
  const saved = readLastRoute()
  if (saved) return saved
  const isMobile = window.matchMedia('(max-width: 768px)').matches
  return isMobile ? '/chat' : '/sessions'
}

export const sharedRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: () => {
      // Desktop app cold starts should feel like opening an assistant: land on
      // Chat, not the session ledger. Browser builds still restore the last
      // stable view when available, with the existing responsive fallback.
      return defaultRootRedirect()
    },
  },
  { path: '/chat',      name: 'chat',      component: ChatView,      meta: { title: 'Chat', group: 'Work', icon: 'chat', nav: 'primary', navOrder: 10, platforms: ['web', 'desktop'] } },
  // Draft state: a clean composer with no session key until the first send.
  { path: '/chat/new',  name: 'chat-new',  component: ChatView,      meta: { title: 'Chat', group: 'Work', icon: 'chat', platforms: ['web', 'desktop'] } },
  { path: '/sessions',  name: 'sessions',  component: SessionsView,  meta: { title: 'Sessions', group: 'Work', icon: 'sessions', nav: 'primary', navOrder: 20, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/approvals', name: 'approvals', component: ApprovalsView, meta: { title: 'Approvals', group: 'Operate', icon: 'approvals', nav: 'primary', navOrder: 35, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/agents',    name: 'agents',    component: AgentsView,    meta: { title: 'Agents', group: 'Operate', icon: 'agents', nav: 'primary', navOrder: 40, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/channels',  name: 'channels',  component: ChannelsView,  meta: { title: 'Channels', group: 'Operate', icon: 'channels', nav: 'primary', navOrder: 50, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/cron',      name: 'cron',      component: CronView,      meta: { title: 'Cron', group: 'Work', icon: 'cron', nav: 'primary', navOrder: 25, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/rag',        name: 'rag',       component: RagView,       alias: '/knowledge', meta: { title: 'RAG', group: 'Work', icon: 'search', nav: 'primary', navOrder: 27, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/skills',    name: 'skills',    component: SkillsView,    meta: { title: 'Skills', group: 'Work', icon: 'skills', nav: 'primary', navOrder: 28, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/overview',  name: 'overview',  component: OverviewView,  meta: { title: 'Overview', group: 'Observe', icon: 'home', nav: 'primary', navOrder: 80, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/usage',     name: 'usage',     component: UsageView,     meta: { title: 'Usage', group: 'Observe', icon: 'usage', nav: 'primary', navOrder: 90, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/logs',      name: 'logs',      component: LogsView,      meta: { title: 'Logs', group: 'Observe', icon: 'logs', nav: 'primary', navOrder: 100, platforms: ['web', 'desktop'], keepAlive: true } },
  // Readiness/doctor moved inline into Overview; the old deep link stays valid.
  { path: '/health',    redirect: '/overview' },
]
