// @vitest-environment happy-dom

import { createApp, h, type App } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it } from 'vitest'

import ClarifyCard from '@/components/chat/ClarifyCard.vue'
import en from '@/locales/en.json'

const mountedApps: App<Element>[] = []

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.replaceChildren()
})

function mountCard(intro: string): HTMLElement {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp({
    setup: () => () => h(ClarifyCard, {
      request: {
        intro,
        fields: [{
          name: 'review',
          prompt: 'Review reply',
          type: 'string',
          required: true,
          defaultValue: '',
          choices: [],
        }],
        runId: 'run-long-preview',
        step: 'revision_confirm_gate',
      },
    }),
  })
  app.use(createI18n({ legacy: false, locale: 'en', messages: { en } }))
  app.mount(host)
  mountedApps.push(app)
  return host.querySelector<HTMLElement>('[data-testid="clarify-intro"]')!
}

describe('ClarifyCard long previews', () => {
  it('keeps an ordinary intro in the normal non-scrollable layout', () => {
    const intro = mountCard('A short clarification note.')

    expect(intro.classList.contains('clarify-card__intro--long')).toBe(false)
    expect(intro.getAttribute('tabindex')).toBeNull()
  })

  it('makes the complete long snapshot keyboard-focusable inside its bounded preview', () => {
    const snapshot = `=== Script snapshot ===\n${'shot detail\n'.repeat(500)}END_OF_SNAPSHOT`
    const intro = mountCard(snapshot)

    expect(snapshot.length).toBeGreaterThan(5_000)
    expect(intro.classList.contains('clarify-card__intro--long')).toBe(true)
    expect(intro.getAttribute('tabindex')).toBe('0')
    expect(intro.textContent).toBe(snapshot)
    expect(intro.textContent?.endsWith('END_OF_SNAPSHOT')).toBe(true)

    intro.focus()
    expect(document.activeElement).toBe(intro)
  })
})
