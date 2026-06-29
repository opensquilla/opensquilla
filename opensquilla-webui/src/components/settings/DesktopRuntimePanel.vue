<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import GatewayStatusBlock from '@/components/settings/GatewayStatusBlock.vue'
import { usePlatform, type GatewayStatus } from '@/platform'
import { useConfirm } from '@/composables/useConfirm'
import { useToasts } from '@/composables/useToasts'

const { t } = useI18n()

// Desktop-only Runtime section of the shared SettingsDialog. The desktop app
// owns its local gateway process, so this surfaces its status/log/restart and
// the "reset saved setup" escape hatch — the controls the old standalone
// DesktopSettingsView carried. Web never renders this (desktopOnly section).
const platform = usePlatform()
const { confirm } = useConfirm()
const { pushToast } = useToasts()

const loading = ref(true)
const busy = ref(false)
const gateway = shallowRef<GatewayStatus | null>(null)

const STATUS_KEYS: Record<string, string> = {
  starting: 'setup.runtime.statusStarting',
  ready: 'setup.runtime.statusReady',
  stopped: 'setup.runtime.statusStopped',
  error: 'setup.runtime.statusError',
}

const statusLabel = computed(() => {
  const key = STATUS_KEYS[gateway.value?.status ?? '']
  return key ? t(key) : t('setup.runtime.statusUnknown')
})
const gatewayError = computed(() => gateway.value?.error || '')
const url = computed(() => gateway.value?.url || t('setup.runtime.noActiveGateway'))
const logAvailable = computed(() => Boolean(gateway.value?.logPath))
const logHint = computed(() => gateway.value?.logPath || t('setup.runtime.noLogPath'))

// This panel only ever mounts on desktop (SettingsDialog gates it behind
// isDesktop), so the capability flags are always true here; gate the buttons on
// the optional methods actually being wired instead.
const canRevealLog = computed(() => Boolean(platform.gateway.revealLog))
const canRestart = computed(() => Boolean(platform.gateway.retryStartup))
const canReset = computed(() => Boolean(platform.settings.resetDesktopSettings))

async function loadStatus() {
  loading.value = true
  try {
    gateway.value = await platform.gateway.getStatus()
  } catch (err) {
    pushToast(t('setup.runtime.statusReadFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    loading.value = false
  }
}

async function revealLog() {
  if (!platform.gateway.revealLog) return
  try {
    const ok = await platform.gateway.revealLog()
    if (!ok) pushToast(t('setup.runtime.noLogToReveal'), { tone: 'danger' })
  } catch (err) {
    pushToast(t('setup.runtime.revealFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  }
}

async function restartGateway() {
  if (!platform.gateway.retryStartup) return
  busy.value = true
  try {
    await platform.gateway.retryStartup()
    pushToast(t('setup.runtime.restarting'))
    await loadStatus()
  } catch (err) {
    pushToast(t('setup.runtime.restartFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

async function resetSetup() {
  if (!platform.settings.resetDesktopSettings) return
  const ok = await confirm({
    title: t('setup.runtime.resetConfirmTitle'),
    body: t('setup.runtime.resetConfirmBody'),
    primaryLabel: t('setup.runtime.resetConfirmPrimary'),
  })
  if (!ok) return
  busy.value = true
  try {
    await platform.settings.resetDesktopSettings()
    pushToast(t('setup.runtime.resetDone'))
  } catch (err) {
    pushToast(t('setup.runtime.resetFailed', { error: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.runtime.title') }}</h3>
      <p class="control-section__desc">{{ t('setup.runtime.desc') }}</p>
    </div>

    <div class="runtime-grid">
      <GatewayStatusBlock :label="t('setup.runtime.gateway')" :value="loading ? t('setup.runtime.loading') : statusLabel" :hint="gatewayError || url" />
      <GatewayStatusBlock :label="t('setup.runtime.title')" :value="t('setup.runtime.local')" :hint="t('setup.runtime.localProcess')" />
      <GatewayStatusBlock :label="t('setup.runtime.gatewayLog')" :value="logAvailable ? t('setup.runtime.available') : t('setup.runtime.unavailable')" :hint="logHint" />
    </div>

    <div class="runtime-actions">
      <button type="button" class="btn btn--ghost" :disabled="loading || busy" @click="loadStatus">
        <Icon name="refresh" :size="15" />
        <span>{{ t('setup.runtime.refresh') }}</span>
      </button>
      <button v-if="canRevealLog" type="button" class="btn btn--ghost" :disabled="!logAvailable" @click="revealLog">
        <Icon name="logs" :size="15" />
        <span>{{ t('setup.runtime.revealLog') }}</span>
      </button>
      <button v-if="canRestart" type="button" class="btn btn--ghost" :disabled="busy" @click="restartGateway">
        <Icon name="refresh" :size="15" />
        <span>{{ t('setup.runtime.restartRuntime') }}</span>
      </button>
    </div>

    <div v-if="canReset" class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.resetLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.resetDesc') }}</span>
      </div>
      <div class="control-row__control">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="resetSetup">
          {{ t('setup.runtime.resetButton') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.runtime-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.runtime-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.runtime-reset {
  color: var(--danger);
}
</style>
