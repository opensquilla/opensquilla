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

// Desktop data cleanup is wired directly on the desktop preload bridge
// (desktop-only, self-contained — it shells out to `opensquilla uninstall` in
// the Python core). It does not remove the installed app bundle itself.
interface UninstallBridge {
  uninstallRun?: (payload: { purgeData: boolean }) => Promise<{ ok: boolean; aborted?: boolean; detail?: string }>
  quitApp?: () => Promise<unknown>
}
const desktopBridge = (
  globalThis as unknown as { opensquillaDesktop?: UninstallBridge }
).opensquillaDesktop
const canUninstall = computed(() => Boolean(desktopBridge?.uninstallRun))

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

async function uninstall(purgeData: boolean) {
  if (!desktopBridge?.uninstallRun) return
  const ok = await confirm(
    purgeData
      ? {
          title: t('setup.runtime.uninstallPurgeTitle'),
          body: t('setup.runtime.uninstallPurgeBody'),
          primaryLabel: t('setup.runtime.uninstallPurgePrimary'),
        }
      : {
          title: t('setup.runtime.uninstallConfirmTitle'),
          body: t('setup.runtime.uninstallConfirmBody'),
          primaryLabel: t('setup.runtime.uninstallConfirmPrimary'),
        },
  )
  if (!ok) return
  busy.value = true
  try {
    const result = await desktopBridge.uninstallRun({ purgeData })
    if (result?.aborted) {
      // Cancelled at the native dialog, or refused (e.g. a gateway still running).
      // Not an error — surface the reason only when it is informative.
      if (result.detail && result.detail !== 'cancelled') {
        pushToast(result.detail, { tone: 'danger' })
      }
      return
    }
    if (!result?.ok) {
      pushToast(t('setup.runtime.uninstallFailed', { detail: result?.detail || t('setup.runtime.uninstallCheckLog') }), { tone: 'danger' })
      return
    }
    pushToast(t('setup.runtime.uninstallDone'))
    await desktopBridge.quitApp?.()
  } catch (err) {
    pushToast(t('setup.runtime.uninstallFailed', { detail: err instanceof Error ? err.message : String(err) }), { tone: 'danger' })
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

    <div v-if="canUninstall" class="control-row danger-zone">
      <div class="control-row__label-block">
        <span class="control-row__label">{{ t('setup.runtime.uninstallLabel') }}</span>
        <span class="control-row__desc">{{ t('setup.runtime.uninstallDesc') }}</span>
      </div>
      <div class="control-row__control danger-zone__actions">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(false)">
          {{ t('setup.runtime.uninstallKeepData') }}
        </button>
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(true)">
          {{ t('setup.runtime.uninstallPurge') }}
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

.danger-zone__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
</style>
