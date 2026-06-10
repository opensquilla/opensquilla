import type { Ref } from 'vue'
import type { ChatRenderedMessage } from '@/types/chat'
import { downloadText } from '@/utils/browser'
import { artifactMeta, artifactName } from '@/utils/chat/artifacts'

export interface UseChatMarkdownExportOptions {
  messages: Readonly<Ref<ChatRenderedMessage[]>>
  currentTitle: Readonly<Ref<string>>
}

function markdownFilename(title: string): string {
  const slug = String(title || 'chat')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 36) || 'chat'
  return `opensquilla-chat-${slug}-${new Date().toISOString().slice(0, 10)}.md`
}

function markdownEscape(text: string): string {
  return String(text || '').replace(/\r\n/g, '\n').trim()
}

export function useChatMarkdownExport(options: UseChatMarkdownExportOptions) {
  function exportMarkdown() {
    const lines: string[] = [
      `# ${options.currentTitle.value || 'OpenSquilla chat'}`,
      '',
      `Exported: ${new Date().toISOString()}`,
      '',
    ]
    for (const message of options.messages.value) {
      if (message.isRouterStrip) {
        const winner = message.gridCells?.[message.winnerIdx ?? -1]
        if (winner) lines.push(`> Router selected ${winner.displayName || winner.model || winner.tier}`)
        continue
      }
      if (!['user', 'assistant', 'system', 'subagent', 'error'].includes(message.displayRole || message.role)) continue
      lines.push(`## ${message.roleLabel || message.displayRole || message.role}`)
      if (message.timeStr) lines.push(`_${message.timeStr}_`)
      if (message.text) {
        lines.push('', markdownEscape(message.text))
      }
      if (message.artifacts?.length) {
        lines.push('', 'Artifacts:')
        for (const artifact of message.artifacts) {
          const meta = artifactMeta(artifact)
          lines.push(`- ${artifactName(artifact)}${meta ? ` (${meta})` : ''}`)
        }
      }
      lines.push('')
    }
    downloadText(markdownFilename(options.currentTitle.value), 'text/markdown;charset=utf-8', lines.join('\n'))
  }

  return {
    exportMarkdown,
  }
}
