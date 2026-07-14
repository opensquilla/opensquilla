// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, type App } from 'vue'
import i18n from '@/i18n'
import type { ChatRenderedMessage } from '@/types/chat'
import ChatMessageList from './ChatMessageList.vue'

const apps: App<Element>[] = []

afterEach(() => {
  apps.splice(0).forEach(app => app.unmount())
  document.body.innerHTML = ''
})

describe('ChatMessageList history anchors', () => {
  it('renders the same stable user-message anchor consumed by the minimap', () => {
    const userMessage: ChatRenderedMessage = {
      id: 'rendered-user-1',
      messageId: 'message-user-1',
      role: 'user',
      displayRole: 'user',
      roleLabel: 'user',
      text: 'Remember this requirement',
      timeStr: '',
      showHeader: false,
    }
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(ChatMessageList, {
      messages: [userMessage],
      shareMode: false,
      selectedMessageIds: new Set<string>(),
      stripTimePrefix: (value: string) => value,
      renderMarkdown: (value: string) => value,
      fmtTok: (value: number) => String(value),
      subagentSummary: (value: string) => value,
      subagentBody: (value: string) => value,
      toolCallGroups: () => [],
      isToolGroupOpen: () => false,
      isToolItemOpen: () => false,
      toolGroupStatusText: () => '',
      toolStatusText: () => '',
      toolSecondaryText: () => '',
      copyMessage: async () => true,
    })
    app.use(i18n)
    app.mount(host)
    apps.push(app)

    const anchor = host.querySelector<HTMLElement>('.msg-user')
    expect(anchor?.id).toBe('chat-turn-0')
    expect(anchor?.dataset.chatTurnKey).toBe('message-user-1')
    expect(anchor?.tabIndex).toBe(-1)
  })
})
