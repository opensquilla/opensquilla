// @vitest-environment happy-dom
import { createApp, h, nextTick, reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import ActivityDisclosure from './ActivityDisclosure.vue'
import { clearAssistantActivityExpansionState } from '@/utils/chat/activityDisclosureState'

const mountedApps: ReturnType<typeof createApp>[] = []

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  messages: {
    en: {
      chat: {
        activityItems: 'Activity · {count}',
        activityCompletedItems: 'Completed · {count}',
        activityFailures: '{count} failed',
        activityFailuresRecovered: '{count} failure recovered',
      },
    },
  },
})

beforeEach(() => {
  clearAssistantActivityExpansionState()
  document.body.innerHTML = ''
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('ActivityDisclosure lifecycle transitions', () => {
  it.each(['failed', 'interrupted'] as const)(
    'opens a mounted disclosure when its lifecycle becomes %s',
    async lifecycle => {
      const state = reactive({
        lifecycle: 'settled' as 'settled' | 'failed' | 'interrupted',
        defaultOpen: false,
      })
      const host = document.createElement('div')
      document.body.appendChild(host)
      const app = createApp({
        render: () => h(ActivityDisclosure, {
          lifecycle: state.lifecycle,
          defaultOpen: state.defaultOpen,
          stepCount: 1,
          failureCount: 0,
          stateKey: `message-${lifecycle}`,
          continuityKey: `turn-${lifecycle}`,
        }, { default: () => 'Activity details' }),
      })
      mountedApps.push(app)
      app.use(i18n)
      app.mount(host)
      await nextTick()

      const summary = host.querySelector<HTMLButtonElement>(
        '.assistant-activity__summary',
      )
      expect(summary?.getAttribute('aria-expanded')).toBe('false')

      state.lifecycle = lifecycle
      state.defaultOpen = true
      await nextTick()

      expect(summary?.getAttribute('aria-expanded')).toBe('true')
    },
  )
})
