<script setup lang="ts">
import { computed, ref } from 'vue'
import ControlSwitch from '@/components/ControlSwitch.vue'

// Client-only "Labs" preferences. Each row reads/writes ONE localStorage key
// directly. The chat composables that consume these read the value once at
// construction and live behind an architecture import-fence, so writing the raw
// key here is the safe, decoupled way to surface them (no chat imports). Applies
// instantly; the reload-gated ones are labelled. Never enters the dirty bar.

// --- boolean '1'/'0' flags (absent => off) ---
const APPROVAL_KEY = 'opensquilla.chat.approvalPoll'
const HISTORY_KEY = 'opensquilla.chat.historyMerge'
const RUNTRACE_KEY = 'opensquilla.logs.runTrace'

function readBool(key: string): boolean {
  try { return localStorage.getItem(key) === '1' } catch { return false }
}
function writeBool(key: string, on: boolean) {
  try { localStorage.setItem(key, on ? '1' : '0') } catch { /* private mode */ }
}

const approvalPoll = ref(readBool(APPROVAL_KEY))
const historyMerge = ref(readBool(HISTORY_KEY))
const runTrace = ref(readBool(RUNTRACE_KEY))
function setApprovalPoll(on: boolean) { approvalPoll.value = on; writeBool(APPROVAL_KEY, on) }
function setHistoryMerge(on: boolean) { historyMerge.value = on; writeBool(HISTORY_KEY, on) }
function setRunTrace(on: boolean) { runTrace.value = on; writeBool(RUNTRACE_KEY, on) }

// --- foldLiveTurn: default ON; '0' is the only OFF value ---
const FOLD_KEY = 'opensquilla.chat.foldLiveTurn'
const foldOn = ref(localStorageGet(FOLD_KEY) !== '0')
function setFold(on: boolean) {
  foldOn.value = on
  try { localStorage.setItem(FOLD_KEY, on ? '1' : '0') } catch { /* private mode */ }
}

// --- answerReveal: "min,max" milliseconds, min >= 0 and max >= min ---
const REVEAL_KEY = 'opensquilla.chat.answerReveal'
const REVEAL_DEFAULT: [number, number] = [1800, 4000]
function readReveal(): [number, number] {
  const raw = localStorageGet(REVEAL_KEY)
  if (raw) {
    const parts = raw.split(',').map(Number)
    if (parts.length === 2 && parts.every(Number.isFinite) && parts[0] >= 0 && parts[1] >= parts[0]) {
      return [parts[0], parts[1]]
    }
  }
  return [...REVEAL_DEFAULT]
}
const initialReveal = readReveal()
const revealMin = ref(initialReveal[0])
const revealMax = ref(initialReveal[1])
const revealValid = computed(() =>
  Number.isFinite(revealMin.value) && Number.isFinite(revealMax.value) &&
  revealMin.value >= 0 && revealMax.value >= revealMin.value,
)
function commitReveal() {
  if (!revealValid.value) return
  try {
    localStorage.setItem(REVEAL_KEY, `${Math.round(revealMin.value)},${Math.round(revealMax.value)}`)
  } catch { /* private mode */ }
}

function localStorageGet(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Advanced</h3>
      <p class="control-section__desc">Experimental client preferences for this browser. They apply instantly &mdash; no save needed. Items marked <em>reload</em> take effect after a page refresh.</p>
    </div>

    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Live turn fold</span>
        <span class="control-row__desc">Render the streaming work-card from the new fold engine (off = legacy render).</span>
      </div>
      <div class="control-row__control">
        <span class="labs-hint">reload</span>
        <ControlSwitch name="labs_fold_live_turn" :checked="foldOn" aria-label="Live turn fold (takes effect after reload)" @change="setFold" />
      </div>
    </label>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <span id="labs-reveal-label" class="control-row__label">Answer reveal window (ms)</span>
        <span class="control-row__desc">Hold the live answer's reveal in a [min, max] window so the router can decide first. min &le; max.</span>
      </div>
      <div class="control-row__control labs-range" role="group" aria-labelledby="labs-reveal-label">
        <input
          class="control-input control-input--narrow"
          name="labs_reveal_min"
          type="number" min="0" step="100" inputmode="numeric"
          v-model.number="revealMin"
          aria-label="Answer reveal minimum milliseconds"
          :aria-invalid="!revealValid ? 'true' : 'false'"
          aria-describedby="labs-reveal-error"
          @change="commitReveal"
        >
        <span class="labs-range__sep" aria-hidden="true">&ndash;</span>
        <input
          class="control-input control-input--narrow"
          name="labs_reveal_max"
          type="number" min="0" step="100" inputmode="numeric"
          v-model.number="revealMax"
          aria-label="Answer reveal maximum milliseconds"
          :aria-invalid="!revealValid ? 'true' : 'false'"
          aria-describedby="labs-reveal-error"
          @change="commitReveal"
        >
        <span v-if="!revealValid" id="labs-reveal-error" class="labs-invalid" role="alert">min must be &ge; 0 and &le; max</span>
      </div>
    </div>

    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Approval recovery polling</span>
        <span class="control-row__desc">Restore the ~2s approvals poll as a self-healing fallback (default off; approvals already stream).</span>
      </div>
      <div class="control-row__control">
        <ControlSwitch name="labs_approval_poll" :checked="approvalPoll" aria-label="Approval recovery polling" @change="setApprovalPoll" />
      </div>
    </label>

    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">History reconcile-by-id merge <span class="labs-exp">experimental</span></span>
        <span class="control-row__desc">On history sync, merge by message id and keep live-only fields (default off, transitioning on).</span>
      </div>
      <div class="control-row__control">
        <span class="labs-hint">reload</span>
        <ControlSwitch name="labs_history_merge" :checked="historyMerge" aria-label="History reconcile-by-id merge (takes effect after reload)" @change="setHistoryMerge" />
      </div>
    </label>

    <label class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Run-trace drawer in Logs</span>
        <span class="control-row__desc">Make log lines interactive and open a per-line node-step detail drawer in the Logs view.</span>
      </div>
      <div class="control-row__control">
        <span class="labs-hint">reload</span>
        <ControlSwitch name="labs_run_trace" :checked="runTrace" aria-label="Run-trace drawer in Logs (takes effect after reload)" @change="setRunTrace" />
      </div>
    </label>
  </section>
</template>

<style scoped>
.labs-hint {
  border: 1px solid color-mix(in srgb, var(--warn) 35%, var(--border));
  border-radius: 999px;
  color: var(--warn);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
  padding: 1px 7px;
  text-transform: uppercase;
}

.labs-exp {
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border));
  border-radius: 999px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.03em;
  margin-left: var(--sp-1);
  padding: 1px 6px;
  text-transform: uppercase;
}

.labs-range {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.labs-range__sep {
  color: var(--text-dim);
}

.labs-invalid {
  color: var(--danger);
  font-size: var(--fs-xs);
  width: 100%;
}
</style>
