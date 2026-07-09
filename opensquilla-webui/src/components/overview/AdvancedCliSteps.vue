<template>
  <div v-if="steps.length" class="health-steps">
    <div v-if="heading" class="health-steps__heading">{{ heading }}</div>
    <!-- Blocks render in authored order; a run of foldable commands collapses
         into one disclosure, guidance and lifecycle steps stay inline. Step
         numbers always reflect the authored sequence. -->
    <template v-for="(block, bIdx) in blocks" :key="bIdx">
      <details v-if="block.kind === 'fold'" class="cli-fold">
        <summary class="cli-fold__summary">{{ t('setup.cli.advancedTitle') }}</summary>
        <p class="cli-fold__hint">
          {{ invocation?.mode === 'dev' ? t('setup.cli.hintDev') : t('setup.cli.hintBundled') }}
        </p>
        <ol>
          <li v-for="step in block.steps" :key="step.idx" class="health-step">
            <span class="health-step__number">{{ step.idx + 1 }}</span>
            <span class="health-step__body">
              <b>{{ step.label }}</b>
              <span class="health-step__command">
                <code>{{ format(step.command || '') }}</code>
                <button
                  class="health-step__copy"
                  :class="{ 'health-step__copy--ok': copiedIdx === step.idx }"
                  type="button"
                  :title="copyTitle(step.idx)"
                  :aria-label="copyTitle(step.idx)"
                  @click="copyStep(step)"
                >
                  <Icon :name="copiedIdx === step.idx ? 'check' : 'copy'" :size="14" />
                </button>
              </span>
              <span v-if="step.detail" class="health-step__detail">{{ step.detail }}</span>
            </span>
          </li>
        </ol>
      </details>
      <ol v-else>
        <li v-for="step in block.steps" :key="step.idx" class="health-step">
          <span class="health-step__number">{{ step.idx + 1 }}</span>
          <span class="health-step__body">
            <b>{{ step.label }}</b>
            <span v-if="step.kind === 'command'" class="health-step__command">
              <code>{{ format(step.command || '') }}</code>
              <button
                class="health-step__copy"
                :class="{ 'health-step__copy--ok': copiedIdx === step.idx }"
                type="button"
                :title="copyTitle(step.idx)"
                :aria-label="copyTitle(step.idx)"
                @click="copyStep(step)"
              >
                <Icon :name="copiedIdx === step.idx ? 'check' : 'copy'" :size="14" />
              </button>
            </span>
            <span v-if="step.kind === 'lifecycle'" class="health-step__detail">{{ t('setup.cli.restartHint') }}</span>
            <span v-else-if="step.detail" class="health-step__detail">{{ step.detail }}</span>
          </span>
        </li>
      </ol>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { usePlatform } from '@/platform'
import { isGatewayLifecycleCommand, useCliInvocation } from '@/composables/useCliInvocation'
import { useToasts } from '@/composables/useToasts'
import { copyTextWithFallback } from '@/utils/browser'

interface CliStep {
  label: string
  command?: string
  detail?: string
}

// 'command' = copyable command; 'lifecycle' = gateway restart/start/stop that
// cannot run from a copied command on desktop, shown as guidance; 'guidance' =
// no command.
type StepKind = 'command' | 'lifecycle' | 'guidance'

interface IndexedStep extends CliStep {
  idx: number
  kind: StepKind
}

interface FoldBlock { kind: 'fold'; steps: IndexedStep[] }
interface InlineBlock { kind: 'inline'; steps: IndexedStep[] }
type Block = FoldBlock | InlineBlock

const props = defineProps<{
  steps: CliStep[]
  heading?: string
}>()

const { t } = useI18n()
const { pushToast } = useToasts()
const { format, invocation } = useCliInvocation()

// Hosts without a terminal workflow (the desktop shell) fold command steps
// behind an advanced disclosure; web keeps the flat authored list.
const folded = !usePlatform().capabilities.hasTerminalWorkflow

// Classify each step, preserving authored order (findings sequence their steps
// deliberately: inspect → fix → restart). On desktop, gateway lifecycle
// commands become guidance because a copied restart cannot drive the
// shell-supervised gateway.
const indexedSteps = computed<IndexedStep[]>(() =>
  props.steps.map((step, idx) => {
    let kind: StepKind = 'guidance'
    if (step.command) {
      kind = folded && isGatewayLifecycleCommand(step.command) ? 'lifecycle' : 'command'
    }
    return { ...step, idx, kind }
  }),
)

// Group consecutive foldable commands (desktop only) into one disclosure;
// everything else renders inline in authored order.
const blocks = computed<Block[]>(() => {
  const out: Block[] = []
  for (const step of indexedSteps.value) {
    const foldable = folded && step.kind === 'command'
    const last = out[out.length - 1]
    if (foldable && last?.kind === 'fold') {
      last.steps.push(step)
    } else if (foldable) {
      out.push({ kind: 'fold', steps: [step] })
    } else if (last?.kind === 'inline') {
      last.steps.push(step)
    } else {
      out.push({ kind: 'inline', steps: [step] })
    }
  }
  return out
})

const copiedIdx = ref<number | null>(null)
let copiedResetId: ReturnType<typeof setTimeout> | null = null

function copyTitle(idx: number): string {
  return copiedIdx.value === idx ? t('setup.toast.copiedCommand') : t('sessions.overview.copyCommand')
}

async function copyStep(step: IndexedStep) {
  if (!step.command) return
  try {
    await copyTextWithFallback(format(step.command))
    copiedIdx.value = step.idx
    if (copiedResetId) clearTimeout(copiedResetId)
    copiedResetId = setTimeout(() => {
      copiedIdx.value = null
      copiedResetId = null
    }, 1600)
    pushToast(t('setup.toast.copiedCommand'), { tone: 'ok' })
  } catch (err) {
    copiedIdx.value = null
    const error = err instanceof Error ? err.message : String(err)
    pushToast(t('setup.toast.copyFailed', { error }), { tone: 'danger' })
  }
}

onUnmounted(() => {
  if (copiedResetId) clearTimeout(copiedResetId)
})
</script>

<style scoped>
.health-steps {
  display: grid;
  gap: 8px;
  margin-top: var(--sp-3);
}

.health-steps__heading {
  color: var(--text-dim);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.health-steps ol {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.health-step {
  align-items: start;
  display: grid;
  gap: 10px;
  grid-template-columns: 24px minmax(0, 1fr);
}

.health-step__number {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  color: var(--text-muted);
  display: inline-flex;
  font-family: var(--font-mono);
  font-size: 11px;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.health-step__body {
  color: var(--text-muted);
  min-width: 0;
}

.health-step__body b {
  color: var(--text);
  display: inline-block;
  margin-right: 8px;
}

.health-step__body code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  display: inline-block;
  font-size: 12px;
  max-width: 100%;
  overflow-wrap: anywhere;
  padding: 3px 7px;
}

.health-step__command {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
  overflow-wrap: anywhere;
  vertical-align: middle;
}

.health-step__detail {
  display: block;
  font-size: 12px;
  margin-top: 2px;
}

.health-step__copy {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  height: 40px;
  justify-content: center;
  padding: 0;
  transition: background var(--dur-fast) var(--ease-standard), border-color var(--dur-fast) var(--ease-standard), color var(--dur-fast) var(--ease-standard);
  width: 40px;
}

.health-step__copy:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
  color: var(--text);
}

.health-step__copy--ok,
.health-step__copy--ok:hover {
  background: color-mix(in srgb, var(--ok) 14%, var(--bg-elevated));
  border-color: var(--ok);
  color: var(--ok);
}

.cli-fold {
  min-width: 0;
}

.cli-fold__summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-xs);
  user-select: none;
  width: fit-content;
}

.cli-fold__summary:hover {
  color: var(--text);
}

.cli-fold__hint {
  color: var(--text-dim);
  font-size: 12px;
  margin: 6px 0 8px;
}

.cli-fold[open] .cli-fold__summary {
  margin-bottom: 2px;
}

@media (max-width: 480px) {
  .health-step__command {
    display: flex;
    width: 100%;
  }

  .health-step__command code {
    flex: 1 1 auto;
    min-width: 0;
  }
}
</style>
