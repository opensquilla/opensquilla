// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref } from 'vue'

import { useDialogA11y } from './useDialogA11y'

describe('useDialogA11y modal stack', () => {
  let app: ReturnType<typeof createApp> | null = null

  afterEach(() => {
    app?.unmount()
    app = null
    document.body.innerHTML = ''
  })

  it('lets only the topmost dialog own Tab and Escape, then restores each invoker', async () => {
    const Host = defineComponent({
      setup() {
        const lowerOpen = ref(false)
        const upperOpen = ref(false)
        const lowerRoot = ref<HTMLElement | null>(null)
        const upperRoot = ref<HTMLElement | null>(null)

        useDialogA11y(lowerRoot, lowerOpen, () => { lowerOpen.value = false })
        useDialogA11y(upperRoot, upperOpen, () => { upperOpen.value = false })

        return () => h('div', [
          h('button', {
            id: 'lower-trigger',
            onClick: () => { lowerOpen.value = true },
          }, 'Open lower'),
          lowerOpen.value
            ? h('section', { ref: lowerRoot, role: 'dialog', 'aria-label': 'Lower' }, [
                h('button', {
                  id: 'upper-trigger',
                  onClick: () => { upperOpen.value = true },
                }, 'Open upper'),
                h('button', { id: 'lower-last' }, 'Lower last'),
              ])
            : null,
          upperOpen.value
            ? h('section', { ref: upperRoot, role: 'dialog', 'aria-label': 'Upper' }, [
                h('button', { id: 'upper-first' }, 'Upper first'),
                h('button', { id: 'upper-last' }, 'Upper last'),
              ])
            : null,
        ])
      },
    })

    const root = document.createElement('div')
    document.body.appendChild(root)
    app = createApp(Host)
    app.mount(root)

    const lowerTrigger = document.querySelector<HTMLButtonElement>('#lower-trigger')!
    lowerTrigger.focus()
    lowerTrigger.click()
    await nextTick()
    await nextTick()
    const upperTrigger = document.querySelector<HTMLButtonElement>('#upper-trigger')!
    expect(document.activeElement).toBe(upperTrigger)

    upperTrigger.click()
    await nextTick()
    await nextTick()
    const upperFirst = document.querySelector<HTMLButtonElement>('#upper-first')!
    expect(document.activeElement).toBe(upperFirst)

    // If the lower trap were still active, Tab from its last button would wrap
    // inside the lower dialog before the upper dialog could handle the event.
    document.querySelector<HTMLButtonElement>('#lower-last')!.focus()
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    document.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(upperFirst)

    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape', bubbles: true, cancelable: true,
    }))
    await nextTick()
    expect(document.querySelector('[aria-label="Upper"]')).toBeNull()
    expect(document.querySelector('[aria-label="Lower"]')).toBeTruthy()
    expect(document.activeElement).toBe(upperTrigger)

    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape', bubbles: true, cancelable: true,
    }))
    await nextTick()
    expect(document.querySelector('[aria-label="Lower"]')).toBeNull()
    expect(document.activeElement).toBe(lowerTrigger)
  })
})
