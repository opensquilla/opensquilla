import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import {
  parseMetaCommandInvocation,
  useChatSlashCommands,
  type ChatSlashCommand,
  type UseChatSlashCommandsOptions,
} from './useChatSlashCommands'

type RpcMock = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<unknown>

function harness(call: RpcMock, requestMetaSetup?: UseChatSlashCommandsOptions['requestMetaSetup']) {
  const notify = vi.fn()
  const dispatchHidden = vi.fn()
  const inputText = ref('')
  const sessionKey = ref('agent:main:test')
  const restoreDraft = vi.fn()
  const api = useChatSlashCommands({
    rpc: {
      waitForConnection: async () => undefined,
      call: async <T = unknown>(method: string, params?: Record<string, unknown>) => (
        await call(method, params) as T
      ),
    },
    inputText,
    sessionKey,
    autoResizeTextarea: vi.fn(),
    newSession: vi.fn(),
    resetCurrentSession: vi.fn(),
    setCompactInFlight: vi.fn(),
    showCompactStatus: vi.fn(),
    notify,
    dispatchHidden,
    restoreDraft,
    requestMetaSetup,
  })
  return { api, notify, dispatchHidden, restoreDraft, inputText, sessionKey }
}

const META_COMMAND: ChatSlashCommand = {
  name: '/meta',
  cmd: '/meta',
  label: '/meta',
  desc: 'Run a MetaSkill',
  aliases: [],
  execution: { action: 'meta.menu' },
}

describe('useChatSlashCommands MetaSkill readiness', () => {
  it('durably stages the exact request before dispatching its hidden turn', async () => {
    const call = vi.fn(async (method: string) => {
      if (method === 'commands.list_for_surface') return { commands: [META_COMMAND] }
      if (method === 'meta.run') return { ok: true }
      throw new Error(`unexpected ${method}`)
    })
    const { api, dispatchHidden } = harness(call)

    await api.executeSlashCommand(
      '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
    )
    await Promise.resolve()
    await Promise.resolve()

    expect(call).toHaveBeenCalledWith('meta.run', {
      name: 'meta-paper-write',
      sessionKey: 'agent:main:test',
      clientRequestId: expect.any(String),
      launchText: '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
    })
    expect(dispatchHidden).toHaveBeenCalledWith(
      '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
      '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
      expect.any(String),
      'agent:main:test',
    )
  })

  it('keeps the legacy command compatible and ignores unseparated trailing tokens', () => {
    expect(parseMetaCommandInvocation('meta-paper-write')).toEqual({
      skillName: 'meta-paper-write',
      launchText: '/meta meta-paper-write',
    })
    expect(parseMetaCommandInvocation('meta-paper-write accidental trailing words')).toEqual({
      skillName: 'meta-paper-write',
      launchText: '/meta meta-paper-write',
    })
  })

  it('passes the full launch through dependency setup', async () => {
    const call = vi.fn(async () => ({
      ok: false,
      setup_required: true,
      readiness: { missing_bins: ['xelatex'] },
    }))
    const requestMetaSetup = vi.fn()
    const { api } = harness(call, requestMetaSetup)

    api.selectSlashCmd(
      META_COMMAND,
      'meta-paper-write -- Produce a ten-page literature review',
    )
    await Promise.resolve()
    await Promise.resolve()

    expect(requestMetaSetup).toHaveBeenCalledWith(
      'meta-paper-write',
      { missing_bins: ['xelatex'] },
      'agent:main:test',
      '/meta meta-paper-write -- Produce a ten-page literature review',
      expect.any(String),
    )
  })

  it('tells the user when a busy setup leaves the stable request pending', async () => {
    const call = vi.fn(async () => ({
      ok: false,
      drafted: true,
      setup_required: true,
      readiness: { missing_bins: ['ffmpeg'] },
    }))
    const requestMetaSetup = vi.fn(async () => 'deferred' as const)
    const { api, notify, restoreDraft } = harness(call, requestMetaSetup)

    api.selectSlashCmd(META_COMMAND, 'meta-short-drama -- wait behind current setup')
    await vi.waitFor(() => expect(notify).toHaveBeenCalledOnce())

    expect(notify.mock.calls[0]?.[0]).toContain('saved with its original identity')
    expect(restoreDraft).not.toHaveBeenCalled()
  })

  it('shows missing dependencies and does not dispatch a hidden turn', async () => {
    const call = vi.fn(async () => ({
      ok: false,
      setup_required: true,
      readiness: { missing_bins: ['xelatex', 'bibtex'] },
    }))
    const { api, notify, dispatchHidden } = harness(call)

    api.selectSlashCmd(META_COMMAND, 'meta-paper-write')
    await Promise.resolve()
    await Promise.resolve()

    expect(call).toHaveBeenCalledWith('meta.run', {
      name: 'meta-paper-write',
      sessionKey: 'agent:main:test',
      clientRequestId: expect.any(String),
      launchText: '/meta meta-paper-write',
    })
    expect(notify).toHaveBeenCalledOnce()
    expect(notify.mock.calls[0][0]).toContain('xelatex, bibtex')
    expect(dispatchHidden).not.toHaveBeenCalled()
  })

  it('preserves readiness status on slash argument candidates', async () => {
    const call = vi.fn(async (method: string) => {
      if (method !== 'commands.list_for_surface') throw new Error(`unexpected ${method}`)
      return {
        commands: [{
          ...META_COMMAND,
          argument_choices: [{
            value: 'meta-paper-write',
            description: 'Paper workflow',
            status: 'needs_setup',
            missing_bins: ['xelatex'],
          }],
        }],
      }
    })
    const { api, inputText } = harness(call)

    await api.loadSlashCommands()
    inputText.value = '/meta '
    api.handleSlashInput()

    expect(api.filteredSlashCmds.value).toHaveLength(1)
    expect(api.filteredSlashCmds.value[0].metaStatus).toBe('needs_setup')
    expect(api.filteredSlashCmds.value[0].missingBins).toEqual(['xelatex'])
  })

  it('persists a delayed ready response for its originating chat', async () => {
    const result = { ok: true }
    let resolveRun: (value: typeof result) => void = () => undefined
    const call = vi.fn(() => new Promise<typeof result>((resolve) => {
      resolveRun = resolve
    }))
    const requestMetaSetup = vi.fn()
    const { api, dispatchHidden, notify, sessionKey } = harness(call, requestMetaSetup)

    api.selectSlashCmd(META_COMMAND, 'meta-paper-write')
    sessionKey.value = 'agent:main:another-chat'
    resolveRun(result)
    await Promise.resolve()
    await Promise.resolve()

    expect(call).toHaveBeenCalledWith('meta.run', {
      name: 'meta-paper-write',
      sessionKey: 'agent:main:test',
      clientRequestId: expect.any(String),
      launchText: '/meta meta-paper-write',
    })
    expect(dispatchHidden).toHaveBeenCalledWith(
      '/meta meta-paper-write',
      '/meta meta-paper-write',
      expect.any(String),
      'agent:main:test',
    )
    expect(requestMetaSetup).not.toHaveBeenCalled()
    expect(notify).not.toHaveBeenCalled()
  })

  it('persists delayed setup readiness for its originating chat', async () => {
    const result = {
      ok: false,
      setup_required: true,
      readiness: { missing_bins: ['xelatex'] },
    }
    let resolveRun: (value: typeof result) => void = () => undefined
    const call = vi.fn(() => new Promise<typeof result>((resolve) => {
      resolveRun = resolve
    }))
    const requestMetaSetup = vi.fn()
    const { api, dispatchHidden, sessionKey } = harness(call, requestMetaSetup)

    api.selectSlashCmd(META_COMMAND, 'meta-paper-write -- delayed request')
    sessionKey.value = 'agent:main:another-chat'
    resolveRun(result)
    await Promise.resolve()
    await Promise.resolve()

    expect(dispatchHidden).not.toHaveBeenCalled()
    expect(requestMetaSetup).toHaveBeenCalledWith(
      'meta-paper-write',
      { missing_bins: ['xelatex'] },
      'agent:main:test',
      '/meta meta-paper-write -- delayed request',
      expect.any(String),
    )
  })

  it('resumes a server draft after an app reopen with the same request identity', async () => {
    const call = vi.fn(async () => ({
      ok: false,
      setup_required: true,
      readiness: { missing_bins: ['xelatex'] },
    }))
    const requestMetaSetup = vi.fn()
    const { api } = harness(call, requestMetaSetup)
    const draft = {
      sessionKey: 'agent:main:test',
      clientRequestId: 'server-durable-request',
      name: 'meta-paper-write',
      launchText: '/meta meta-paper-write -- exact request after reopen',
      createdAt: 100,
      expiresAt: 200,
      sessionExists: false,
    }

    await api.restoreDurableMetaDrafts([draft])

    expect(call).toHaveBeenCalledWith('meta.run', {
      name: draft.name,
      sessionKey: draft.sessionKey,
      clientRequestId: draft.clientRequestId,
      launchText: draft.launchText,
    })
    expect(requestMetaSetup).toHaveBeenCalledWith(
      draft.name,
      { missing_bins: ['xelatex'] },
      draft.sessionKey,
      draft.launchText,
      draft.clientRequestId,
    )
  })

  it('does not resurrect a durable draft cancelled by another tab', async () => {
    const discarded = Object.assign(new Error('The saved request was already discarded.'), {
      code: 'META_DRAFT_DISCARDED',
      retryable: false,
      accepted: false,
    })
    const requestMetaSetup = vi.fn()
    let runCount = 0
    const { api, dispatchHidden, notify, restoreDraft } = harness(
      vi.fn(async () => {
        runCount += 1
        if (runCount === 1) throw discarded
        return { ok: true }
      }),
      requestMetaSetup,
    )
    const draft = {
      sessionKey: 'agent:main:test',
      clientRequestId: 'cancelled-in-another-tab',
      name: 'meta-short-drama',
      launchText: '/meta meta-short-drama -- cancelled elsewhere',
      createdAt: 100,
      expiresAt: 200,
      sessionExists: true,
    }

    const liveDraft = {
      ...draft,
      clientRequestId: 'still-live-in-server-outbox',
      launchText: '/meta meta-short-drama -- still live',
    }
    const attempted = await api.restoreDurableMetaDrafts([draft, liveDraft])

    expect(attempted).toEqual([draft.clientRequestId, liveDraft.clientRequestId])
    expect(requestMetaSetup).not.toHaveBeenCalled()
    expect(dispatchHidden).toHaveBeenCalledWith(
      liveDraft.launchText,
      liveDraft.launchText,
      liveDraft.clientRequestId,
      liveDraft.sessionKey,
    )
    expect(restoreDraft).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledOnce()
    expect(notify.mock.calls[0]?.[0]).toContain('already discarded')
  })

  it('stops a multi-draft restore when its lifecycle guard becomes stale', async () => {
    let resolveFirst: ((value: { ok: boolean }) => void) | undefined
    const first = new Promise<{ ok: boolean }>((resolve) => { resolveFirst = resolve })
    const call = vi.fn()
      .mockImplementationOnce(() => first)
      .mockResolvedValue({ ok: true })
    const { api } = harness(call)
    const drafts = ['first', 'second'].map(clientRequestId => ({
      sessionKey: 'agent:main:test',
      clientRequestId,
      name: 'meta-paper-write',
      launchText: `/meta meta-paper-write -- ${clientRequestId}`,
      createdAt: 100,
      expiresAt: 200,
      sessionExists: true,
    }))
    let current = true

    const restoring = api.restoreDurableMetaDrafts(drafts, () => current)
    await vi.waitFor(() => expect(call).toHaveBeenCalledOnce())
    current = false
    resolveFirst?.({ ok: true })
    await restoring

    expect(call).toHaveBeenCalledOnce()
  })

  it('restores only a rejection that happened before server draft ownership', async () => {
    const rejected = harness(vi.fn(async () => ({ ok: false, error: 'Not available' })))
    rejected.api.selectSlashCmd(META_COMMAND, 'meta-paper-write -- rejected request')
    await Promise.resolve()
    await Promise.resolve()
    expect(rejected.restoreDraft).toHaveBeenCalledWith(
      '/meta meta-paper-write -- rejected request',
      'agent:main:test',
    )

    const requestMetaSetup = vi.fn()
    const failed = harness(
      vi.fn(async () => { throw new Error('offline') }),
      requestMetaSetup,
    )
    failed.api.selectSlashCmd(META_COMMAND, 'meta-short-drama -- offline request')
    await vi.waitFor(() => {
      expect(requestMetaSetup).toHaveBeenCalledWith(
        'meta-short-drama',
        expect.objectContaining({ reasons: ['offline'] }),
        'agent:main:test',
        '/meta meta-short-drama -- offline request',
        expect.any(String),
      )
    })
    expect(failed.restoreDraft).not.toHaveBeenCalled()
  })

  it('keeps the same id pending when hidden-control persistence rejects the launch', async () => {
    const call = vi.fn(async () => ({ ok: true, drafted: true }))
    const requestMetaSetup = vi.fn()
    const { api, dispatchHidden, restoreDraft } = harness(call, requestMetaSetup)
    dispatchHidden.mockResolvedValue({
      status: 'rejected',
      reason: 'outbox_persist_failed',
      clientRequestId: 'request-id',
      sessionKey: 'agent:main:test',
    })

    api.selectSlashCmd(META_COMMAND, 'meta-paper-write -- keep rejected dispatch')
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    expect(requestMetaSetup).toHaveBeenCalledWith(
      'meta-paper-write',
      expect.objectContaining({ reasons: ['outbox_persist_failed'] }),
      'agent:main:test',
      '/meta meta-paper-write -- keep rejected dispatch',
      expect.any(String),
    )
    expect(restoreDraft).not.toHaveBeenCalled()
  })

  it('keeps a drafted business failure under its stable retry identity', async () => {
    const requestMetaSetup = vi.fn()
    const { api, restoreDraft } = harness(vi.fn(async () => ({
      ok: false,
      drafted: true,
      error: 'launch ledger busy',
    })), requestMetaSetup)

    api.selectSlashCmd(META_COMMAND, 'meta-short-drama -- keep this stable')
    await vi.waitFor(() => expect(requestMetaSetup).toHaveBeenCalledWith(
      'meta-short-drama',
      expect.objectContaining({ reasons: ['launch ledger busy'] }),
      'agent:main:test',
      '/meta meta-short-drama -- keep this stable',
      expect.any(String),
    ))
    expect(restoreDraft).not.toHaveBeenCalled()
  })
})
