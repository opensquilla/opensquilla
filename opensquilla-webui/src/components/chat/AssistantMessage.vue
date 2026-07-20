<template>
  <div
    class="msg-ai"
    :class="{
      'msg-ai--share-mode': shareMode && !message.stopNotice,
      'msg-ai--share-selected': shareSelected && !message.stopNotice,
      'msg-ai--stop-notice': message.stopNotice,
    }"
    :data-message-id="message.messageId"
    :data-share-message-id="message.stopNotice ? undefined : shareMessageId"
    :data-share-selected="shareSelected && !message.stopNotice ? 'true' : undefined"
    @click="onMessageClick"
  >
    <button
      v-if="shareMode && !message.stopNotice"
      type="button"
      class="chat-share-picker"
      :class="{ 'is-selected': shareSelected }"
      :aria-pressed="shareSelected"
      :title="shareSelected ? 'Remove from share image' : 'Add to share image'"
      :aria-label="shareSelected ? 'Remove from share image' : 'Add to share image'"
      @click.stop="emit('toggleShare', shareMessageId)"
    >
      <Icon v-if="shareSelected" name="check" :size="13" />
    </button>
    <div class="msg-ai-main">
      <div v-if="!message.stopNotice" class="msg-ai-author">
        <span class="msg-ai-avatar" aria-hidden="true">
          <img src="/opensquilla-assistant-avatar.png" alt="" />
        </span>
      </div>
      <slot v-if="!message.stopNotice" name="router-strip" />
      <details v-if="hasActivityFold" class="activity-fold" @toggle="onActivityFoldToggle">
        <summary
          class="activity-fold__summary"
          data-testid="activity-fold-toggle"
        >
          <Icon class="activity-fold__chevron" name="chevronRight" :size="13" />
          <span class="activity-fold__summary-text">{{ activitySummary }}</span>
          <span v-if="message.isStreaming && hasActivityTools && reasoningSummary" class="activity-fold__summary-meta">{{ reasoningSummary }}</span>
        </summary>
        <div class="activity-fold__body" data-testid="activity-fold-body">
          <section v-if="reasoningPart" class="activity-fold__reasoning-step">
            <button
              type="button"
              class="activity-fold__step-toggle"
              :aria-expanded="activityReasoningOpen ? 'true' : 'false'"
              data-testid="activity-reasoning-toggle"
              @click="toggleActivityReasoning"
            >
              <span class="activity-fold__step-label">{{ reasoningSummary }}</span>
              <Icon
                class="activity-fold__step-chevron"
                :class="{ open: activityReasoningOpen }"
                name="chevronRight"
                :size="13"
              />
            </button>
            <div v-if="activityReasoningOpen" class="activity-fold__reasoning">
              <div class="activity-fold__reasoning-text">{{ reasoningPart.text }}</div>
            </div>
          </section>
          <ToolCallTimeline
            v-if="activityTimelineItems.length"
            class="activity-fold__timeline"
            variant="activity"
            :items="activityTimelineItems"
            :is-tool-group-open="isActivityToolGroupOpen"
            :is-tool-item-open="isActivityToolItemOpen"
            :tool-group-status-text="activityGroupStatusText"
            :tool-status-text="toolStatusText"
            :tool-secondary-text="toolSecondaryText"
            @toggle-group="toggleActivityToolGroup"
            @toggle-item="toggleActivityToolItem"
            @show-result="(content, title, context) => $emit('showToolResult', content, title, context)"
          />
        </div>
      </details>

      <ToolCallTimeline
        v-if="answerTimelineItems.length"
        :items="answerTimelineItems"
        :is-tool-group-open="isToolGroupOpen"
        :is-tool-item-open="isToolItemOpen"
        :tool-group-status-text="toolGroupStatusText"
        :tool-status-text="toolStatusText"
        :tool-secondary-text="toolSecondaryText"
        @toggle-group="$emit('toggleToolGroup', $event)"
        @toggle-item="$emit('toggleToolItem', $event)"
        @show-result="(content, title, context) => $emit('showToolResult', content, title, context)"
      />
      <TextPart
        v-else-if="standaloneTextPart"
        :part="standaloneTextPart"
        :sources="message.sources ?? []"
        @citation="onCitation"
      />

      <!-- Inline interrupts: approval / clarify requests that blocked the run,
           rendered after the body and before the ending deliverables. -->
      <InterruptPart
        v-for="part in interruptParts"
        :key="part.key"
        :part="part"
        @resolve="(id, decision, note) => $emit('resolveInterrupt', id, decision, note)"
        @extend="id => $emit('extendInterrupt', id)"
        @clarify-submit="(fields, request) => $emit('clarifySubmit', fields, request)"
        @clarify-dismiss="$emit('clarifyDismiss')"
      />

      <!-- What the agent did this turn: an expandable activity timeline of the
           accepted phase transitions, shown before the ending deliverables. -->
      <StatusHistoryPart
        v-if="statusHistory.length"
        :entries="statusHistory"
      />

      <div
        class="msg-ai-ending"
        :class="{ 'msg-ai-ending--done': showDoneBlock }"
        :data-testid="showDoneBlock ? 'done-block' : undefined"
      >
        <ChatArtifactList
          v-if="message.artifacts?.length"
          :artifacts="message.artifacts"
          :navigation-artifacts="artifactNavigationItems"
          :session-key="sessionKey"
          :auth-token="authToken"
          @download="$emit('downloadArtifact', $event)"
        />

        <SourcesRow v-if="message.toolCalls?.length" ref="sourcesRowRef" :calls="message.toolCalls" :sources="message.sources ?? []" />

        <div v-if="showFooter" class="msg-ai-footer">
          <div v-if="message.meta" class="msg-ai-meta">
            <span v-if="message.meta.model && !message.meta.ensemble" class="msg-meta__model">{{ message.meta.modelShort }}</span>
            <span v-if="message.meta.costUsd && !message.meta.ensemble" class="msg-meta__cost">${{ message.meta.costUsd.toFixed(6).replace(/\.?0+$/, '') }}</span>
            <span v-if="message.meta.ensemble" class="msg-meta__ensemble">{{ t('chat.msgMeta.ensembleModels', { count: message.meta.ensemble.modelCount }) }}</span>
            <span v-if="message.meta.hasSaved && !message.meta.ensemble" class="savings-indicator">{{ message.meta.savedLabel }}</span>
            <span
              v-if="hasMetaDetails"
              ref="metaMoreRef"
              class="msg-meta__more"
              @mouseenter="metaHovered = true"
              @mouseleave="metaHovered = false"
              @keydown.escape.stop="closeMetaDetails"
              @focusout="onMetaFocusOut"
            >
              <button
                ref="metaTriggerRef"
                type="button"
                class="msg-meta__more-btn"
                :aria-expanded="metaDetailsOpen"
                :aria-controls="metaDetailsId"
                :aria-label="t('chat.usageDetails')"
                @click="metaPinned = !metaPinned"
              >
                <Icon name="info" :size="12" />
              </button>
              <div
                v-if="metaDetailsOpen"
                :id="metaDetailsId"
                class="msg-meta-popover"
                role="group"
                :aria-label="t('chat.usageDetails')"
              >
                <div v-if="message.meta.hasTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">{{ t('chat.msgMeta.tokens') }}</span>
                  <span class="msg-meta-popover__value">&#8593;{{ fmtTok(message.meta.input) }} &#8595;{{ fmtTok(message.meta.output) }}</span>
                </div>
                <div v-if="message.meta.cachedTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">{{ t('chat.msgMeta.cache') }}</span>
                  <span class="msg-meta-popover__value">{{ fmtTok(message.meta.cachedTokens) }}</span>
                </div>
                <div v-if="message.meta.reasoningTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">{{ t('chat.msgMeta.think') }}</span>
                  <span class="msg-meta-popover__value">{{ fmtTok(message.meta.reasoningTokens) }}</span>
                </div>
                <template v-if="message.meta.ensemble">
                  <div class="msg-meta-popover__divider"></div>
                  <div class="msg-meta-popover__row">
                    <span class="msg-meta-popover__label">{{ t('chat.msgMeta.ensemble') }}</span>
                    <span class="msg-meta-popover__value">{{ ensembleSummary }}</span>
                  </div>
                  <div class="msg-meta-popover__row">
                    <span class="msg-meta-popover__label">{{ t('chat.msgMeta.cost') }}</span>
                    <span class="msg-meta-popover__value">{{ fmtUsd(message.meta.ensemble.costUsd || message.meta.costUsd) }}</span>
                  </div>
                  <div v-if="message.meta.ensemble.fallbackUsed" class="msg-meta-popover__row">
                    <span class="msg-meta-popover__label">{{ t('chat.msgMeta.fallback') }}</span>
                    <span class="msg-meta-popover__value">{{ t('chat.msgMeta.fallbackUsed') }}</span>
                  </div>
                  <div class="msg-meta-popover__models" :aria-label="t('chat.msgMeta.ensembleModelsAria')">
                    <div
                      v-for="member in message.meta.ensemble.models"
                      :key="`${member.role}:${member.provider}:${member.model}`"
                      class="msg-meta-popover__model"
                    >
                      <span class="msg-meta-popover__model-role">{{ ensembleRole(member.role, member.label) }}</span>
                      <span class="msg-meta-popover__model-name" :title="member.model">{{ member.modelShort }}</span>
                      <span class="msg-meta-popover__model-cost">{{ fmtUsd(member.costUsd) }}</span>
                    </div>
                  </div>
                </template>
              </div>
            </span>
          </div>
          <div v-if="!shareMode && !message.stopNotice" class="msg-ai-actions">
            <button
              type="button"
              class="msg-action"
              :class="{ 'msg-action--ok': copyState === 'ok', 'msg-action--err': copyState === 'err' }"
              :title="copyTitle"
              :aria-label="copyTitle"
              @click="onCopyClick"
            >
              <Icon :name="copyIconName" :size="12" />
            </button>
            <span class="msg-copy-live" aria-live="polite">{{ copyLiveText }}</span>
            <button type="button" class="msg-action" :title="t('chat.regenerate')" :aria-label="t('chat.regenerate')" @click="$emit('regenerate', message)">
              <Icon name="refresh" :size="12" />
            </button>
            <template v-if="feedbackDecisionId">
              <button
                type="button"
                class="msg-action msg-action--vote"
                :class="{ 'msg-action--ok': feedbackRating === 'up' }"
                :disabled="feedbackBusy"
                :aria-pressed="feedbackRating === 'up'"
                :title="feedbackUpTitle"
                :aria-label="feedbackUpTitle"
                @click="onFeedbackClick('up')"
              >
                <Icon name="thumbs-up" :size="12" />
              </button>
              <button
                type="button"
                class="msg-action msg-action--vote"
                :class="{ 'msg-action--err': feedbackRating === 'down' }"
                :disabled="feedbackBusy"
                :aria-pressed="feedbackRating === 'down'"
                :title="feedbackDownTitle"
                :aria-label="feedbackDownTitle"
                @click="onFeedbackClick('down')"
              >
                <Icon name="thumbs-down" :size="12" />
              </button>
            </template>
            <button
              v-if="isTip"
              type="button"
              class="msg-action msg-action--fork"
              data-testid="fork-conversation"
              :disabled="forkBusy"
              :title="t('chat.forkConversation')"
              :aria-label="t('chat.forkConversation')"
              @click="$emit('fork')"
            >
              <Icon name="fork" :size="12" />
            </button>
            <time v-if="timeIso" class="msg-time" :datetime="timeIso" :title="timeFull">
              <span class="msg-time__abs">{{ timeAbs }}</span>
              <span class="msg-time__dot" aria-hidden="true">·</span>
              <span class="msg-time__rel">{{ timeRel }}</span>
            </time>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import ChatArtifactList from '@/components/chat/ChatArtifactList.vue'
import SourcesRow from '@/components/chat/SourcesRow.vue'
import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import InterruptPart from '@/components/chat/parts/InterruptPart.vue'
import StatusHistoryPart from '@/components/chat/parts/StatusHistoryPart.vue'
import TextPart from '@/components/chat/parts/TextPart.vue'
import { useChatRouteFeedback } from '@/composables/chat/useChatRouteFeedback'
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
import { useRelativeNow } from '@/composables/useRelativeNow'
import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCall,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
  ToolResultContext,
} from '@/types/chat'
import type { ChatPart } from '@/types/parts'
import type { ArtifactPayload } from '@/types/rpc'
import { toolActionLabel, toolOperationKey, toolResultCount } from '@/utils/chat/toolDisplay'
import { absoluteTime, fullTime, isoTime, relativeTime } from '@/utils/messageTime'

const props = defineProps<{
  message: ChatRenderedMessage
  index: number
  turnElapsedSeconds?: number
  shareMode: boolean
  shareSelected: boolean
  shareMessageId: string
  renderMarkdown: (text: string) => string
  fmtTok: (value: number) => string
  toolCallGroups: (calls: ChatToolCall[], baseKey: string) => ChatToolCallGroup[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
  copyMessage: (message: ChatRenderedMessage) => Promise<boolean>
  artifactNavigationItems?: ArtifactPayload[]
  sessionKey?: string
  authToken?: string
  /** True on the thread's last assistant message — the only place the whole-conversation fork action renders. */
  isTip?: boolean
  forkBusy?: boolean
}>()

const emit = defineEmits<{
  regenerate: [message: ChatRenderedMessage]
  toggleShare: [messageId: string]
  downloadArtifact: [artifact: ArtifactPayload]
  toggleToolGroup: [groupId: string]
  toggleToolItem: [renderKey: string]
  showToolResult: [content: string, title: string, context?: ToolResultContext]
  fork: []
  resolveInterrupt: [id: string, decision: 'allow-once' | 'allow-always' | 'deny', note?: string]
  extendInterrupt: [id: string]
  clarifySubmit: [fields: Record<string, string>, request?: NonNullable<Extract<import('@/types/parts').ChatPart, { type: 'interrupt' }>['clarify']>]
  clarifyDismiss: []
}>()

// Absolute label is static; only the relative label subscribes to the shared
// clock, so a tick re-evaluates one cheap computed per visible bubble.
const { t } = useI18n()

// Routing feedback: buttons only exist when the turn carries a V017 decision
// id (router actually decided this turn). The copy differs by execution kind —
// a single-model rating judges the tier choice, an ensemble rating judges the
// aggregated answer (backend excludes it from tier training accordingly).
const routeFeedback = useChatRouteFeedback()
const feedbackDecisionId = computed(() => props.message.meta?.decisionId)
const feedbackRating = computed(() => routeFeedback.ratingFor(feedbackDecisionId.value))
const feedbackBusy = computed(() => routeFeedback.busy(feedbackDecisionId.value))
const feedbackUpTitle = computed(() =>
  props.message.meta?.ensemble ? t('chat.routeFeedback.upEnsemble') : t('chat.routeFeedback.up'),
)
const feedbackDownTitle = computed(() =>
  props.message.meta?.ensemble ? t('chat.routeFeedback.downEnsemble') : t('chat.routeFeedback.down'),
)
function onFeedbackClick(rating: 'up' | 'down') {
  const id = feedbackDecisionId.value
  if (id) void routeFeedback.submit(id, rating)
}

const now = useRelativeNow()
const timeIso = computed(() => isoTime(props.message.ts))
const timeAbs = computed(() => absoluteTime(props.message.ts))
const timeRel = computed(() => relativeTime(props.message.ts, now.value))
const timeFull = computed(() => fullTime(props.message.ts))

// reasoning + standalone text now come pre-folded on message.parts (see toParts).
// The text part already carries pre-rendered, sanitized html, so this component
// no longer re-runs renderMarkdown for the body.
const reasoningPart = computed(
  () =>
    props.message.parts?.find(
      (part): part is Extract<ChatPart, { type: 'reasoning' }> => part.type === 'reasoning',
    ) ?? null,
)
// Standalone text only exists in the no-timeline body: toParts emits a single
// text part (key `${ownerKey}:text`) and never alongside a timeline.
const standaloneTextPart = computed(() =>
  props.message.timelineItems?.length
    ? null
    : props.message.parts?.find(
        (part): part is Extract<ChatPart, { type: 'text' }> => part.type === 'text',
      ) ?? null,
)
// Inline interrupt parts (approval / clarify) fold into the body order after
// text/tools and before the ending; render them through the shared adapter.
const interruptParts = computed(
  () =>
    props.message.parts?.filter(
      (part): part is Extract<ChatPart, { type: 'interrupt' }> => part.type === 'interrupt',
    ) ?? [],
)
// The persisted activity timeline for this finished turn. Empty (fold hidden)
// for OFF-mode turns and reloaded threads, which carry no snapshot.
const statusHistory = computed(() => props.message.statusHistory ?? [])
const showFooter = computed(() => !!props.message.meta || (!props.shareMode && !props.message.stopNotice))

// A citation pill in the body asks the paired SourcesRow to reveal + highlight
// the source it points at. No-op when no SourcesRow is mounted (which only
// happens when there are no sources, so the body has no pills either).
const sourcesRowRef = ref<InstanceType<typeof SourcesRow> | null>(null)
function onCitation(sourceId: number) {
  sourcesRowRef.value?.focusSource(sourceId)
}

const { copyState, copyIconName, copyTitle, copyLiveText, onCopyClick } = useCopyFeedback(
  () => props.copyMessage(props.message),
)

const metaMoreRef = ref<HTMLElement | null>(null)
const metaTriggerRef = ref<HTMLButtonElement | null>(null)
const metaPinned = ref(false)
const metaHovered = ref(false)
const metaDetailsOpen = computed(() => metaPinned.value || metaHovered.value)

// A completed turn that produced artifacts ends with the deliverable block:
// artifact chips, then sources, then the receipt, grouped as one ending.
const showDoneBlock = computed(() =>
  !!props.message.artifacts?.length && !props.message.isStreaming && !props.message.interrupted,
)

const hasMetaDetails = computed(() => {
  const meta = props.message.meta
  if (!meta) return false
  return meta.hasTokens || meta.cachedTokens > 0 || meta.reasoningTokens > 0 || !!meta.ensemble
})

const ensembleSummary = computed(() => {
  const ensemble = props.message.meta?.ensemble
  if (!ensemble) return ''
  const requests = ensemble.requestCount > 0 ? `${ensemble.requestCount} requests` : ''
  const profile = ensemble.profile && ensemble.profile !== 'llm_ensemble' ? ensemble.profile : ''
  return [profile, requests].filter(Boolean).join(' · ') || `${ensemble.modelCount} models`
})

const metaDetailsId = computed(
  () => `msg-meta-details-${props.message.messageId || props.message.id || props.index}`,
)

function closeMetaDetails() {
  if (!metaDetailsOpen.value) return
  metaPinned.value = false
  metaHovered.value = false
  metaTriggerRef.value?.focus()
}

function onMetaFocusOut(event: FocusEvent) {
  const next = event.relatedTarget
  if (next instanceof Node && metaMoreRef.value?.contains(next)) return
  if (next === null) return
  metaPinned.value = false
}

function onDocumentPointerDown(event: PointerEvent) {
  const root = metaMoreRef.value
  if (!root) return
  if (event.target instanceof Node && root.contains(event.target)) return
  metaPinned.value = false
  metaHovered.value = false
}

watch(metaDetailsOpen, open => {
  if (open) document.addEventListener('pointerdown', onDocumentPointerDown, true)
  else document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

const legacyTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
  const calls = props.message.toolCalls || []
  // message.id is always set ("${role}-${sourceIndex}") and equals the
  // composable's ownerKey when messageId is absent, so tool renderKeys match the
  // keys toParts folds. The final term only types the fallback and reconstructs
  // the same owner the composable used; it is unreachable while id is set.
  const baseKey = props.message.messageId || props.message.id || `${props.message.role}-${props.message.sourceIndex}`
  return props.toolCallGroups(calls, baseKey).map(group => ({
    type: 'tool-group',
    key: group.groupId,
    group,
  }))
})

// The persisted/live timeline interleaves narration and tools. The final text
// segment is the answer; everything before it is execution context and belongs
// in the collapsed activity disclosure. This also handles a tool emitted after
// the final text by keeping the answer visually last, which is the most useful
// reading order once the run has completed.
const sourceTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
  if (props.message.timelineItems?.length) return props.message.timelineItems
  return props.message.toolCalls?.length ? legacyTimelineItems.value : []
})

const timelineSplit = computed(() => {
  const items = sourceTimelineItems.value
  const hasTools = items.some(item => item.type === 'tool-group')
  if (!hasTools) return { activity: [] as ChatStreamTimelineItem[], answer: items }

  let finalTextIndex = -1
  for (let index = items.length - 1; index >= 0; index--) {
    if (items[index].type === 'text') {
      finalTextIndex = index
      break
    }
  }
  if (finalTextIndex < 0) return { activity: items, answer: [] as ChatStreamTimelineItem[] }
  return {
    activity: items.filter((_, index) => index !== finalTextIndex),
    answer: [items[finalTextIndex]],
  }
})

const WEB_RESEARCH_OPERATIONS = new Set(['web.search', 'web.read', 'web.discover'])

/** Continuous web search/read retries are one research phase from the user's
 * perspective. Collapse them into one disclosure, omit failed/zero-result
 * attempts, and keep only useful calls in the nested detail. */
const activityTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
  const activity = timelineSplit.value.activity
  const toolItems = activity.filter(
    (item): item is Extract<ChatStreamTimelineItem, { type: 'tool-group' }> => item.type === 'tool-group',
  )
  if (!toolItems.length || !toolItems.every(item => WEB_RESEARCH_OPERATIONS.has(item.group.operationKey))) {
    return activity
  }

  const calls = toolItems.flatMap(item => item.group.calls)
    .filter(call => {
      if (call.isRunning) return true
      if (call.isError || call.status === 'error') return false
      const operation = toolOperationKey(call.name)
      return !(
        (operation === 'web.search' || operation === 'web.discover')
        && toolResultCount(call.result) === 0
      )
    })
    .map(call => ({ ...call, displayName: toolActionLabel(call.name) }))

  if (!calls.length) return []
  const isRunning = calls.some(call => call.isRunning)
  const allDone = calls.every(call => call.status === 'success')
  const group: ChatToolCallGroup = {
    groupId: `${props.message.messageId || props.message.id}:web-research`,
    operationKey: 'web.research',
    label: t('chat.tool.researchWeb'),
    iconName: 'search',
    calls,
    countLabel: props.message.sources?.length
      ? t('shared.runTrace.resultsCount', { count: props.message.sources.length })
      : t('shared.runTrace.callsCount', { count: calls.length }),
    secondary: '',
    isRunning,
    isError: false,
    status: allDone ? 'success' : '',
  }
  return [{ type: 'tool-group', key: group.groupId, group }]
})
const answerTimelineItems = computed(() => timelineSplit.value.answer)
const hasActivityFold = computed(() => !!reasoningPart.value || activityTimelineItems.value.length > 0)
const hasActivityTools = computed(() =>
  activityTimelineItems.value.some(item => item.type === 'tool-group'),
)
const activityReasoningOpen = ref(false)
const activityOpenGroupId = ref<string | null>(null)
const activityOpenItemKey = ref<string | null>(null)

function resetActivityLevels() {
  activityReasoningOpen.value = false
  activityOpenGroupId.value = null
  activityOpenItemKey.value = null
}

function onActivityFoldToggle(event: Event) {
  const details = event.currentTarget as HTMLDetailsElement | null
  if (!details?.open) resetActivityLevels()
}

function toggleActivityReasoning() {
  const next = !activityReasoningOpen.value
  resetActivityLevels()
  activityReasoningOpen.value = next
}

function isActivityToolGroupOpen(groupId: string): boolean {
  return activityOpenGroupId.value === groupId
}

function isActivityToolItemOpen(renderKey: string): boolean {
  return activityOpenItemKey.value === renderKey
}

function activityGroupForCall(renderKey: string): ChatToolCallGroup | null {
  for (const item of activityTimelineItems.value) {
    if (item.type !== 'tool-group') continue
    if (item.group.calls.some(call => call.renderKey === renderKey)) return item.group
  }
  return null
}

function toggleActivityToolGroup(groupId: string) {
  const next = activityOpenGroupId.value === groupId ? null : groupId
  resetActivityLevels()
  activityOpenGroupId.value = next
}

function toggleActivityToolItem(renderKey: string) {
  const group = activityGroupForCall(renderKey)
  const keepGroupId = group && group.calls.length > 1 ? group.groupId : null
  const next = activityOpenItemKey.value === renderKey ? null : renderKey
  activityReasoningOpen.value = false
  activityOpenGroupId.value = keepGroupId
  activityOpenItemKey.value = next
}

watch(
  () => props.message.messageId || props.message.id,
  resetActivityLevels,
)

const reasoningSummary = computed(() => {
  const seconds = reasoningPart.value?.seconds || 0
  if (!reasoningPart.value) return ''
  if (seconds < 1) return t('chat.thoughtProcess')
  if (seconds < 60) return t('chat.thoughtForSeconds', { seconds })
  return t('chat.thoughtForMinutes', {
    minutes: Math.floor(seconds / 60),
    seconds: seconds % 60,
  })
})

const completedElapsedSeconds = computed(() => Math.max(
  0,
  Math.floor(props.turnElapsedSeconds || reasoningPart.value?.seconds || 0),
))

const completedSummary = computed(() => {
  const total = completedElapsedSeconds.value
  if (total < 1) return t('chat.completed')
  return t('chat.completedIn', {
    minutes: Math.floor(total / 60),
    seconds: total % 60,
  })
})

function activityGroupStatusText(group: ChatToolCallGroup): string {
  if (group.operationKey !== 'web.research') return props.toolGroupStatusText(group)
  if (group.isRunning) return t('chat.tool.running')
  return group.status === 'success' ? t('chat.tool.done') : ''
}

const activitySummary = computed(() => {
  if (!props.message.isStreaming) return completedSummary.value
  const groups = activityTimelineItems.value.filter(
    (item): item is Extract<ChatStreamTimelineItem, { type: 'tool-group' }> => item.type === 'tool-group',
  )
  if (!groups.length) return reasoningSummary.value || t('chat.thoughtProcess')
  if (groups.length === 1 && groups[0].group.operationKey === 'web.research') {
    return groups[0].group.label
  }

  const summaries: string[] = []
  const byOperation = new Map<string, { label: string; count: number }>()
  for (const item of groups) {
    const current = byOperation.get(item.group.operationKey)
    if (current) current.count += item.group.calls.length
    else byOperation.set(item.group.operationKey, {
      label: item.group.label,
      count: item.group.calls.length,
    })
  }
  for (const entry of byOperation.values()) {
    summaries.push(entry.count > 1 ? `${entry.label} ×${entry.count}` : entry.label)
  }
  const visible = summaries.slice(0, 3)
  if (summaries.length > visible.length) visible.push(`+${summaries.length - visible.length}`)
  return visible.join(' · ')
})

function onMessageClick(event: MouseEvent) {
  if (!props.shareMode) return
  if (props.message.stopNotice) return
  if ((event.target as HTMLElement | null)?.closest('button,a,input,textarea,select')) return
  emit('toggleShare', props.shareMessageId)
}

function fmtUsd(value: number): string {
  const n = Number.isFinite(value) ? Math.max(0, value) : 0
  if (n === 0) return '$0'
  if (n < 0.0001) return '<$0.0001'
  return `$${n.toFixed(6).replace(/\.?0+$/, '')}`
}

function ensembleRole(role: string, label: string): string {
  const normalized = String(role || '').replace(/_/g, ' ')
  if (normalized === 'proposer') return 'proposer'
  if (normalized === 'aggregator') return 'aggregator'
  if (normalized === 'fallback single') return 'fallback'
  return label || normalized || 'member'
}
</script>

<style scoped>
.msg-ai {
  position: relative;
  display: flex;
  gap: 0.625rem;
  width: var(--chat-col, min(calc(100% - 48px), 980px));
  margin: 0 auto;
  padding: 0.5rem 0;
  align-items: flex-start;
  max-width: calc(100% - 48px);
}

.msg-ai--share-mode {
  cursor: pointer;
  width: min(calc(100% - 16px), 1012px);
  max-width: calc(100% - 16px);
  box-sizing: border-box;
  padding: 0.5rem 1rem 0.5rem 2.5rem;
  border-radius: var(--radius-lg);
  transition: background var(--dur-base) var(--ease-standard), box-shadow var(--dur-base) var(--ease-standard);
}

.msg-ai--share-mode:hover {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.msg-ai--share-selected {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: inset 0 0 0 2px var(--accent);
}

/* Checkbox-style selection indicator: empty outlined circle when unselected,
   accent-filled with a check when selected. Always visible in share mode. */
.chat-share-picker {
  position: absolute;
  left: 0.45rem;
  top: 0.65rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--border-strong);
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  color: var(--text-muted);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease-standard), border-color var(--dur-fast) var(--ease-standard), background var(--dur-fast) var(--ease-standard), color var(--dur-fast) var(--ease-standard);
}

.chat-share-picker:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong));
}

.chat-share-picker:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}

.chat-share-picker.is-selected {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-foreground);
}

@media (prefers-reduced-motion: reduce) {
  .chat-share-picker {
    transition: none;
  }
}

.msg-ai-main {
  flex: 1;
  min-width: 0;
  max-width: none;
  padding-top: 0.0625rem;
}

.msg-ai-author {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 2rem;
  margin-bottom: 0.5rem;
}

.msg-ai-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 2rem;
  width: 2rem;
  height: 2rem;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--ok) 18%, var(--border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--ok) 8%, var(--bg-surface));
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--bg-surface) 78%, transparent);
}

.msg-ai-avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
}

.activity-fold {
  margin: 0 0 0.625rem;
  color: var(--text-muted);
  font-size: 0.8125rem;
}

.activity-fold__summary {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  min-width: 0;
  width: fit-content;
  max-width: 100%;
  padding: 0.25rem 0.125rem;
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  cursor: pointer;
  list-style: none;
  line-height: 1.45;
  transition: color var(--dur-fast) var(--ease-standard);
}

.activity-fold__summary::-webkit-details-marker {
  display: none;
}

.activity-fold__summary:hover {
  color: var(--text-muted);
}

.activity-fold__summary:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.activity-fold__chevron {
  flex: 0 0 auto;
  transition: transform var(--dur-fast) var(--ease-standard);
}

.activity-fold[open] > .activity-fold__summary .activity-fold__chevron {
  transform: rotate(90deg);
}

.activity-fold__summary-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-fold__summary-meta {
  flex: 0 0 auto;
  color: var(--text-dim);
  font-size: 0.75rem;
  white-space: nowrap;
}

.activity-fold__body {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin: 0.25rem 0 0.5rem;
  padding: 0.125rem 0;
}

.activity-fold__reasoning-step {
  min-width: 0;
}

.activity-fold__step-toggle {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1rem;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  min-height: 2.25rem;
  padding: 0.25rem 0.5rem 0.25rem 0;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-standard), color var(--dur-fast) var(--ease-standard);
}

.activity-fold__step-toggle:hover,
.activity-fold__step-toggle[aria-expanded="true"] {
  background: color-mix(in srgb, var(--bg-hover) 68%, transparent);
  color: var(--text);
}

.activity-fold__step-toggle:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring-inset);
}

.activity-fold__step-label {
  min-width: 0;
  overflow: hidden;
  font-size: 0.78125rem;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-fold__step-chevron {
  color: var(--text-dim);
  transition: transform var(--dur-fast) var(--ease-standard);
}

.activity-fold__step-chevron.open {
  transform: rotate(90deg);
}

.activity-fold__reasoning {
  min-width: 0;
  margin: 0.125rem 0 0.375rem 0.5rem;
  padding: 0.375rem 0.625rem;
  border-left: 1px solid color-mix(in srgb, var(--accent) 22%, var(--hairline));
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: color-mix(in srgb, var(--bg-surface) 54%, transparent);
}

.activity-fold__reasoning-text {
  max-height: 15rem;
  overflow-y: auto;
  color: var(--text-muted);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.activity-fold__timeline :deep(.tool-row) {
  min-height: 2.125rem;
  padding: 0.375rem 0.5rem 0.375rem 0;
}

.activity-fold__timeline :deep(.tool-row__label),
.activity-fold__timeline :deep(.tool-row__arg),
.activity-fold__timeline :deep(.tool-row__status) {
  font-size: 0.78125rem;
}

@media (max-width: 620px) {
  .activity-fold__summary-meta {
    display: none;
  }

  .activity-fold__body {
    margin-left: 0.125rem;
    padding-left: 0.75rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .activity-fold__summary,
  .activity-fold__chevron,
  .activity-fold__step-toggle,
  .activity-fold__step-chevron {
    transition: none;
  }
}

.msg-ai--stop-notice .msg-ai-main {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  flex: 0 1 auto;
  max-width: min(30rem, 100%);
  padding: 0.375rem 0.625rem;
  border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--warn) 10%, var(--bg-surface));
  color: var(--warn);
}

.msg-ai--stop-notice .msg-ai-main::before {
  content: "";
  width: 0.4375rem;
  height: 0.4375rem;
  flex: 0 0 auto;
  border-radius: var(--radius-full);
  background: var(--warn);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 12%, transparent);
}

.msg-ai--stop-notice :deep(.msg-ai-text) {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: inherit;
}

.msg-ai-footer {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-top: 0.25rem;
}

.msg-ai-ending--done {
  margin-top: 0.625rem;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.msg-ai-ending--done :deep(.msg-artifacts) {
  margin: 0;
}

.msg-ai-ending--done :deep(.sources-row) {
  margin: 0.5rem 0 0;
}

.msg-ai-ending--done .msg-ai-footer {
  margin-top: 0.5rem;
  padding-top: 0;
  border-top: 0;
}

.msg-ai-actions {
  display: flex;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity var(--dur-fast);
}

.msg-ai:hover .msg-ai-actions,
.msg-ai-actions:focus-within {
  opacity: 1;
}

/* Touch screens have no hover to reveal the cluster — keep it always visible
   and give the buttons real tap targets. */
@media (hover: none) {
  .msg-ai-actions {
    opacity: 1;
  }

  .msg-action {
    min-width: 2.75rem;
    min-height: 2.75rem;
  }
}

.msg-time {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
  margin-left: 0.25rem;
  align-self: center;
  font-size: var(--fs-xs);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.msg-time__rel {
  color: color-mix(in srgb, var(--text-dim) 80%, transparent);
}

.msg-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.25rem;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  font-size: 0.6875rem;
}

.msg-action:hover {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.msg-action:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* Fork creates something new — its hover signal is the accent, not text-muted. */
.msg-action--fork:hover {
  color: var(--accent);
}

.msg-action--fork:disabled {
  cursor: progress;
  opacity: 0.55;
}

.msg-action.msg-action--ok,
.msg-action.msg-action--ok:hover {
  color: var(--ok);
}

.msg-action.msg-action--err,
.msg-action.msg-action--err:hover {
  color: var(--danger);
}

.msg-action--vote:disabled {
  cursor: progress;
  opacity: 0.55;
}

/* A cast vote stays visible without hover — the row otherwise fades out and
   the user would lose the only cue that their rating registered. */
.msg-ai-actions:has(.msg-action--vote[aria-pressed='true']) {
  opacity: 1;
}

.msg-copy-live {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.msg-ai-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  min-width: 0;
  gap: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: color-mix(in srgb, var(--text-muted) 56%, transparent);
}

.msg-ai-meta > span:not(.savings-indicator):not(.msg-meta__more) {
  opacity: 0.72;
  transition: opacity var(--dur-base) var(--ease-standard), color var(--dur-base) var(--ease-standard);
}

.msg-ai:hover .msg-ai-meta > span:not(.savings-indicator):not(.msg-meta__more) {
  opacity: 0.88;
}

.msg-meta__cost,
.msg-meta__ensemble {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.msg-meta__ensemble {
  color: color-mix(in srgb, var(--accent) 70%, var(--text-muted));
  max-width: 10rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

.msg-meta__more {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.msg-meta__more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--radius-full);
  color: var(--text-dim);
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

.msg-meta__more-btn:hover,
.msg-meta__more-btn[aria-expanded='true'] {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.msg-meta__more-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.msg-meta-popover {
  position: absolute;
  bottom: calc(100% + 0.375rem);
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 10rem;
  max-width: min(24rem, calc(100vw - 2rem));
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.4;
  white-space: nowrap;
}

.msg-meta-popover__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}

.msg-meta-popover__label {
  color: var(--text-dim);
}

.msg-meta-popover__value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.msg-meta-popover__divider {
  height: 1px;
  margin: 0.125rem 0;
  background: var(--hairline);
}

.msg-meta-popover__models {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.msg-meta-popover__model {
  display: grid;
  grid-template-columns: minmax(4.75rem, 0.8fr) minmax(7rem, 1fr) auto;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 0;
}

.msg-meta-popover__model-role {
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
}

.msg-meta-popover__model-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
}

.msg-meta-popover__model-cost {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.savings-indicator {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-height: 1.25rem;
  padding: 0 0.45rem;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
  border-radius: var(--radius-full);
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--accent) 8%, var(--bg-surface)), var(--bg-surface) 48%, color-mix(in srgb, var(--ok) 8%, var(--bg-surface))),
    radial-gradient(circle at 18% 0%, color-mix(in srgb, var(--warn) 34%, transparent), transparent 42%);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--bg-surface) 85%, transparent),
    0 5px 14px color-mix(in srgb, var(--accent) 8%, transparent);
  color: var(--accent);
  font-weight: 650;
  isolation: isolate;
}

.savings-indicator::after {
  content: '';
  position: absolute;
  inset: -40% auto -40% -60%;
  width: 42%;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--bg-surface) 82%, transparent), transparent);
  transform: skewX(-18deg);
  animation: savingsSweep 5.6s ease-in-out infinite;
  opacity: 0.55;
  pointer-events: none;
}

@keyframes savingsSweep {
  0%, 62% {
    left: -60%;
  }
  84%, 100% {
    left: 118%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .savings-indicator::after {
    animation: none;
    display: none;
  }
}

@media (max-width: 768px) {
  .msg-ai-footer {
    min-width: 0;
  }

  .msg-ai-meta {
    flex: 1;
    flex-wrap: nowrap;
    gap: 0.375rem;
  }

  .msg-meta__model {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .msg-meta__cost,
  .savings-indicator,
  .msg-meta__more {
    flex-shrink: 0;
  }

  .msg-meta__ensemble {
    max-width: min(14rem, 100%);
  }
}

@media (max-width: 640px) {
  .msg-ai--share-mode {
    width: min(calc(100% - 12px), 1012px);
    max-width: calc(100% - 12px);
    padding: 0.5rem 0.75rem 0.5rem 2.25rem;
  }

  .chat-share-picker {
    left: 0.35rem;
  }
}
</style>
