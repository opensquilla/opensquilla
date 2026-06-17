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
  // Surface a short, client-side notice (e.g. the meta-skill list). No LLM call.
  notify: (message: string) => void
  // Send a turn whose provider text bypasses slash parsing (mirrors the TUI
  // override path). Used by /meta <name> to trigger the launch after meta.run.
  dispatchHidden: (providerText: string, displayText: string) => void
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

  function selectSlashCmd(cmd: ChatSlashCommand, args = '') {
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
          })
          .catch((err: unknown) => console.warn('Reset failed:', err instanceof Error ? err.message : String(err)))
        break
      case 'compact_context':
      case 'sessions.contextCompact':
      case '/compact': {
        const compactKey = options.sessionKey.value
        options.setCompactInFlight(true, compactKey)
        options.showCompactStatus('started', 'Compacting context', { tone: 'info' })
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
      case 'meta.menu': {
        const skillName = String(args || '').trim()
        if (!skillName) {
          // /meta with no argument → list the available meta-skills (no LLM).
          options.rpc.call<{ skills?: Array<{ name?: string }>; disabled?: boolean }>('meta.list')
            .then((result) => {
              const skills = Array.isArray(result?.skills) ? result.skills : []
              if (result?.disabled || skills.length === 0) {
                options.notify('No meta-skills available.')
                return
              }
              const names = skills.map(s => s?.name).filter(Boolean).join(', ')
              options.notify('Meta-skills: ' + names + ' — run one with /meta <name>')
            })
            .catch((err: unknown) => options.notify('Could not list meta-skills: ' + (err instanceof Error ? err.message : String(err))))
        } else {
          // /meta <name> → stamp the launch, then trigger a turn so the
          // pipeline seeds the marker and the orchestrator runs the skill.
          options.rpc.call<{ ok?: boolean; error?: string }>('meta.run', { name: skillName, sessionKey: options.sessionKey.value })
            .then((result) => {
              if (result?.ok) {
                options.dispatchHidden('/meta ' + skillName, '/meta ' + skillName)
              } else {
                options.notify(result?.error || ('Could not run meta-skill ' + skillName + '.'))
              }
            })
            .catch((err: unknown) => options.notify('Could not run meta-skill: ' + (err instanceof Error ? err.message : String(err))))
        }
        break
      }
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
