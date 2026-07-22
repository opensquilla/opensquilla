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
    requestMetaSetup,
  })
  return { api, notify, dispatchHidden, inputText, sessionKey }
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
  it('keeps the request on the hidden turn and sends only the skill token to meta.run', async () => {
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
    })
    expect(dispatchHidden).toHaveBeenCalledWith(
      '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
      '/meta meta-paper-write -- Write a ten-page paper\nwith real cited sources',
      expect.any(String),
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
    )
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

  it.each([
    ['ready response', { ok: true }],
    ['setup response', { ok: false, setup_required: true, readiness: { missing_bins: ['xelatex'] } }],
  ])('does not apply a delayed %s to a newly selected chat', async (_label, result) => {
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
    })
    expect(dispatchHidden).not.toHaveBeenCalled()
    expect(requestMetaSetup).not.toHaveBeenCalled()
    expect(notify).not.toHaveBeenCalled()
  })
})
