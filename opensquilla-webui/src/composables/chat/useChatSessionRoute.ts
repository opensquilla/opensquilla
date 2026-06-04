import type { Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  WEBCHAT_SESSION_KEY,
  agentIdFromSessionKey,
  canonicalSessionKey,
  webchatSessionKey,
} from '@/utils/chat/sessionKeys'

const ACTIVE_SESSION_STORAGE_KEY = 'opensquilla_active_session'

function routeStringParam(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function readStoredSession(): string {
  try {
    return canonicalSessionKey(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY) || '')
  } catch {
    return ''
  }
}

function writeStoredSession(key: string) {
  try {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, key)
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

export function useChatSessionRoute(sessionKey: Ref<string>) {
  const route = useRoute()
  const router = useRouter()

  function persistSession(key: string, options: { updateRoute?: boolean } = {}) {
    sessionKey.value = canonicalSessionKey(key)
    writeStoredSession(sessionKey.value)
    if (options.updateRoute === false) return
    if (readSessionFromUrl() === sessionKey.value) return
    router.replace({ path: '/chat', query: { session: sessionKey.value } }).catch(() => {})
  }

  function hasNewChatRouteSignal(): boolean {
    return route.query.newChat === '1' || route.query.new === '1'
  }

  function readSessionFromUrl(): string {
    return routeStringParam(route.query.session)
  }

  function readAgentFromUrl(): string {
    return routeStringParam(route.query.agent)
  }

  function createSessionKey(): string {
    return webchatSessionKey(agentIdFromSessionKey(sessionKey.value), Math.random().toString(36).slice(2, 10))
  }

  function resolveInitialSession(): { sessionKey: string; hasUrlSession: boolean; startNewChat: boolean } {
    const urlSession = readSessionFromUrl()
    const urlAgent = readAgentFromUrl()
    const storedSession = readStoredSession()
    const fallbackSession = urlAgent ? webchatSessionKey(urlAgent) : (storedSession || WEBCHAT_SESSION_KEY)
    return {
      sessionKey: canonicalSessionKey(urlSession || fallbackSession),
      hasUrlSession: Boolean(urlSession),
      startNewChat: hasNewChatRouteSignal(),
    }
  }

  return {
    route,
    createSessionKey,
    hasNewChatRouteSignal,
    persistSession,
    readAgentFromUrl,
    readSessionFromUrl,
    resolveInitialSession,
  }
}
