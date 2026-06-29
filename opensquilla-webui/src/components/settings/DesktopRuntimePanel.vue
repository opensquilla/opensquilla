<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import Icon from '@/components/Icon.vue'
import GatewayStatusBlock from '@/components/settings/GatewayStatusBlock.vue'
import { usePlatform, type GatewayStatus } from '@/platform'
import { useConfirm } from '@/composables/useConfirm'
import { useToasts } from '@/composables/useToasts'

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

const STATUS_LABELS: Record<string, string> = {
  starting: 'Starting',
  ready: 'Ready',
  stopped: 'Stopped',
  error: 'Error',
}

const statusLabel = computed(() => STATUS_LABELS[gateway.value?.status ?? ''] || 'Unknown')
const gatewayError = computed(() => gateway.value?.error || '')
const url = computed(() => gateway.value?.url || 'No active gateway')
const logAvailable = computed(() => Boolean(gateway.value?.logPath))
const logHint = computed(() => gateway.value?.logPath || 'No local log path')

// This panel only ever mounts on desktop (SettingsDialog gates it behind
// isDesktop), so the capability flags are always true here; gate the buttons on
// the optional methods actually being wired instead.
const canRevealLog = computed(() => Boolean(platform.gateway.revealLog))
const canRestart = computed(() => Boolean(platform.gateway.retryStartup))
const canReset = computed(() => Boolean(platform.settings.resetDesktopSettings))

// Uninstall is wired directly on the desktop preload bridge (desktop-only,
// self-contained — it shells out to `opensquilla uninstall` in the Python core).
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
    pushToast('Failed to read gateway status: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    loading.value = false
  }
}

async function revealLog() {
  if (!platform.gateway.revealLog) return
  try {
    const ok = await platform.gateway.revealLog()
    if (!ok) pushToast('No gateway log to reveal yet.', { tone: 'danger' })
  } catch (err) {
    pushToast('Could not reveal log: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

async function restartGateway() {
  if (!platform.gateway.retryStartup) return
  busy.value = true
  try {
    await platform.gateway.retryStartup()
    pushToast('Restarting the local runtime…')
    await loadStatus()
  } catch (err) {
    pushToast('Restart failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

async function resetSetup() {
  if (!platform.settings.resetDesktopSettings) return
  const ok = await confirm({
    title: 'Reset saved setup?',
    body: 'This clears the saved desktop credential and generated config. The next launch re-runs first-time setup.',
    primaryLabel: 'Reset',
  })
  if (!ok) return
  busy.value = true
  try {
    await platform.settings.resetDesktopSettings()
    pushToast('Saved setup cleared. Restart the desktop app to re-run setup.')
  } catch (err) {
    pushToast('Reset failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

async function uninstall(purgeData: boolean) {
  if (!desktopBridge?.uninstallRun) return
  const ok = await confirm(
    purgeData
      ? {
          title: 'Remove OpenSquilla and delete all data?',
          body: 'This removes the runtime AND permanently deletes all your data on this machine — sessions, configuration, and secrets. This cannot be undone.',
          primaryLabel: 'Delete everything',
        }
      : {
          title: 'Uninstall OpenSquilla?',
          body: 'This removes the OpenSquilla runtime but keeps your data (sessions, config, secrets) on disk.',
          primaryLabel: 'Uninstall',
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
      pushToast('Uninstall failed: ' + (result?.detail || 'check the gateway log.'), { tone: 'danger' })
      return
    }
    pushToast('OpenSquilla uninstalled. The app will now close.')
    await desktopBridge.quitApp?.()
  } catch (err) {
    pushToast('Uninstall failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    busy.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Runtime</h3>
      <p class="control-section__desc">The desktop app owns the local gateway and serves this Control UI from it.</p>
    </div>

    <div class="runtime-grid">
      <GatewayStatusBlock label="Gateway" :value="loading ? 'Loading…' : statusLabel" :hint="gatewayError || url" />
      <GatewayStatusBlock label="Runtime" value="Local" hint="Desktop-owned process" />
      <GatewayStatusBlock label="Gateway log" :value="logAvailable ? 'Available' : 'Unavailable'" :hint="logHint" />
    </div>

    <div class="runtime-actions">
      <button type="button" class="btn btn--ghost" :disabled="loading || busy" @click="loadStatus">
        <Icon name="refresh" :size="15" />
        <span>Refresh</span>
      </button>
      <button v-if="canRevealLog" type="button" class="btn btn--ghost" :disabled="!logAvailable" @click="revealLog">
        <Icon name="logs" :size="15" />
        <span>Reveal log</span>
      </button>
      <button v-if="canRestart" type="button" class="btn btn--ghost" :disabled="busy" @click="restartGateway">
        <Icon name="refresh" :size="15" />
        <span>Restart runtime</span>
      </button>
    </div>

    <div v-if="canReset" class="control-row">
      <div class="control-row__label-block">
        <span class="control-row__label">Reset saved setup</span>
        <span class="control-row__desc">Clear the saved credential and generated config, then re-run first-time setup on next launch.</span>
      </div>
      <div class="control-row__control">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="resetSetup">
          Reset
        </button>
      </div>
    </div>

    <div v-if="canUninstall" class="control-row danger-zone">
      <div class="control-row__label-block">
        <span class="control-row__label">Danger zone — uninstall OpenSquilla</span>
        <span class="control-row__desc">Remove the runtime. Keeping your data leaves sessions, config, and secrets on disk; deleting everything is permanent.</span>
      </div>
      <div class="control-row__control danger-zone__actions">
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(false)">
          Remove, keep my data
        </button>
        <button type="button" class="btn btn--ghost runtime-reset" :disabled="busy" @click="uninstall(true)">
          Remove and delete everything
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
