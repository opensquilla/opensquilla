import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { getPlatform } from '@/platform'
import { desktopRoutes } from './desktopRoutes'
import { sharedRoutes } from './sharedRoutes'
import { webRoutes } from './webRoutes'
import { captureContentScroll, contentScrollBehavior } from './scrollMemory'

const basePath = (() => {
  const el = document.getElementById('opensquilla-data')
  const raw = el?.dataset.basePath || '/control'
  return raw.endsWith('/') ? raw : raw + '/'
})()

const platform = getPlatform()

export const routes: RouteRecordRaw[] = [
  ...sharedRoutes,
  ...(platform.capabilities.hasWebConfig ? webRoutes : []),
  ...(platform.capabilities.hasDesktopOnboarding ? desktopRoutes : []),
]

export const router = createRouter({
  history: createWebHistory(basePath),
  routes,
  scrollBehavior: contentScrollBehavior,
})

// Capture the leaving route's content scroll offset so back/forward can restore it.
router.beforeEach((_to, from) => {
  captureContentScroll(from)
})

// Navigation guard to sync document title
router.afterEach((to) => {
  const title = (to.meta?.title as string) || 'OpenSquilla'
  document.title = `${title} — OpenSquilla`
})
