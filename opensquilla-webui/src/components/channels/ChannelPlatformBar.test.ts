// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, defineComponent, h, nextTick } from 'vue'
import ChannelPlatformBar from './ChannelPlatformBar.vue'
import i18n from '@/i18n'
import type { ChannelEditorSpec } from '@/composables/channels/useChannelEditor'

const ALL_TYPES = ['slack', 'telegram', 'discord', 'matrix', 'feishu', 'wecom', 'dingtalk', 'qq']

function specsFor(types: string[]): ChannelEditorSpec[] {
  return types.map(type => ({ type, label: type, fields: [] }))
}

async function mountBar(props: {
  channels: ChannelEditorSpec[]
  usedTypes: string[]
  pending?: boolean
  locale?: string
  onPick?: (type: string) => void
  onMore?: () => void
}) {
  i18n.global.locale.value = (props.locale || 'en') as 'en'
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(defineComponent({
    setup() {
      return () => h(ChannelPlatformBar, {
        channels: props.channels,
        usedTypes: props.usedTypes,
        pending: props.pending ?? false,
        onPick: props.onPick,
        onMore: props.onMore,
      })
    },
  }))
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

function chipTypes(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll<HTMLElement>('.ch-platbar__chip[data-channel-type]'))
    .map(node => node.getAttribute('data-channel-type') || '')
}

afterEach(() => {
  i18n.global.locale.value = 'en'
})

describe('ChannelPlatformBar', () => {
  it('skips already-configured platforms, orders locale-default, caps at 6 with a +N more chip', async () => {
    const { app, el } = await mountBar({ channels: specsFor(ALL_TYPES), usedTypes: ['slack'] })
    try {
      // slack is configured → skipped; the remaining 7 order by the default
      // (non-zh) ladder, capped at six, with the 7th folded into "+1 more".
      expect(chipTypes(el)).toEqual(['telegram', 'discord', 'matrix', 'feishu', 'wecom', 'dingtalk'])
      expect(el.querySelector('[data-channel-type="slack"]')).toBeNull()
      const more = el.querySelector<HTMLElement>('.ch-platbar__chip--more')
      expect(more).toBeTruthy()
      expect(more!.textContent).toContain('+1 more')
    } finally {
      app.unmount()
    }
  })

  it('drops the more chip when six or fewer platforms remain', async () => {
    const { app, el } = await mountBar({
      channels: specsFor(ALL_TYPES),
      usedTypes: ['slack', 'telegram'],
    })
    try {
      expect(chipTypes(el)).toHaveLength(6)
      expect(el.querySelector('.ch-platbar__chip--more')).toBeNull()
    } finally {
      app.unmount()
    }
  })

  it('orders CN platforms first for zh locales', async () => {
    const { app, el } = await mountBar({
      channels: specsFor(ALL_TYPES),
      usedTypes: [],
      locale: 'zh-Hans',
    })
    try {
      // zh ladder leads with the CN-ecosystem platforms; capped at six.
      expect(chipTypes(el)).toEqual(['feishu', 'wecom', 'dingtalk', 'qq', 'slack', 'telegram'])
    } finally {
      app.unmount()
    }
  })

  it('emits pick with the chip type and more from the overflow chip', async () => {
    const picked: string[] = []
    let moreCount = 0
    const { app, el } = await mountBar({
      channels: specsFor(ALL_TYPES),
      usedTypes: ['slack'],
      onPick: type => picked.push(type),
      onMore: () => { moreCount += 1 },
    })
    try {
      el.querySelector<HTMLButtonElement>('[data-channel-type="feishu"]')!.click()
      await nextTick()
      expect(picked).toEqual(['feishu'])
      el.querySelector<HTMLButtonElement>('.ch-platbar__chip--more')!.click()
      await nextTick()
      expect(moreCount).toBe(1)
    } finally {
      app.unmount()
    }
  })
})
