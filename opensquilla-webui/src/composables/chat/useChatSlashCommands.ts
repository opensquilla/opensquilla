import { ref, type Ref } from 'vue'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface ChatSlashCommand {
  name: string
  cmd: string
  label: string
  desc: string
  aliases: string[]
  execution?: {
    action?: string
  }
  [key: string]: unknown
}

interface SlashCommandPayload extends Record<string, unknown> {
  name?: string
  cmd?: string
  label?: string
  description?: string
  desc?: string
  usage?: string
  aliases?: unknown
  execution?: {
    action?: string
  }
}

interface UsageStatusResult {
  totals?: {
    tokens?: number
  }
  totalTokens?: number
  total_tokens?: number
}

export interface UseChatSlashCommandsOptions {
  rpc: RpcClient
  inputText: Ref<string>
  sessionKey: Ref<string>
  autoResizeTextarea: () => void
  newSession: () => void
  resetCurrentSession: () => void
  setCompactInFlight: (active: boolean, key?: string) => void
  showCompactStatus: (status: string, message: string, options?: { tone?: string; detail?: string; dismissMs?: number }) => void
}

function slashCommandKey(value: string): string {
  const raw = String(value || '').trim().split(/\s+/, 1)[0].toLowerCase()
  if (!raw) return ''
  return raw.startsWith('/') ? raw : '/' + raw
}

function normalizeSlashCommand(cmd: SlashCommandPayload): ChatSlashCommand {
  const name = cmd?.name || cmd?.cmd || ''
  return {
    ...cmd,
    name,
    cmd: name,
    label: cmd?.label || name,
    desc: cmd?.description || cmd?.desc || cmd?.usage || '',
    aliases: Array.isArray(cmd?.aliases) ? cmd.aliases : [],
  }
}

export function useChatSlashCommands(options: UseChatSlashCommandsOptions) {
  const slashOpen = ref(false)
  const slashIdx = ref(0)
  const slashCmds = ref<ChatSlashCommand[]>([])
  const filteredSlashCmds = ref<ChatSlashCommand[]>([])
  const slashCatalogLoaded = ref(false)

  async function loadSlashCommands() {
    try {
      await options.rpc.waitForConnection()
      const res = await options.rpc.call<{ commands?: ChatSlashCommand[] }>('commands.list_for_surface', { surface: 'web_chat' })
      slashCmds.value = (Array.isArray(res?.commands) ? res.commands : []).map(normalizeSlashCommand)
      slashCatalogLoaded.value = true
    } catch {
      slashCmds.value = []
      slashCatalogLoaded.value = false
    }
  }

  function handleSlashInput() {
    const val = options.inputText.value
    if (val.startsWith('//')) {
      closeSlashMenu()
      return
    }
    if (val.startsWith('/') && !val.includes(' ')) {
      const query = val.slice(1).toLowerCase()
      filteredSlashCmds.value = slashCmds.value.filter(c => c.cmd.slice(1).startsWith(query))
      if (filteredSlashCmds.value.length > 0) {
        slashOpen.value = true
        slashIdx.value = 0
        return
      }
    }
    closeSlashMenu()
  }

  function closeSlashMenu() {
    slashOpen.value = false
    filteredSlashCmds.value = []
  }

  function selectSlashCmd(cmd: ChatSlashCommand, _args = '') {
    closeSlashMenu()
    options.inputText.value = ''
    options.autoResizeTextarea()

    const action = cmd?.execution?.action || cmd.cmd || cmd.name
    switch (action) {
      case 'new_chat':
      case '/new':
        options.newSession()
        break
      case 'reset_session':
      case 'sessions.reset':
      case '/reset':
        options.rpc.call('sessions.reset', { key: options.sessionKey.value })
          .then(() => {
            options.resetCurrentSession()
            console.info('Session reset')
          })
          .catch((err: unknown) => console.warn('Reset failed:', err instanceof Error ? err.message : String(err)))
        break
      case 'compact_context':
      case 'sessions.contextCompact':
      case '/compact': {
        const compactKey = options.sessionKey.value
        options.setCompactInFlight(true, compactKey)
        options.showCompactStatus('started', 'Compacting context...', { tone: 'info' })
        options.rpc.call('sessions.contextCompact', { key: compactKey })
          .then(() => {
            if (compactKey !== options.sessionKey.value) return
            options.showCompactStatus('completed', 'Context compacted', { tone: 'ok', dismissMs: 5000 })
          })
          .catch((err: unknown) => {
            if (compactKey !== options.sessionKey.value) return
            options.showCompactStatus('failed', 'Compact failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'err', dismissMs: 10000 })
          })
        break
      }
      case 'usage_status':
      case 'usage.status':
      case '/usage':
        options.rpc.call<UsageStatusResult>('usage.status')
          .then((result: UsageStatusResult) => {
            const totals = result?.totals || {}
            const tokens = Number(result?.totalTokens ?? result?.total_tokens ?? totals.tokens ?? 0)
            console.info(`Usage: ${tokens.toLocaleString()} tokens`)
          })
          .catch((err: unknown) => console.warn('Usage failed:', err instanceof Error ? err.message : String(err)))
        break
    }
  }

  async function executeSlashCommand(text: string): Promise<boolean> {
    if (!slashCatalogLoaded.value) await loadSlashCommands()
    const [cmdText, ...rest] = text.trim().split(/\s+/)
    const cmd = slashCmds.value.find(c => slashCommandKey(c.name) === slashCommandKey(cmdText))
    if (!cmd) {
      closeSlashMenu()
      console.warn('Unsupported command:', cmdText)
      return true
    }
    selectSlashCmd(cmd, rest.join(' '))
    return true
  }

  return {
    slashOpen,
    slashIdx,
    filteredSlashCmds,
    loadSlashCommands,
    handleSlashInput,
    closeSlashMenu,
    selectSlashCmd,
    executeSlashCommand,
  }
}
