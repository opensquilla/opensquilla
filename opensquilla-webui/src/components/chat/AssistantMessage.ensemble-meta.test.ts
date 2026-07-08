// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import type { ChatRenderedMessage } from '@/types/chat'
import AssistantMessage from './AssistantMessage.vue'
import source from './AssistantMessage.vue?raw'

function assistantMessage(overrides: Partial<ChatRenderedMessage> = {}): ChatRenderedMessage {
  return {
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: 'fused answer',
    timeStr: '',
    ts: null,
    showHeader: false,
    ...overrides,
  }
}

async function mountMessage(message: ChatRenderedMessage, propOverrides: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(AssistantMessage, {
    message,
    index: 0,
    shareMode: false,
    shareSelected: false,
    shareMessageId: message.messageId || 'assistant-0',
    renderMarkdown: (text: string) => text,
    fmtTok: (value: number) => String(value),
    toolCallGroups: () => [],
    isToolGroupOpen: () => false,
    isToolItemOpen: () => false,
    toolGroupStatusText: () => '',
    toolStatusText: () => '',
    toolSecondaryText: () => '',
    copyMessage: async () => true,
    ...propOverrides,
  })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('AssistantMessage ensemble footer metadata', () => {
  it('does not present ensemble aggregate metadata as single-model footer metadata', async () => {
    const { app, el } = await mountMessage(
      assistantMessage({
        meta: {
          model: 'z-ai/glm-5.2-20260616',
          modelShort: 'glm-5.2-20260616',
          input: 120,
          output: 40,
          hasTokens: true,
          cachedTokens: 0,
          reasoningTokens: 0,
          costUsd: 0.371989,
          hasSaved: true,
          savedLabel: 'Saved ~92%',
          ensemble: {
            profile: 'default',
            modelCount: 5,
            totalCandidates: 5,
            requestCount: 5,
            fallbackUsed: false,
            fallbackReason: '',
            costUsd: 0.371989,
            savedUsd: 0,
            savedPct: 0,
            models: [],
          },
        },
      }),
    )

    expect(el.querySelector('.msg-meta__model')).toBeNull()
    expect(el.querySelector('.msg-meta__cost')).toBeNull()
    expect(el.querySelector('.savings-indicator')).toBeNull()
    expect(el.querySelector('.msg-meta__ensemble')?.textContent).toBe('Ensemble · 5 models')
    app.unmount()
  })

  it('keeps the savings badge for non-ensemble optimized messages', async () => {
    const { app, el } = await mountMessage(
      assistantMessage({
        meta: {
          model: 'z-ai/glm-5.2-20260616',
          modelShort: 'glm-5.2-20260616',
          input: 120,
          output: 40,
          hasTokens: true,
          cachedTokens: 0,
          reasoningTokens: 0,
          costUsd: 0.050328,
          hasSaved: true,
          savedLabel: 'Saved ~92%',
        },
      }),
    )

    expect(el.querySelector('.savings-indicator')?.textContent).toBe('Saved ~92%')
    app.unmount()
  })

  it('keeps the ensemble summary broad enough on compact layouts', () => {
    expect(source).not.toContain('max-width: 7rem;')
    expect(source).toContain('max-width: min(14rem, 100%);')
  })

  it('does not toggle share selection for stopped-output notices', async () => {
    const onToggleShare = vi.fn()
    const { app, el } = await mountMessage(
      assistantMessage({
        text: 'Stopped after 1s',
        messageId: 'client-stop-notice:task-1',
        stopNotice: true,
      }),
      {
        shareMode: true,
        shareMessageId: 'client-stop-notice:task-1',
        onToggleShare,
      },
    )

    el.querySelector<HTMLElement>('.msg-ai')?.click()
    await nextTick()

    expect(el.querySelector('.chat-share-picker')).toBeNull()
    expect(onToggleShare).not.toHaveBeenCalled()
    app.unmount()
  })
})
