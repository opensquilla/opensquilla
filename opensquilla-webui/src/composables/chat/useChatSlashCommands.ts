import { ref, type Ref } from 'vue'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface ArgumentChoice {
  value: string
  description: string
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
  // Tab-completable argument candidates for this command (e.g. meta-skill names).
  argumentChoices?: ArgumentChoice[]
  // Set on synthetic entries that represent a chosen argument ("/meta <skill>").
  argValue?: string
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
  // Surface a short, client-side notice (e.g. the meta-skill list). No provider call.
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
  const rawChoices = Array.isArray((cmd as { argument_choices?: unknown })?.argument_choices)
    ? (cmd as { argument_choices: Array<{ value?: unknown; description?: unknown }> }).argument_choices
    : []
  return {
    ...cmd,
    name,
    cmd: name,
    label: cmd?.label || name,
    desc: cmd?.description || cmd?.desc || cmd?.usage || '',
    aliases: Array.isArray(cmd?.aliases) ? cmd.aliases : [],
    argumentChoices: rawChoices
      .map((c) => ({ value: String(c?.value ?? ''), description: String(c?.description ?? '') }))
      .filter((c) => c.value),
  }
}

function makeArgCandidate(parent: ChatSlashCommand, choice: ArgumentChoice): ChatSlashCommand {
  const full = parent.cmd + ' ' + choice.value
  return {
    name: full,
    cmd: full,
    label: full,
    desc: choice.description,
    aliases: [],
    execution: parent.execution,
    argValue: choice.value,
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

  function openWith(cmds: ChatSlashCommand[]): void {
    filteredSlashCmds.value = cmds
    if (cmds.length > 0) {
      slashOpen.value = true
      slashIdx.value = 0
    } else {
      closeSlashMenu()
    }
  }

  function handleSlashInput() {
    const val = options.inputText.value
    if (val.startsWith('//') || !val.startsWith('/')) {
      closeSlashMenu()
      return
    }
    const firstSpace = val.indexOf(' ')
    if (firstSpace === -1) {
      // Command-name completion: "/me" -> matching commands.
      const query = val.slice(1).toLowerCase()
      openWith(slashCmds.value.filter(c => c.cmd.slice(1).startsWith(query)))
      return
    }
    // Argument completion: "/meta <partial>" -> the command's argument choices.
    const head = '/' + val.slice(1, firstSpace).toLowerCase()
    const partial = val.slice(firstSpace + 1).trimStart().toLowerCase()
    const parent = slashCmds.value.find(c => slashCommandKey(c.name) === slashCommandKey(head))
    const choices = parent?.argumentChoices || []
    if (parent && choices.length > 0) {
      openWith(
        choices
          .filter(ch => ch.value.toLowerCase().startsWith(partial))
          .map(ch => makeArgCandidate(parent, ch)),
      )
      return
    }
    closeSlashMenu()
  }

  function closeSlashMenu() {
    slashOpen.value = false
    filteredSlashCmds.value = []
  }

  function selectSlashCmd(cmd: ChatSlashCommand, args = '') {
    // Argument candidate ("/meta <skill>"): Tab-completes into the composer;
    // the user presses Enter to run it.
    if (cmd.argValue) {
      closeSlashMenu()
      options.inputText.value = cmd.cmd
      options.autoResizeTextarea()
      return
    }
    // A command that takes arguments, selected with none yet: complete to
    // "/cmd " and reopen the menu showing its argument candidates.
    if (!args && (cmd.argumentChoices?.length ?? 0) > 0) {
      closeSlashMenu()
      options.inputText.value = cmd.cmd + ' '
      options.autoResizeTextarea()
      handleSlashInput()
      return
    }

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
        // Bare "/meta" is handled by the argument-completion branch above
        // (it reopens the menu with the skill choices). Here we only reach the
        // run path, with a skill name supplied (e.g. Enter on "/meta <skill>").
        const skillName = String(args || '').trim()
        if (!skillName) break
        // Stamp the launch, then trigger a turn so the pipeline seeds the
        // marker and the orchestrator runs the skill.
        options.rpc.call<{ ok?: boolean; error?: string }>('meta.run', { name: skillName, sessionKey: options.sessionKey.value })
          .then((result) => {
            if (result?.ok) {
              options.dispatchHidden('/meta ' + skillName, '/meta ' + skillName)
            } else {
              options.notify(result?.error || ('Could not run meta-skill ' + skillName + '.'))
            }
          })
          .catch((err: unknown) => options.notify('Could not run meta-skill: ' + (err instanceof Error ? err.message : String(err))))
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
