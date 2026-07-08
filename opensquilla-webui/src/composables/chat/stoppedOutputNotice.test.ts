import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { messagesWithStoppedOutputNotice } from './stoppedOutputNotice'
import { useChatRenderedMessages } from './useChatRenderedMessages'
import type { ChatMessage, ChatRouterTierConfig, ChatRunStatus } from '@/types/chat'

const stoppedStatus: ChatRunStatus = {
  status: 'cancelled',
  label: 'Stopped after 1s',
  task: { task_id: 'task-1', status: 'cancelled', finished_at: 1_234 },
}

describe('messagesWithStoppedOutputNotice', () => {
  it('adds a visible assistant-side stop notice when the cancelled turn has no output', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'start and stop quickly', ts: 1_000, messageId: 'user-1' },
    ]

    const result = messagesWithStoppedOutputNotice(messages, stoppedStatus)

    expect(result).toHaveLength(2)
    expect(result[1]).toMatchObject({
      role: 'assistant',
      text: 'Stopped after 1s',
      interrupted: true,
      stopNotice: true,
    })
  })

  it('does not add a duplicate notice when the turn already has assistant output', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'start and stop after output', ts: 1_000, messageId: 'user-1' },
      { role: 'assistant', text: 'partial output', ts: 1_100, messageId: 'assistant-1' },
    ]

    expect(messagesWithStoppedOutputNotice(messages, stoppedStatus)).toBe(messages)
  })

  it('can add the notice after router-only turn metadata', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'route then stop', ts: 1_000, messageId: 'user-1' },
      { role: 'router', text: '', ts: 1_050, messageId: 'router-1' },
    ]

    const result = messagesWithStoppedOutputNotice(messages, stoppedStatus)

    expect(result).toHaveLength(3)
    expect(result[2]?.role).toBe('assistant')
    expect(result[2]?.text).toBe('Stopped after 1s')
  })

  it('leaves active turns alone', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'still running', ts: 1_000, messageId: 'user-1' },
    ]

    expect(messagesWithStoppedOutputNotice(messages, {
      status: 'running',
      label: 'Running',
      task: { status: 'running' },
    })).toBe(messages)
  })

  it('fills missing stopped-output notices between consecutive user turns', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'same prompt', ts: 1_000, messageId: 'user-1' },
      { role: 'user', text: 'same prompt', ts: 2_000, messageId: 'user-2' },
      { role: 'user', text: 'same prompt', ts: 3_000, messageId: 'user-3' },
    ]

    const result = messagesWithStoppedOutputNotice(messages, stoppedStatus, 'Output interrupted')

    expect(result.map(message => [message.role, message.text])).toEqual([
      ['user', 'same prompt'],
      ['assistant', 'Output interrupted'],
      ['user', 'same prompt'],
      ['assistant', 'Output interrupted'],
      ['user', 'same prompt'],
      ['assistant', 'Stopped after 1s'],
    ])
    expect(result.filter(message => message.stopNotice)).toHaveLength(3)
  })

  it('places interior stopped-output notices after router-only metadata', () => {
    const messages: ChatMessage[] = [
      { role: 'user', text: 'route then stop', ts: 1_000, messageId: 'user-1' },
      { role: 'router', text: '', ts: 1_050, messageId: 'router-1' },
      { role: 'user', text: 'next question', ts: 2_000, messageId: 'user-2' },
    ]

    const result = messagesWithStoppedOutputNotice(messages, stoppedStatus, 'Output interrupted')

    expect(result.map(message => [message.role, message.text])).toEqual([
      ['user', 'route then stop'],
      ['router', ''],
      ['assistant', 'Output interrupted'],
      ['user', 'next question'],
      ['assistant', 'Stopped after 1s'],
    ])
  })

  it('renders the notice in the assistant output path', () => {
    const messages = ref<ChatMessage[]>(messagesWithStoppedOutputNotice([
      { role: 'user', text: 'start and stop quickly', ts: 1_000, messageId: 'user-1' },
    ], stoppedStatus))
    const rendered = useChatRenderedMessages({
      messages,
      sessionKey: ref('agent:main:webchat:test'),
      routerSlots: ref([]),
      routerModels: ref({}),
      routerTierConfigs: ref<Record<string, ChatRouterTierConfig>>({}),
      routerVisualEffectsEnabled: ref(false),
      routerVisualMode: ref('real_candidates'),
      renderMarkdown: text => text,
      stripGeneratedArtifactMarkers: text => text,
      stripTimePrefix: text => text,
      isSubagentCompletionMessage: () => false,
    }).renderedMessages.value

    expect(rendered[1]).toMatchObject({
      displayRole: 'assistant',
      text: 'Stopped after 1s',
      stopNotice: true,
      interrupted: true,
    })
    expect(rendered[1]?.parts?.[0]).toMatchObject({
      type: 'text',
      rawText: 'Stopped after 1s',
    })
  })
})
