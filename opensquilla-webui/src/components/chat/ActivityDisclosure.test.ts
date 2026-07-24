// @vitest-environment happy-dom
import { createApp, h, nextTick, reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import ActivityDisclosure from './ActivityDisclosure.vue'
import activityDisclosureSource from './ActivityDisclosure.vue?raw'
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
  it('uses an AA text token for the compact summary', () => {
    const selectorStart = activityDisclosureSource.indexOf(
      '.assistant-activity__summary {',
    )
    const blockEnd = activityDisclosureSource.indexOf('}', selectorStart)
    const rule = activityDisclosureSource.slice(selectorStart, blockEnd)

    expect(selectorStart).toBeGreaterThanOrEqual(0)
    expect(rule).toContain('color: var(--text-muted);')

    const elapsedStart = activityDisclosureSource.indexOf(
      '.assistant-activity__live-elapsed {',
    )
    const elapsedEnd = activityDisclosureSource.indexOf('}', elapsedStart)
    const elapsedRule = activityDisclosureSource.slice(elapsedStart, elapsedEnd)
    expect(elapsedRule).toContain('color: var(--text-muted);')

    const activeStart = activityDisclosureSource.indexOf(
      '.assistant-activity__live-label.is-active {',
    )
    const activeEnd = activityDisclosureSource.indexOf('}', activeStart)
    const activeRule = activityDisclosureSource.slice(activeStart, activeEnd)
    expect(activeRule).toContain('var(--text-muted)')
    expect(activeRule).toContain('var(--text)')
    expect(activeRule).not.toContain('transparent)')
  })

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
