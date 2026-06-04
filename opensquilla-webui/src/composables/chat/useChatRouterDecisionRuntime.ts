import { ref, type Ref } from 'vue'
import type { ChatMessage } from '@/types/chat'
import type { RouterDecisionPayload } from '@/types/rpc'
import {
  type NormalizedRouterDecision,
  normalizeRouterDecision,
  shortModelName,
} from '@/composables/chat/useChatRenderedMessages'

export interface UseChatRouterDecisionRuntimeOptions {
  messages: Ref<ChatMessage[]>
  sessionKey: Ref<string>
  isStreaming: Ref<boolean>
  streamBubble: Ref<boolean>
  streamHasVisibleOutput: Ref<boolean>
  startStreaming: () => void
  resetStreamForRouterReplay: () => void
  resetStreamIdleTimer: () => void
  setStreamActivity: (label: string) => void
  scrollToBottom: () => void
}

export function useChatRouterDecisionRuntime(options: UseChatRouterDecisionRuntimeOptions) {
  const pendingRouterDecision = ref<{ payload: RouterDecisionPayload; decision: NormalizedRouterDecision } | null>(null)

  function handleRouterControlReplay() {
    if (!options.isStreaming.value) options.startStreaming()
    pendingRouterDecision.value = null
    options.resetStreamForRouterReplay()
    options.resetStreamIdleTimer()
    options.scrollToBottom()
  }

  function appendRouterDecision(payload: RouterDecisionPayload, decision = normalizeRouterDecision(payload)) {
    if (!decision) return
    const messageId = payload?.stream_seq
      ? `router-${options.sessionKey.value}-${payload.stream_seq}`
      : `router-${options.sessionKey.value}-${Date.now()}`
    const last = options.messages.value[options.messages.value.length - 1]
    if (last?.messageId === messageId) return

    if (options.isStreaming.value) {
      for (let i = options.messages.value.length - 1; i >= 0; i--) {
        const message = options.messages.value[i]
        if (message.role === 'user') break
        if (message.role === 'router' && message.provenanceKind === 'router_decision') {
          message.routerDecision = decision
          message.messageId = messageId
          message.ts = new Date().toISOString()
          message.routerSettled = true
          options.scrollToBottom()
          return
        }
      }
    }

    options.messages.value.push({
      role: 'router',
      text: '',
      ts: new Date().toISOString(),
      routerDecision: decision,
      provenanceKind: 'router_decision',
      messageId,
    })
    options.scrollToBottom()
  }

  function queueRouterDecision(payload: RouterDecisionPayload) {
    const decision = normalizeRouterDecision(payload)
    if (!decision) return
    if (options.isStreaming.value && options.streamBubble.value && !options.streamHasVisibleOutput.value) {
      const model = shortModelName(decision.model || decision.routed_model || '')
      options.setStreamActivity(model ? `模型路由完成 · ${model}` : '模型路由完成')
    }
    pendingRouterDecision.value = { payload, decision }
    appendRouterDecision(payload, decision)
  }

  function flushPendingRouterDecision() {
    const pending = pendingRouterDecision.value
    if (!pending) return
    pendingRouterDecision.value = null
    appendRouterDecision(pending.payload, pending.decision)
  }

  function clearPendingRouterDecision() {
    pendingRouterDecision.value = null
  }

  return {
    pendingDecision: pendingRouterDecision,
    handleRouterControlReplay,
    queueRouterDecision,
    flushPendingRouterDecision,
    clearPendingRouterDecision,
  }
}
