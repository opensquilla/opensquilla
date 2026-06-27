<template>
  <Teleport to="body">
    <Transition name="panel">
      <div v-if="open" class="cron-panel-overlay">
        <div class="cron-panel__scrim" :class="{ 'is-open': open }" @click="emit('close')" />
        <div
          ref="drawerRef"
          class="cron-panel"
          :class="{ 'is-open': open }"
          role="dialog"
          aria-modal="true"
          :aria-label="editingJob ? 'Edit schedule' : 'Create a job'"
        >
          <div class="cron-panel__head">
            <div>
              <span class="cron-panel__eyebrow">{{ editingJob ? 'Edit schedule' : 'New schedule' }}</span>
              <h3 class="cron-panel__title">{{ editingJob ? 'Edit Schedule' : 'Create a job' }}</h3>
            </div>
            <button class="cron-iconbtn" aria-label="Close" @click="emit('close')">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="cron-panel__body">
            <div class="cron-field">
              <label class="cron-field__label" for="cp-name">Name</label>
              <input id="cp-name" v-model="form.name" class="cron-field__input" type="text" placeholder="my-job" autocomplete="off">
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-type">Schedule type</label>
              <select id="cp-type" v-model="form.type" class="cron-field__input">
                <option value="cron">Cron expression</option>
                <option value="every">Fixed interval</option>
                <option value="at">One-time ISO time</option>
              </select>
            </div>

            <div v-show="form.type === 'cron'" class="cron-field">
              <label class="cron-field__label" for="cp-cron">Cron expression</label>
              <input
                id="cp-cron"
                v-model="form.cron"
                class="cron-field__input cron-field__input--mono"
                type="text"
                placeholder="0 9 * * 1-5"
                autocomplete="off"
                spellcheck="false"
                @input="emit('cronInput')"
              >
              <div class="cron-explain" :class="{ 'is-valid': cronExplainValid, 'is-invalid': cronExplainInvalid }">
                <div class="cron-explain__human">{{ cronExplainHuman }}</div>
                <div v-if="!cronExplainValid && !cronExplainInvalid" class="cron-explain__hint">
                  e.g. <code>*/15 * * * *</code>, <code>0 9 * * 1-5</code>, <code>0 0 1 * *</code>
                </div>
                <ul v-if="cronExplainUpcoming.length > 0" class="cron-explain__upcoming">
                  <li v-for="(d, i) in cronExplainUpcoming" :key="i">
                    <span class="cron-explain__num">{{ i + 1 }}.</span>
                    <span class="cron-mono">{{ humanCountdown(d) }}</span>
                    <span class="cron-explain__abs">{{ humanTime(d) }}</span>
                  </li>
                </ul>
              </div>
              <div class="cron-presets">
                <span class="cron-presets__label">Presets:</span>
                <button type="button" class="cron-preset" @click="emit('preset', '*/5 * * * *')">Every 5m</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 * * * *')">Hourly</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 9 * * 1-5')">Weekdays 09:00</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 0 * * 0')">Sundays midnight</button>
              </div>
            </div>

            <div v-show="form.type === 'every'" class="cron-field">
              <label class="cron-field__label" for="cp-every">Interval (seconds)</label>
              <input id="cp-every" v-model="form.every" class="cron-field__input" type="number" min="1" placeholder="60">
            </div>

            <div v-show="form.type === 'at'" class="cron-field">
              <label class="cron-field__label" for="cp-at">ISO time</label>
              <input id="cp-at" v-model="form.at" class="cron-field__input cron-field__input--mono" type="text" placeholder="2026-05-18T09:00:00+08:00">
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-tz">Timezone (IANA)</label>
              <input id="cp-tz" v-model="form.tz" class="cron-field__input cron-field__input--mono" type="text" placeholder="America/Los_Angeles" autocomplete="off" spellcheck="false">
              <div class="cron-field__hint">Leave empty to evaluate the cron expression in UTC. Example: <code>Asia/Shanghai</code>, <code>Europe/London</code>.</div>
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-payload-kind">Job mode</label>
              <select id="cp-payload-kind" v-model="form.payloadKind" class="cron-field__input" @change="emit('payloadKindChange')">
                <option value="reminder">Static Reminder (no model)</option>
                <option value="agent_turn">Background Agent Task (choose session)</option>
                <option value="system_event">System Event (Main)</option>
              </select>
              <div class="cron-field__hint">{{ jobModeHint }}</div>
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-agent-id">Agent ID</label>
              <input id="cp-agent-id" v-model="form.agentId" class="cron-field__input" type="text" placeholder="main">
            </div>

            <div v-show="form.payloadKind === 'agent_turn'" class="cron-field">
              <label class="cron-field__label" for="cp-session-target">Session target</label>
              <select id="cp-session-target" v-model="form.sessionTarget" class="cron-field__input" @change="emit('sessionTargetChange')">
                <option value="main">Agent main session</option>
                <option value="current">Current chat session</option>
                <option value="isolated">Isolated cron session</option>
                <option value="session">Named session</option>
              </select>
              <div class="cron-field__hint">{{ sessionTargetHint }}</div>
            </div>

            <div v-show="showTargetSessionRow" class="cron-field">
              <label class="cron-field__label" for="cp-target-session-key">{{ targetSessionLabel }}</label>
              <input id="cp-target-session-key" v-model="form.targetSessionKey" class="cron-field__input" type="text" placeholder="agent:main:webchat:abc123">
              <div class="cron-field__hint">{{ targetSessionHint }}</div>
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-message">{{ messageLabel }}</label>
              <textarea id="cp-message" v-model="form.message" class="cron-field__input cron-field__input--textarea" rows="4" placeholder="Run daily report&hellip;" />
            </div>

            <details class="cron-advanced">
              <summary class="cron-advanced__summary">Advanced delivery &amp; wake</summary>
              <div class="cron-advanced__body">
                <div class="cron-field">
                  <label class="cron-field__label" for="cp-wake-mode">Wake mode</label>
                  <select id="cp-wake-mode" v-model="form.wakeMode" class="cron-field__input">
                    <option value="now">Now (fire immediately on schedule)</option>
                    <option value="next-heartbeat">Next heartbeat (defer to main loop)</option>
                  </select>
                  <div class="cron-field__hint">Use <code>next-heartbeat</code> for main-session jobs that should ride the existing turn queue.</div>
                </div>

                <div class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-mode">Delivery mode</label>
                  <select id="cp-delivery-mode" v-model="form.deliveryMode" class="cron-field__input">
                    <option value="">Default (inferred from session)</option>
                    <option value="none">None (run silently)</option>
                    <option value="announce">Announce to channel</option>
                    <option value="webhook">Post to webhook</option>
                  </select>
                </div>

                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-channel">Channel</label>
                  <input id="cp-delivery-channel" v-model="form.deliveryChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-to">Recipient</label>
                  <input id="cp-delivery-to" v-model="form.deliveryTo" class="cron-field__input" type="text" placeholder="C-team-alerts" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-account">Account id</label>
                  <input id="cp-delivery-account" v-model="form.deliveryAccount" class="cron-field__input" type="text" autocomplete="off">
                </div>

                <div v-show="form.deliveryMode === 'webhook'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-webhook-url">Webhook URL</label>
                  <input id="cp-delivery-webhook-url" v-model="form.deliveryWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/cron" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'webhook'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-webhook-token">Webhook bearer token</label>
                  <input id="cp-delivery-webhook-token" v-model="form.deliveryWebhookToken" class="cron-field__input" type="password" placeholder="optional bearer token" autocomplete="off">
                </div>

                <label v-show="form.deliveryMode === 'announce' || form.deliveryMode === 'webhook'" class="cron-toggle">
                  <input v-model="form.deliveryBestEffort" type="checkbox">
                  <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
                  <span class="cron-toggle__label">Best-effort delivery (do not fail the job when delivery fails)</span>
                </label>

                <details class="cron-advanced cron-advanced--nested">
                  <summary class="cron-advanced__summary">Failure destination</summary>
                  <div class="cron-advanced__body">
                    <div class="cron-field">
                      <label class="cron-field__label" for="cp-fd-mode">Route failures to</label>
                      <select id="cp-fd-mode" v-model="form.fdMode" class="cron-field__input">
                        <option value="">Disabled (no separate failure alert)</option>
                        <option value="channel">A channel</option>
                        <option value="webhook">A webhook</option>
                      </select>
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-channel">Channel</label>
                      <input id="cp-fd-channel" v-model="form.fdChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-to">Recipient</label>
                      <input id="cp-fd-to" v-model="form.fdTo" class="cron-field__input" type="text" placeholder="C-ops-alerts" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-account">Account id</label>
                      <input id="cp-fd-account" v-model="form.fdAccount" class="cron-field__input" type="text" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'webhook'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-webhook-url">Webhook URL</label>
                      <input id="cp-fd-webhook-url" v-model="form.fdWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/alert" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'webhook'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-webhook-token">Webhook bearer token</label>
                      <input id="cp-fd-webhook-token" v-model="form.fdWebhookToken" class="cron-field__input" type="password" placeholder="optional bearer token" autocomplete="off">
                    </div>
                  </div>
                </details>
              </div>
            </details>

            <label class="cron-toggle">
              <input v-model="form.enabled" type="checkbox">
              <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
              <span class="cron-toggle__label">Enabled</span>
            </label>

            <div class="cron-panel__actions">
              <button class="btn btn--primary" @click="emit('save')">Save schedule</button>
              <button class="btn btn--ghost" @click="emit('close')">Cancel</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, toRef } from 'vue'
import Icon from '@/components/Icon.vue'
import type { CronJob, CronJobFormModel } from '@/types/cron'
import { humanCountdown, humanTime } from '@/utils/cron/time'
import { useDialogA11y } from '@/composables/useDialogA11y'

const props = defineProps<{
  open: boolean
  editingJob: CronJob | null
  cronExplainHuman: string
  cronExplainValid: boolean
  cronExplainInvalid: boolean
  cronExplainUpcoming: Date[]
  jobModeHint: string
  sessionTargetHint: string
  showTargetSessionRow: boolean
  targetSessionLabel: string
  targetSessionHint: string
  messageLabel: string
}>()

const form = defineModel<CronJobFormModel>('form', { required: true })

const emit = defineEmits<{
  close: []
  save: []
  cronInput: []
  preset: [cron: string]
  payloadKindChange: []
  sessionTargetChange: []
}>()

const drawerRef = ref<HTMLElement | null>(null)
const openRef = toRef(props, 'open')
useDialogA11y(drawerRef, openRef, () => emit('close'))
</script>
