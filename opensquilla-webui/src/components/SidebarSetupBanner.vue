<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'
import SetupCommandBlock from './setup/SetupCommandBlock.vue'
import { useRpcCall } from '@/composables/useRpc'
import { useToasts } from '@/composables/useToasts'
import {
  readinessLegacyData,
  useReadinessSummary,
  type ReadinessStatus,
} from '@/composables/setup/useReadinessSummary'
import { usePlatform } from '@/platform'
import { copyTextWithFallback } from '@/utils/browser'

const { t } = useI18n()
const router = useRouter()
const { pushToast } = useToasts()
const platform = usePlatform()
const { data: status } = useRpcCall<ReadinessStatus>('onboarding.status')
const { needsAction, actionCount } = useReadinessSummary(status)

// Per-session dismissal that re-arms when the readiness signal changes.
const dismissedSignature = ref<string | null>(null)
const signature = computed(() => JSON.stringify({
  n: status.value?.needsOnboarding,
  s: status.value?.llmSource,
  d: status.value?.sectionDetails,
}))
const visible = computed(() => needsAction.value && dismissedSignature.value !== signature.value)

function dismiss() { dismissedSignature.value = signature.value }
// Lands on the first not-ready section of the Settings dialog.
function openSetup() { router.push('/settings/auto') }
// Inline readiness report.
function openReadiness() { router.push('/overview') }

// Legacy-home advisory: detection is a read-only scan safe under a running
// gateway, but the import itself needs a quiesced gateway, so this banner only
// advises. On the web the operator stops the gateway and runs the suggested
// CLI command; on desktop the Settings → Runtime "Import legacy data" action
// owns the whole stop → import → restart lifecycle.
const isDesktop = platform.capabilities.isDesktop
const legacy = computed(() => readinessLegacyData(status.value))

// Same per-session dismissal shape as the setup notice, keyed on its own
// signature so a changed detection (different path/command) re-arms it.
const legacyDismissedSignature = ref<string | null>(null)
const legacySignature = computed(() => JSON.stringify(legacy.value))
const legacyVisible = computed(
  () => legacy.value !== null && legacyDismissedSignature.value !== legacySignature.value,
)

function dismissLegacy() { legacyDismissedSignature.value = legacySignature.value }
function openRuntimeSettings() { router.push('/settings/runtime') }

async function copyMigrateCommand(command: string) {
  try {
    await copyTextWithFallback(command)
    pushToast(t('setup.toast.copiedCommand'), { tone: 'ok' })
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err)
    pushToast(t('setup.toast.copyFailed', { error }), { tone: 'danger' })
  }
}
</script>

<template>
  <section
    v-if="visible"
    class="sidebar-setup-banner"
    role="status"
    aria-live="polite"
    :aria-label="t('shared.setupBanner.ariaLabel')"
  >
    <div class="sidebar-setup-banner__row">
      <Icon class="sidebar-setup-banner__icon" name="info" :size="15" aria-hidden="true" />
      <span class="sidebar-setup-banner__text">
        {{ t('shared.setupBanner.title') }}<span v-if="actionCount > 1"> ({{ actionCount }})</span>
      </span>
      <button
        type="button"
        class="sidebar-setup-banner__dismiss"
        :title="t('shared.setupBanner.dismiss')"
        :aria-label="t('shared.setupBanner.dismissNotice')"
        @click="dismiss"
      >
        <Icon name="x" :size="13" aria-hidden="true" />
      </button>
    </div>
    <p class="sidebar-setup-banner__hint">{{ t('shared.setupBanner.hint') }}</p>
    <div class="sidebar-setup-banner__actions">
      <button type="button" class="sidebar-setup-banner__cta" @click="openSetup">
        {{ t('shared.setupBanner.finishSetup') }}
      </button>
      <button type="button" class="sidebar-setup-banner__link" @click="openReadiness">
        {{ t('shared.setupBanner.viewReadiness') }}
      </button>
    </div>
  </section>

  <section
    v-if="legacyVisible && legacy"
    class="sidebar-setup-banner sidebar-setup-banner--legacy"
    role="status"
    aria-live="polite"
    :aria-label="t('shared.legacyDataBanner.ariaLabel')"
    data-testid="legacy-data-banner"
  >
    <div class="sidebar-setup-banner__row">
      <Icon class="sidebar-setup-banner__icon" name="info" :size="15" aria-hidden="true" />
      <span class="sidebar-setup-banner__text">{{ t('shared.legacyDataBanner.title') }}</span>
      <button
        type="button"
        class="sidebar-setup-banner__dismiss"
        :title="t('shared.legacyDataBanner.dismiss')"
        :aria-label="t('shared.legacyDataBanner.dismissNotice')"
        data-testid="legacy-data-dismiss"
        @click="dismissLegacy"
      >
        <Icon name="x" :size="13" aria-hidden="true" />
      </button>
    </div>
    <p class="sidebar-setup-banner__path" data-testid="legacy-data-path">
      <code>{{ legacy.path }}</code>
    </p>
    <template v-if="isDesktop">
      <p class="sidebar-setup-banner__hint">{{ t('shared.legacyDataBanner.hintDesktop') }}</p>
      <div class="sidebar-setup-banner__actions">
        <button
          type="button"
          class="sidebar-setup-banner__cta"
          data-testid="legacy-data-open-settings"
          @click="openRuntimeSettings"
        >
          {{ t('shared.legacyDataBanner.openSettings') }}
        </button>
      </div>
    </template>
    <template v-else>
      <p class="sidebar-setup-banner__hint">{{ t('shared.legacyDataBanner.hintWeb') }}</p>
      <SetupCommandBlock
        :command="legacy.command"
        :copy-label="t('shared.legacyDataBanner.copyCommand')"
        @copy="copyMigrateCommand"
      />
    </template>
  </section>
</template>
