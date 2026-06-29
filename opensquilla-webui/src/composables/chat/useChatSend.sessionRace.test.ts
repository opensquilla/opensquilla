import { describe, expect, it } from 'vitest'
import { decideSendResponseSession } from './useChatSend'

describe('decideSendResponseSession', () => {
  it('ignores a late response after the user navigated to another session', () => {
    expect(decideSendResponseSession({
      requestSessionKey: 'agent:main:webchat:A',
      currentSessionKey: 'agent:main:webchat:B',
      responseSessionKey: 'agent:main:webchat:A',
    })).toEqual({
      action: 'ignore',
      reason: 'current_session_changed',
    })
  })

  it('persists server canonicalization while the request session is still current', () => {
    expect(decideSendResponseSession({
      requestSessionKey: 'legacy-A',
      currentSessionKey: 'legacy-A',
      responseSessionKey: 'agent:main:webchat:legacy-A',
    })).toEqual({
      action: 'persist',
      responseSessionKey: 'agent:main:webchat:legacy-A',
    })
  })

  it('ignores same-session responses', () => {
    expect(decideSendResponseSession({
      requestSessionKey: 'agent:main:webchat:A',
      currentSessionKey: 'agent:main:webchat:A',
      responseSessionKey: 'agent:main:webchat:A',
    })).toEqual({
      action: 'ignore',
      reason: 'same_session',
    })
  })

  it('ignores responses with no session key', () => {
    expect(decideSendResponseSession({
      requestSessionKey: 'agent:main:webchat:A',
      currentSessionKey: 'agent:main:webchat:A',
      responseSessionKey: undefined,
    })).toEqual({
      action: 'ignore',
      reason: 'missing_response_session',
    })
  })
})
