import type { RouteRecordRaw } from 'vue-router'
import { detectPlatformId } from '@/platform/capabilities'
import { readLastRoute } from './lastRoute'

const ChatView = () => import('@/views/ChatView.vue')
const CronView = () => import('@/views/CronView.vue')
const AgentsView = () => import('@/views/AgentsView.vue')
const SessionsView = () => import('@/views/SessionsView.vue')
const SkillsView = () => import('@/views/SkillsView.vue')
const ChangelogView = () => import('@/views/ChangelogView.vue')
// Hosts Overview / Channels / Usage / Logs as tabbed sections of one Monitor
// destination (the four views stay intact inside it).
const MonitorHubView = () => import('@/views/MonitorHubView.vue')

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
  // Monitor hub: Overview/Channels/Usage/Logs are one destination with four
  // tabbed sections. All four canonical URLs stay valid (the tabs are routes);
  // only /overview carries the rail entry. Shared viewKey keeps one live
  // instance across the four paths so tab switches never remount the hub.
  { path: '/overview',  name: 'overview',  component: MonitorHubView, meta: { title: 'Overview', group: 'Work', icon: 'home', nav: 'primary', navOrder: 30, platforms: ['web', 'desktop'], keepAlive: true, viewKey: 'monitor-hub' } },
  { path: '/channels',  name: 'channels',  component: MonitorHubView, meta: { title: 'Channels', icon: 'channels', platforms: ['web', 'desktop'], keepAlive: true, viewKey: 'monitor-hub' } },
  { path: '/usage',     name: 'usage',     component: MonitorHubView, meta: { title: 'Usage', icon: 'usage', platforms: ['web', 'desktop'], keepAlive: true, viewKey: 'monitor-hub' } },
  { path: '/logs',      name: 'logs',      component: MonitorHubView, meta: { title: 'Logs', icon: 'logs', platforms: ['web', 'desktop'], keepAlive: true, viewKey: 'monitor-hub' } },
  // Approvals retired as a front-end destination: the pending queue resolves
  // inline in the chat transcript (ApprovalCard) and via the topbar interrupt
  // pill. The old deep link redirects to Sessions so bookmarks and the pill
  // degrade gracefully
  // (openBlockedApprovalSession() routes straight to the blocked chat first).
  { path: '/approvals', redirect: '/sessions' },
  { path: '/agents',    name: 'agents',    component: AgentsView,    meta: { title: 'Agents', group: 'Operate', icon: 'agents', nav: 'primary', navOrder: 40, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/cron',      name: 'cron',      component: CronView,      meta: { title: 'Cron', group: 'Operate', icon: 'cron', nav: 'primary', navOrder: 55, platforms: ['web', 'desktop'], keepAlive: true } },
  { path: '/skills',    name: 'skills',    component: SkillsView,    meta: { title: 'Skills', group: 'Operate', icon: 'skills', nav: 'primary', navOrder: 45, platforms: ['web', 'desktop'], keepAlive: true } },
  // Editorial surface (read, not operated): the first route to opt into an
  // Axis-B expressive skin. Not in the primary nav — reached by URL / links.
  { path: '/changelog', name: 'changelog', component: ChangelogView, meta: { title: 'Changelog', platforms: ['web', 'desktop'], skin: 'out-of-register' } },
  // Readiness/doctor moved inline into Overview; the old deep link stays valid.
  { path: '/health',    redirect: '/overview' },
]
