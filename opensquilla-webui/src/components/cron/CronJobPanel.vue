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
          :aria-label="editingJob ? t('cronSkills.panel.ariaEdit') : t('cronSkills.panel.ariaCreate')"
        >
          <div class="cron-panel__head">
            <div>
              <span class="cron-panel__eyebrow">{{ editingJob ? t('cronSkills.panel.eyebrowEdit') : t('cronSkills.panel.eyebrowNew') }}</span>
              <h3 class="cron-panel__title">{{ editingJob ? t('cronSkills.panel.titleEdit') : t('cronSkills.panel.titleCreate') }}</h3>
            </div>
            <button class="cron-iconbtn" :aria-label="t('common.close')" @click="emit('close')">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="cron-panel__body">
            <div class="cron-field">
              <label class="cron-field__label" for="cp-name">{{ t('cronSkills.panel.name') }}</label>
              <input id="cp-name" v-model="form.name" class="cron-field__input" type="text" placeholder="my-job" autocomplete="off">
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-type">{{ t('cronSkills.panel.scheduleType') }}</label>
              <select id="cp-type" v-model="form.type" class="cron-field__input">
                <option value="cron">{{ t('cronSkills.panel.typeCron') }}</option>
                <option value="every">{{ t('cronSkills.panel.typeEvery') }}</option>
                <option value="at">{{ t('cronSkills.panel.typeAt') }}</option>
              </select>
            </div>

            <div v-show="form.type === 'cron'" class="cron-field">
              <label class="cron-field__label" for="cp-cron">{{ t('cronSkills.panel.cronExpression') }}</label>
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
                <span class="cron-presets__label">{{ t('cronSkills.panel.presetsLabel') }}</span>
                <button type="button" class="cron-preset" @click="emit('preset', '*/5 * * * *')">{{ t('cronSkills.panel.preset5m') }}</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 * * * *')">{{ t('cronSkills.panel.presetHourly') }}</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 9 * * 1-5')">{{ t('cronSkills.panel.presetWeekdays') }}</button>
                <button type="button" class="cron-preset" @click="emit('preset', '0 0 * * 0')">{{ t('cronSkills.panel.presetSundays') }}</button>
              </div>
            </div>

            <div v-show="form.type === 'every'" class="cron-field">
              <label class="cron-field__label" for="cp-every">{{ t('cronSkills.panel.intervalSeconds') }}</label>
              <input id="cp-every" v-model="form.every" class="cron-field__input" type="number" min="1" placeholder="60">
            </div>

            <div v-show="form.type === 'at'" class="cron-field">
              <label class="cron-field__label" for="cp-at">{{ t('cronSkills.panel.isoTime') }}</label>
              <input id="cp-at" v-model="form.at" class="cron-field__input cron-field__input--mono" type="text" placeholder="2026-05-18T09:00:00+08:00">
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-tz">{{ t('cronSkills.panel.timezone') }}</label>
              <input id="cp-tz" v-model="form.tz" class="cron-field__input cron-field__input--mono" type="text" placeholder="America/Los_Angeles" autocomplete="off" spellcheck="false">
              <i18n-t keypath="cronSkills.panel.timezoneHint" tag="div" class="cron-field__hint">
                <template #example1><code>Asia/Shanghai</code></template>
                <template #example2><code>Europe/London</code></template>
              </i18n-t>
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-payload-kind">{{ t('cronSkills.panel.jobMode') }}</label>
              <select id="cp-payload-kind" v-model="form.payloadKind" class="cron-field__input" @change="emit('payloadKindChange')">
                <option value="reminder">{{ t('cronSkills.panel.modeReminder') }}</option>
                <option value="agent_turn">{{ t('cronSkills.panel.modeAgentTurn') }}</option>
                <option value="system_event">{{ t('cronSkills.panel.modeSystemEvent') }}</option>
              </select>
              <div class="cron-field__hint">{{ jobModeHint }}</div>
            </div>

            <div class="cron-field">
              <label class="cron-field__label" for="cp-agent-id">{{ t('cronSkills.panel.agentId') }}</label>
              <input id="cp-agent-id" v-model="form.agentId" class="cron-field__input" type="text" placeholder="main">
            </div>

            <div v-show="form.payloadKind === 'agent_turn'" class="cron-field">
              <label class="cron-field__label" for="cp-session-target">{{ t('cronSkills.panel.sessionTarget') }}</label>
              <select id="cp-session-target" v-model="form.sessionTarget" class="cron-field__input" @change="emit('sessionTargetChange')">
                <option value="main">{{ t('cronSkills.panel.targetMain') }}</option>
                <option value="current">{{ t('cronSkills.panel.targetCurrent') }}</option>
                <option value="isolated">{{ t('cronSkills.panel.targetIsolated') }}</option>
                <option value="session">{{ t('cronSkills.panel.targetNamed') }}</option>
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
              <textarea id="cp-message" v-model="form.message" class="cron-field__input cron-field__input--textarea" rows="4" :placeholder="t('cronSkills.panel.messagePlaceholder')" />
            </div>

            <details class="cron-advanced">
              <summary class="cron-advanced__summary">{{ t('cronSkills.panel.advancedSummary') }}</summary>
              <div class="cron-advanced__body">
                <div class="cron-field">
                  <label class="cron-field__label" for="cp-wake-mode">{{ t('cronSkills.panel.wakeMode') }}</label>
                  <select id="cp-wake-mode" v-model="form.wakeMode" class="cron-field__input">
                    <option value="now">{{ t('cronSkills.panel.wakeNow') }}</option>
                    <option value="next-heartbeat">{{ t('cronSkills.panel.wakeNextHeartbeat') }}</option>
                  </select>
                  <i18n-t keypath="cronSkills.panel.wakeModeHint" tag="div" class="cron-field__hint">
                    <template #code><code>next-heartbeat</code></template>
                  </i18n-t>
                </div>

                <div class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-mode">{{ t('cronSkills.panel.deliveryMode') }}</label>
                  <select id="cp-delivery-mode" v-model="form.deliveryMode" class="cron-field__input">
                    <option value="">{{ t('cronSkills.panel.deliveryDefault') }}</option>
                    <option value="none">{{ t('cronSkills.panel.deliveryNone') }}</option>
                    <option value="announce">{{ t('cronSkills.panel.deliveryAnnounce') }}</option>
                    <option value="webhook">{{ t('cronSkills.panel.deliveryWebhook') }}</option>
                  </select>
                </div>

                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-channel">{{ t('cronSkills.panel.channel') }}</label>
                  <input id="cp-delivery-channel" v-model="form.deliveryChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-to">{{ t('cronSkills.panel.recipient') }}</label>
                  <input id="cp-delivery-to" v-model="form.deliveryTo" class="cron-field__input" type="text" placeholder="C-team-alerts" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'announce'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-account">{{ t('cronSkills.panel.accountId') }}</label>
                  <input id="cp-delivery-account" v-model="form.deliveryAccount" class="cron-field__input" type="text" autocomplete="off">
                </div>

                <div v-show="form.deliveryMode === 'webhook'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-webhook-url">{{ t('cronSkills.panel.webhookUrl') }}</label>
                  <input id="cp-delivery-webhook-url" v-model="form.deliveryWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/cron" autocomplete="off">
                </div>
                <div v-show="form.deliveryMode === 'webhook'" class="cron-field">
                  <label class="cron-field__label" for="cp-delivery-webhook-token">{{ t('cronSkills.panel.webhookToken') }}</label>
                  <input id="cp-delivery-webhook-token" v-model="form.deliveryWebhookToken" class="cron-field__input" type="password" :placeholder="t('cronSkills.panel.webhookTokenPlaceholder')" autocomplete="off">
                </div>

                <label v-show="form.deliveryMode === 'announce' || form.deliveryMode === 'webhook'" class="cron-toggle">
                  <input v-model="form.deliveryBestEffort" type="checkbox">
                  <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
                  <span class="cron-toggle__label">{{ t('cronSkills.panel.bestEffort') }}</span>
                </label>

                <details class="cron-advanced cron-advanced--nested">
                  <summary class="cron-advanced__summary">{{ t('cronSkills.panel.failureDestination') }}</summary>
                  <div class="cron-advanced__body">
                    <div class="cron-field">
                      <label class="cron-field__label" for="cp-fd-mode">{{ t('cronSkills.panel.routeFailuresTo') }}</label>
                      <select id="cp-fd-mode" v-model="form.fdMode" class="cron-field__input">
                        <option value="">{{ t('cronSkills.panel.fdDisabled') }}</option>
                        <option value="channel">{{ t('cronSkills.panel.fdChannel') }}</option>
                        <option value="webhook">{{ t('cronSkills.panel.fdWebhook') }}</option>
                      </select>
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-channel">{{ t('cronSkills.panel.channel') }}</label>
                      <input id="cp-fd-channel" v-model="form.fdChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-to">{{ t('cronSkills.panel.recipient') }}</label>
                      <input id="cp-fd-to" v-model="form.fdTo" class="cron-field__input" type="text" placeholder="C-ops-alerts" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'channel'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-account">{{ t('cronSkills.panel.accountId') }}</label>
                      <input id="cp-fd-account" v-model="form.fdAccount" class="cron-field__input" type="text" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'webhook'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-webhook-url">{{ t('cronSkills.panel.webhookUrl') }}</label>
                      <input id="cp-fd-webhook-url" v-model="form.fdWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/alert" autocomplete="off">
                    </div>
                    <div v-show="form.fdMode === 'webhook'" class="cron-field">
                      <label class="cron-field__label" for="cp-fd-webhook-token">{{ t('cronSkills.panel.webhookToken') }}</label>
                      <input id="cp-fd-webhook-token" v-model="form.fdWebhookToken" class="cron-field__input" type="password" :placeholder="t('cronSkills.panel.webhookTokenPlaceholder')" autocomplete="off">
                    </div>
                  </div>
                </details>
              </div>
            </details>

            <label class="cron-toggle">
              <input v-model="form.enabled" type="checkbox">
              <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
              <span class="cron-toggle__label">{{ t('cronSkills.panel.enabled') }}</span>
            </label>

            <div class="cron-panel__actions">
              <button class="btn btn--primary" @click="emit('save')">{{ t('cronSkills.panel.saveSchedule') }}</button>
              <button class="btn btn--ghost" @click="emit('close')">{{ t('common.cancel') }}</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { CronJob, CronJobFormModel } from '@/types/cron'
import { humanCountdown, humanTime } from '@/utils/cron/time'
import { useDialogA11y } from '@/composables/useDialogA11y'

const { t } = useI18n()

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
