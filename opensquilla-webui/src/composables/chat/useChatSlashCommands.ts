import { ref, type Ref } from 'vue'
import i18n from '@/i18n'
import type { RpcClientError } from '@/lib/rpc'
import type { HiddenControlDispatchResult } from '@/types/chat'
import type { MetaSetupReadiness } from '@/types/metaSetup'
import type { MetaLaunchDraftPayload } from '@/types/rpc'
import { createClientRequestId } from '@/utils/chat/messageIdentity'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface ArgumentChoice {
  value: string
  description: string
  status?: 'ready' | 'needs_setup'
  missingBins?: string[]
  missingEnv?: string[]
  missingEnvAny?: string[][]
  missingSkills?: string[]
  missingCapabilities?: string[]
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
  metaStatus?: 'ready' | 'needs_setup'
  missingBins?: string[]
  missingEnv?: string[]
  missingEnvAny?: string[][]
  missingSkills?: string[]
  missingCapabilities?: string[]
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
  dispatchHidden: (
    providerText: string,
    displayText: string,
    clientRequestId?: string,
    targetSessionKey?: string,
  ) => void | HiddenControlDispatchResult | Promise<void | HiddenControlDispatchResult>
  // Recover a request removed from the composer when launch cannot proceed.
  // The callback owns same-session queueing and cross-session persistence.
  restoreDraft?: (launchText: string, sessionKey: string) => void
  // Open a persistent, explicitly-confirmed setup flow. Older embeddings can
  // omit this callback and keep the compact toast fallback.
  requestMetaSetup?: (
    name: string,
    readiness: MetaSetupReadiness,
    originatingSessionKey: string,
    launchText: string,
    clientRequestId?: string,
  ) => void | 'visible' | 'deferred' | Promise<void | 'visible' | 'deferred'>
}

export interface MetaCommandInvocation {
  skillName: string
  launchText: string
}

export type DurableMetaDraft = MetaLaunchDraftPayload

export function parseMetaCommandInvocation(args: string): MetaCommandInvocation | null {
  const trimmed = String(args || '').trim()
  if (!trimmed) return null

  const firstWhitespace = trimmed.search(/\s/)
  const skillName = firstWhitespace === -1 ? trimmed : trimmed.slice(0, firstWhitespace)
  const suffix = firstWhitespace === -1 ? '' : trimmed.slice(firstWhitespace).trim()
  const requestMatch = suffix.match(/^--(?:\s+([\s\S]*))?$/)
  const request = requestMatch ? String(requestMatch[1] || '').trim() : ''
  return {
    skillName,
    launchText: request ? `/meta ${skillName} -- ${request}` : `/meta ${skillName}`,
  }
}

function slashCommandKey(value: string): string {
  const raw = String(value || '').trim().split(/\s+/, 1)[0].toLowerCase()
  if (!raw) return ''
  return raw.startsWith('/') ? raw : '/' + raw
}

function normalizeSlashCommand(cmd: SlashCommandPayload): ChatSlashCommand {
  const name = cmd?.name || cmd?.cmd || ''
  const rawChoices = Array.isArray((cmd as { argument_choices?: unknown })?.argument_choices)
    ? (cmd as { argument_choices: Array<Record<string, unknown>> }).argument_choices
    : []
  return {
    ...cmd,
    name,
    cmd: name,
    label: cmd?.label || name,
    desc: cmd?.description || cmd?.desc || cmd?.usage || '',
    aliases: Array.isArray(cmd?.aliases) ? cmd.aliases : [],
    argumentChoices: rawChoices
      .map((c) => ({
        value: String(c?.value ?? ''),
        description: String(c?.description ?? ''),
        status: c?.status === 'needs_setup' ? 'needs_setup' as const : 'ready' as const,
        missingBins: Array.isArray(c?.missing_bins) ? c.missing_bins.map(String) : [],
        missingEnv: Array.isArray(c?.missing_env) ? c.missing_env.map(String) : [],
        missingEnvAny: Array.isArray(c?.missing_env_any)
          ? c.missing_env_any.map(group => Array.isArray(group) ? group.map(String) : [])
          : [],
        missingSkills: Array.isArray(c?.missing_skills) ? c.missing_skills.map(String) : [],
        missingCapabilities: Array.isArray(c?.missing_capabilities)
          ? c.missing_capabilities.map(String)
          : [],
      }))
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
    metaStatus: choice.status,
    missingBins: choice.missingBins,
    missingEnv: choice.missingEnv,
    missingEnvAny: choice.missingEnvAny,
    missingSkills: choice.missingSkills,
    missingCapabilities: choice.missingCapabilities,
  }
}

export function useChatSlashCommands(options: UseChatSlashCommandsOptions) {
  const slashOpen = ref(false)
  const slashIdx = ref(0)
  const slashCmds = ref<ChatSlashCommand[]>([])
  const filteredSlashCmds = ref<ChatSlashCommand[]>([])
  const slashCatalogLoaded = ref(false)

  async function runMetaInvocation(input: {
    skillName: string
    launchText: string
    originatingSessionKey: string
    clientRequestId: string
  }): Promise<'accepted' | 'queued' | 'setup' | 'failed' | 'discarded'> {
    const {
      skillName,
      launchText,
      originatingSessionKey,
      clientRequestId,
    } = input
    const retainStableRetry = async (error: string): Promise<void> => {
      if (options.requestMetaSetup) {
        try {
          const disposition = await options.requestMetaSetup(
            skillName,
            {
              ready: false,
              status: 'needs_setup',
              reasons: [error],
              setup_actions: [],
              manual_setup_actions: [],
            },
            originatingSessionKey,
            launchText,
            clientRequestId,
          )
          if (disposition === 'deferred') {
            options.notify(i18n.global.t('chat.metaRuns.savedForRetry', { skill: skillName }))
          }
          return
        } catch {
          // The Gateway outbox still owns this identity. Fall through to an
          // explicit notice, never to ordinary composer text with a new id.
        }
      }
      options.notify(i18n.global.t('chat.metaRuns.couldNotRunSkillError', { error }))
    }
    try {
      const result = await options.rpc.call<{
        ok?: boolean
        error?: string
        drafted?: boolean
        setup_required?: boolean
        readiness?: MetaSetupReadiness
      }>('meta.run', {
        name: skillName,
        sessionKey: originatingSessionKey,
        clientRequestId,
        launchText,
      })
      if (result?.ok) {
        const dispatchResult = await options.dispatchHidden(
          launchText,
          launchText,
          clientRequestId,
          originatingSessionKey,
        )
        if (dispatchResult?.status === 'rejected') {
          await retainStableRetry(dispatchResult.reason)
          return 'failed'
        }
        if (dispatchResult?.status === 'unknown') {
          // The server and browser outboxes retain the exact id and payload.
          // Surface uncertainty without creating a second sendable draft.
          options.notify(i18n.global.t('chat.metaRuns.couldNotRunSkillError', {
            error: dispatchResult.reason,
          }))
          return 'queued'
        }
        return dispatchResult?.status === 'queued' ? 'queued' : 'accepted'
      }
      if (result?.setup_required) {
        const readiness = result.readiness || {}
        if (options.requestMetaSetup) {
          const disposition = await options.requestMetaSetup(
            skillName,
            readiness,
            originatingSessionKey,
            launchText,
            clientRequestId,
          )
          if (disposition === 'deferred') {
            options.notify(i18n.global.t('chat.metaRuns.savedForRetry', { skill: skillName }))
          }
          return 'setup'
        }
        const dependencies = [
          ...(readiness.missing_bins || []),
          ...(readiness.missing_env || []),
          ...(readiness.missing_env_any || []).map(group => group.join(' / ')),
          ...(readiness.missing_skills || []),
          ...(readiness.missing_capabilities || []),
        ].join(', ') || i18n.global.t('chat.metaRuns.unknownDependency')
        options.notify(i18n.global.t('chat.metaRuns.setupRequired', {
          skill: skillName,
          dependencies,
        }))
        return 'setup'
      }
      const error = result?.error
        || i18n.global.t('chat.metaRuns.couldNotRunSkill', { skill: skillName })
      if (result?.drafted) {
        await retainStableRetry(error)
        return 'failed'
      }
      // Disabled/unknown skills are rejected before the Gateway stages a raw
      // request, so returning those to the composer cannot create two ids.
      options.restoreDraft?.(launchText, originatingSessionKey)
      options.notify(
        error,
      )
      return 'failed'
    } catch (err: unknown) {
      const rpcError = err as RpcClientError | undefined
      if (rpcError?.code === 'META_DRAFT_DISCARDED') {
        // Another tab already committed the user's cancellation. This identity
        // is terminal: never recreate a setup card or a sendable composer copy.
        options.notify(i18n.global.t('chat.metaRuns.couldNotRunSkillError', {
          error: rpcError.message,
        }))
        return 'discarded'
      }
      // A transport error can happen after the Gateway commits the draft. Keep
      // the same request id in a retry card; restoring plain text would race
      // server recovery and create a second logical request.
      await retainStableRetry(err instanceof Error ? err.message : String(err))
      return 'failed'
    }
  }

  async function restoreDurableMetaDrafts(drafts: DurableMetaDraft[]): Promise<string[]> {
    const attemptedRequestIds: string[] = []
    for (const draft of drafts) {
      if (draft.sessionKey !== options.sessionKey.value) return attemptedRequestIds
      if (
        !draft.name
        || !draft.launchText
        || !/^\S{1,256}$/.test(draft.clientRequestId)
      ) continue
      attemptedRequestIds.push(draft.clientRequestId)
      const outcome = await runMetaInvocation({
        skillName: draft.name,
        launchText: draft.launchText,
        originatingSessionKey: draft.sessionKey,
        clientRequestId: draft.clientRequestId,
      })
      if (outcome === 'discarded') continue
      // A setup card or queued hidden turn owns the next user-visible slot.
      // Remaining server drafts stay durable and will be resumed later.
      if (outcome !== 'accepted') return attemptedRequestIds
    }
    return attemptedRequestIds
  }

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
        options.showCompactStatus('started', i18n.global.t('chat.compact.compacting'), { tone: 'info' })
        options.rpc.call('sessions.contextCompact', { key: compactKey })
          .then(() => {
            if (compactKey !== options.sessionKey.value) return
            options.showCompactStatus('completed', i18n.global.t('chat.compact.compacted'), { tone: 'ok', dismissMs: 5000 })
          })
          .catch((err: unknown) => {
            if (compactKey !== options.sessionKey.value) return
            options.showCompactStatus('failed', i18n.global.t('chat.compact.failed') + ': ' + (err instanceof Error ? err.message : String(err)), { tone: 'err', dismissMs: 10000 })
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
        const invocation = parseMetaCommandInvocation(args)
        if (!invocation) break
        const { skillName, launchText } = invocation
        const originatingSessionKey = options.sessionKey.value
        const clientRequestId = createClientRequestId()
        // Save the exact request server-side before readiness/setup and retain
        // its stable identity through the eventual hidden turn.
        void runMetaInvocation({
          skillName,
          launchText,
          originatingSessionKey,
          clientRequestId,
        })
        break
      }
    }
  }

  async function executeSlashCommand(text: string): Promise<boolean> {
    if (!slashCatalogLoaded.value) await loadSlashCommands()
    const trimmed = text.trim()
    const firstWhitespace = trimmed.search(/\s/)
    const cmdText = firstWhitespace === -1 ? trimmed : trimmed.slice(0, firstWhitespace)
    const args = firstWhitespace === -1 ? '' : trimmed.slice(firstWhitespace).trimStart()
    const cmd = slashCmds.value.find(c => slashCommandKey(c.name) === slashCommandKey(cmdText))
    if (!cmd) {
      closeSlashMenu()
      console.warn('Unsupported command:', cmdText)
      return true
    }
    selectSlashCmd(cmd, args)
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
    restoreDurableMetaDrafts,
  }
}
