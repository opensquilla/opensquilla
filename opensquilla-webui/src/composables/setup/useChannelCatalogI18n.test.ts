// @vitest-environment happy-dom
import { beforeAll, describe, expect, it } from 'vitest'
import { createApp, defineComponent, h } from 'vue'
import i18n from '@/i18n'
import { loadLocaleMessages } from '@/i18n/index'
import { useChannelCatalogI18n } from './useChannelCatalogI18n'

beforeAll(async () => {
  // The zh-Hans messages are lazy-loaded; register them before asserting.
  await loadLocaleMessages('zh-Hans')
})

function withOverlay<T>(locale: string, fn: (o: ReturnType<typeof useChannelCatalogI18n>) => T): T {
  i18n.global.locale.value = locale as never
  let captured!: T
  const Comp = defineComponent({
    setup() {
      captured = fn(useChannelCatalogI18n())
      return () => h('div')
    },
  })
  const app = createApp(Comp)
  app.use(i18n)
  const el = document.createElement('div')
  app.mount(el)
  app.unmount()
  return captured
}

describe('useChannelCatalogI18n', () => {
  it('localizes a known channel type description and needs into zh-Hans', () => {
    const { desc, needs } = withOverlay('zh-Hans', o => ({
      desc: o.localizeDescription('slack', 'Slack workspace bot.'),
      needs: o.localizeNeeds('slack', ['Bot token (xoxb-...).', 'Signing secret.']),
    }))
    expect(desc).not.toBe('Slack workspace bot.')
    expect(desc).toContain('Slack')
    expect(needs.length).toBe(2)
    expect(needs.join('')).not.toContain('Signing secret.')
  })

  it('falls back to the backend English for an unknown type or field', () => {
    const { desc, label } = withOverlay('zh-Hans', o => ({
      desc: o.localizeDescription('not_a_channel', 'Backend English description.'),
      label: o.localizeFieldLabel('slack', 'not_a_field', 'Backend Label'),
    }))
    expect(desc).toBe('Backend English description.')
    expect(label).toBe('Backend Label')
  })

  it('returns the fallback needs when the overlay has no array', () => {
    const needs = withOverlay('en', o => o.localizeNeeds('unknown', ['only', 'fallback']))
    expect(needs).toEqual(['only', 'fallback'])
  })
})
