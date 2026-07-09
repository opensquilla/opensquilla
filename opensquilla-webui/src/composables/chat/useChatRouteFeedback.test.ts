import { beforeEach, describe, expect, it, vi } from 'vitest'

const rpcCall = vi.fn()

vi.mock('@/stores/rpc', () => ({
  useRpcStore: () => ({ call: rpcCall }),
}))

const pushToast = vi.fn()
vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ pushToast }),
}))

vi.mock('@/i18n', () => ({
  default: { global: { t: (key: string) => key } },
}))

import { useChatRouteFeedback } from './useChatRouteFeedback'

describe('useChatRouteFeedback', () => {
  beforeEach(() => {
    rpcCall.mockReset()
    pushToast.mockReset()
  })

  it('submits a rating and records optimistic state', async () => {
    rpcCall.mockResolvedValue({ accepted: true, recorded: 'up' })
    const fb = useChatRouteFeedback()

    await fb.submit('dec-1', 'up')

    expect(rpcCall).toHaveBeenCalledWith('router.feedback.submit', {
      decisionId: 'dec-1',
      rating: 'up',
    })
    expect(fb.ratingFor('dec-1')).toBe('up')
    expect(pushToast).not.toHaveBeenCalled()
  })

  it('clicking the active thumb again revokes with neutral', async () => {
    rpcCall.mockResolvedValue({ accepted: true })
    const fb = useChatRouteFeedback()

    await fb.submit('dec-2', 'down')
    expect(fb.ratingFor('dec-2')).toBe('down')

    await fb.submit('dec-2', 'down')
    expect(rpcCall).toHaveBeenLastCalledWith('router.feedback.submit', {
      decisionId: 'dec-2',
      rating: 'neutral',
    })
    expect(fb.ratingFor('dec-2')).toBeUndefined()
  })

  it('clicking the other thumb revises the rating', async () => {
    rpcCall.mockResolvedValue({ accepted: true })
    const fb = useChatRouteFeedback()

    await fb.submit('dec-3', 'down')
    await fb.submit('dec-3', 'up')

    expect(rpcCall).toHaveBeenLastCalledWith('router.feedback.submit', {
      decisionId: 'dec-3',
      rating: 'up',
    })
    expect(fb.ratingFor('dec-3')).toBe('up')
  })

  it('rolls back and toasts when the decision expired', async () => {
    rpcCall.mockResolvedValue({ accepted: false, reason: 'decision_not_found' })
    const fb = useChatRouteFeedback()

    await fb.submit('dec-4', 'up')

    expect(fb.ratingFor('dec-4')).toBeUndefined()
    expect(pushToast).toHaveBeenCalledWith('chat.routeFeedback.expired', { tone: 'danger' })
  })

  it('rolls back to the previous rating on a transport error', async () => {
    rpcCall.mockResolvedValueOnce({ accepted: true })
    const fb = useChatRouteFeedback()
    await fb.submit('dec-5', 'up')

    rpcCall.mockRejectedValueOnce(new Error('boom'))
    await fb.submit('dec-5', 'down')

    expect(fb.ratingFor('dec-5')).toBe('up')
    expect(pushToast).toHaveBeenCalledWith('chat.routeFeedback.failed', { tone: 'danger' })
  })
})
