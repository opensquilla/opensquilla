// @vitest-environment happy-dom
// The pending-pairing banner's "approve as admin" checkbox: the local
// fallback override must survive a transient pendingPairing blip (the same
// request disappearing and re-resolving) while never leaking onto a
// different request, and the host-controlled mode must delegate all state to
// the host instead of keeping a second copy.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, reactive } from 'vue'
import i18n from '@/i18n'
import ChannelAlerts from './ChannelAlerts.vue'
import type { ChannelPairing } from '@/composables/channels/useChannelMembers'

function pairing(id: string): ChannelPairing {
  return {
    pairingId: id,
    pairingCode: 'AB12CD34',
    channelName: 'ops-slack',
    senderId: `U-${id}`,
    senderName: `Sender ${id}`,
    status: 'pending',
  }
}

interface HostState {
  pendingPairing: ChannelPairing | null
  defaultAsAdmin: boolean
  asAdminChecked?: boolean
}

function mountAlerts(state: HostState, handlers: {
  onApprove?: (asAdmin: boolean) => void
  onSetAsAdmin?: (asAdmin: boolean) => void
} = {}) {
  i18n.global.locale.value = 'en'
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(defineComponent({
    setup() {
      return () => h(ChannelAlerts, {
        pendingPairing: state.pendingPairing,
        defaultAsAdmin: state.defaultAsAdmin,
        ...(state.asAdminChecked !== undefined ? { asAdminChecked: state.asAdminChecked } : {}),
        onApprove: handlers.onApprove,
        onSetAsAdmin: handlers.onSetAsAdmin,
      })
    },
  }))
  app.use(i18n)
  app.mount(el)
  return { app, el }
}

function checkbox(el: HTMLElement): HTMLInputElement {
  const box = el.querySelector<HTMLInputElement>('.chal__asadmin input')
  if (!box) throw new Error('as-admin checkbox not found')
  return box
}

function toggle(el: HTMLElement, value: boolean): void {
  const box = checkbox(el)
  box.checked = value
  box.dispatchEvent(new Event('change', { bubbles: true }))
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('ChannelAlerts as-admin override (local fallback)', () => {
  it('survives a transient pairing blip but resets for a different request', async () => {
    const state = reactive<HostState>({ pendingPairing: pairing('pair-1'), defaultAsAdmin: false })
    const onApprove = vi.fn()
    const { app, el } = mountAlerts(state, { onApprove })
    try {
      expect(checkbox(el).checked).toBe(false)
      toggle(el, true)
      await nextTick()
      expect(checkbox(el).checked).toBe(true)

      // Transient facts failure hides the banner…
      state.pendingPairing = null
      await nextTick()
      expect(el.querySelector('.chal--pending')).toBeNull()

      // …and the next poll restores the SAME request: the explicit choice
      // must still stand.
      state.pendingPairing = pairing('pair-1')
      await nextTick()
      expect(checkbox(el).checked).toBe(true)
      el.querySelector<HTMLButtonElement>('.chal__btn')!.click()
      expect(onApprove).toHaveBeenCalledWith(true)

      // A DIFFERENT request never inherits the override.
      state.pendingPairing = pairing('pair-2')
      await nextTick()
      expect(checkbox(el).checked).toBe(false)
    } finally {
      app.unmount()
    }
  })

  it('falls back to the bootstrap default until explicitly overridden', async () => {
    const state = reactive<HostState>({ pendingPairing: pairing('pair-1'), defaultAsAdmin: true })
    const { app, el } = mountAlerts(state)
    try {
      expect(checkbox(el).checked).toBe(true)
      toggle(el, false)
      await nextTick()
      expect(checkbox(el).checked).toBe(false)
    } finally {
      app.unmount()
    }
  })
})

describe('ChannelAlerts as-admin override (host-controlled)', () => {
  it('renders the host state and emits setAsAdmin instead of self-updating', async () => {
    const state = reactive<HostState>({
      pendingPairing: pairing('pair-1'),
      defaultAsAdmin: true,
      asAdminChecked: false,
    })
    const onApprove = vi.fn()
    const onSetAsAdmin = vi.fn()
    const { app, el } = mountAlerts(state, { onApprove, onSetAsAdmin })
    try {
      // The prop wins over the bootstrap default: no second source of truth.
      expect(checkbox(el).checked).toBe(false)
      toggle(el, true)
      await nextTick()
      expect(onSetAsAdmin).toHaveBeenCalledWith(true)
      // The component holds no local copy: approve reads the HOST value, not
      // the DOM toggle, until the host reflects the change.
      el.querySelector<HTMLButtonElement>('.chal__btn')!.click()
      expect(onApprove).toHaveBeenCalledWith(false)

      state.asAdminChecked = true
      await nextTick()
      expect(checkbox(el).checked).toBe(true)
      el.querySelector<HTMLButtonElement>('.chal__btn')!.click()
      expect(onApprove).toHaveBeenLastCalledWith(true)
    } finally {
      app.unmount()
    }
  })
})
