import 'vue-router'

/** Sidebar grouping bands, ordered top→bottom in the Console fold. */
export type NavGroup = 'Work' | 'Operate' | 'Observe' | 'Settings'

/** Console fold renders these bands as labeled sub-sections, in this order. */
export const CONSOLE_GROUP_ORDER: readonly NavGroup[] = ['Operate', 'Observe'] as const

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    group?: NavGroup
    icon?: import('@/utils/icons').IconName
    nav?: 'primary' | 'bottom'
    navOrder?: number
    platforms?: Array<'web' | 'desktop'>
    /** Keep this view mounted across visits so it does not re-run its polling
     *  and RPC fan-out on every navigation. Reserved for poll-heavy observe
     *  views; chat is excluded (it re-inits per session). */
    keepAlive?: boolean
  }
}
