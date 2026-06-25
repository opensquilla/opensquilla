import { computed, type Ref } from 'vue'

export interface ReadinessSectionDetail {
  status?: string
  blocking?: boolean
  actionRequired?: boolean
  required?: boolean
  label?: string
  detail?: string
}

export interface ReadinessStatus {
  needsOnboarding?: boolean
  hasConfig?: boolean
  llmSource?: string
  sectionDetails?: Record<string, ReadinessSectionDetail>
}

/** Pure predicate shared by the Settings dialog and the sidebar banner. */
export function readinessNeedsAction(status: ReadinessStatus | null | undefined): boolean {
  if (!status) return false
  if (status.needsOnboarding) return true
  if (status.llmSource === 'missing_env') return true
  const details = status.sectionDetails || {}
  return Object.values(details).some((d) =>
    d.blocking || d.actionRequired || d.status === 'missing' || d.status === 'degraded')
}

/** Headline action count for the banner. */
export function readinessActionCount(status: ReadinessStatus | null | undefined): number {
  if (!status) return 0
  const details = status.sectionDetails || {}
  let n = Object.values(details).filter((d) =>
    d.blocking || d.actionRequired || d.status === 'missing' || d.status === 'degraded').length
  if (status.llmSource === 'missing_env' && !details.llm && !details.provider) n += 1
  if (status.needsOnboarding && n === 0) n = 1
  return n
}

export function useReadinessSummary(status: Ref<ReadinessStatus | null>) {
  const needsAction = computed(() => readinessNeedsAction(status.value))
  const actionCount = computed(() => readinessActionCount(status.value))
  return { needsAction, actionCount }
}
