import type { SidebarSectionFamily, SidebarSectionRow } from '@/composables/useSessions'

export function shouldShowAgentFilterBadge(
  family: SidebarSectionFamily,
  row: Pick<SidebarSectionRow, 'sessionKind' | 'depth'>,
): boolean {
  return family === 'chats' && row.sessionKind !== 'task' && row.depth === 0
}
