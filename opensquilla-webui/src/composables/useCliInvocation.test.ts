import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resetCliInvocationForTest, useCliInvocation } from './useCliInvocation'
import type { CliInvocation } from '@/platform'

const platformMock = {
  capabilities: { hasTerminalWorkflow: false },
  gateway: {} as { getCliInvocation?: () => Promise<CliInvocation | null> },
}

vi.mock('@/platform', () => ({
  usePlatform: () => platformMock,
}))

async function flushLoad() {
  await Promise.resolve()
  await Promise.resolve()
}

const PREFIX =
  "OPENSQUILLA_STATE_DIR='/tmp/state' OPENSQUILLA_GATEWAY_CONFIG_PATH='/tmp/config.toml' '/apps/opensquilla-gateway'"

describe('useCliInvocation', () => {
  beforeEach(() => {
    resetCliInvocationForTest()
    platformMock.capabilities = { hasTerminalWorkflow: false }
    platformMock.gateway = {}
  })

  it('rewrites the leading opensquilla token with the shell prefix', async () => {
    platformMock.gateway.getCliInvocation = async () => ({ mode: 'bundled', prefix: PREFIX })
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla gateway restart --config /tmp/config.toml'))
      .toBe(`${PREFIX} gateway restart --config /tmp/config.toml`)
    expect(format('opensquilla')).toBe(PREFIX)
  })

  it('keeps $-sequences in the prefix literal instead of expanding them', async () => {
    const dollarPrefix =
      "OPENSQUILLA_STATE_DIR='/home/a$$b/state' OPENSQUILLA_GATEWAY_CONFIG_PATH='/srv/x$' '/opt/gw'"
    platformMock.gateway.getCliInvocation = async () => ({ mode: 'bundled', prefix: dollarPrefix })
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla gateway restart')).toBe(`${dollarPrefix} gateway restart`)
  })

  it('rewrites only the leading token, never embedded mentions', async () => {
    platformMock.gateway.getCliInvocation = async () => ({ mode: 'bundled', prefix: PREFIX })
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla doctor # run opensquilla doctor'))
      .toBe(`${PREFIX} doctor # run opensquilla doctor`)
  })

  it('leaves non-CLI shell lines untouched', async () => {
    platformMock.gateway.getCliInvocation = async () => ({ mode: 'bundled', prefix: PREFIX })
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('export SILICONFLOW_API_KEY=sk-demo')).toBe('export SILICONFLOW_API_KEY=sk-demo')
    expect(format('opensquillax doctor')).toBe('opensquillax doctor')
  })

  it('is the identity on hosts with a terminal workflow (web)', async () => {
    platformMock.capabilities = { hasTerminalWorkflow: true }
    const spy = vi.fn(async () => ({ mode: 'bundled' as const, prefix: PREFIX }))
    platformMock.gateway.getCliInvocation = spy
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla doctor --json')).toBe('opensquilla doctor --json')
    expect(spy).not.toHaveBeenCalled()
  })

  it('degrades to the identity when the bridge method is missing', async () => {
    const { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla doctor --json')).toBe('opensquilla doctor --json')
  })

  it('degrades to the identity when the bridge lookup fails or is empty', async () => {
    platformMock.gateway.getCliInvocation = async () => {
      throw new Error('ipc broke')
    }
    let { format } = useCliInvocation()
    await flushLoad()
    expect(format('opensquilla doctor')).toBe('opensquilla doctor')

    resetCliInvocationForTest()
    platformMock.gateway.getCliInvocation = async () => null
    ;({ format } = useCliInvocation())
    await flushLoad()
    expect(format('opensquilla doctor')).toBe('opensquilla doctor')
  })
})
