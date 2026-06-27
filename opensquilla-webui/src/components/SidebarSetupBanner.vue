<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'
import { useRpcCall } from '@/composables/useRpc'
import {
  useReadinessSummary,
  type ReadinessStatus,
} from '@/composables/setup/useReadinessSummary'

const router = useRouter()
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
</script>

<template>
  <section
    v-if="visible"
    class="sidebar-setup-banner"
    role="status"
    aria-live="polite"
    aria-label="Gateway setup needed"
  >
    <div class="sidebar-setup-banner__row">
      <Icon class="sidebar-setup-banner__icon" name="info" :size="15" aria-hidden="true" />
      <span class="sidebar-setup-banner__text">
        Setup needed<span v-if="actionCount > 1"> ({{ actionCount }})</span>
      </span>
      <button
        type="button"
        class="sidebar-setup-banner__dismiss"
        title="Dismiss"
        aria-label="Dismiss setup notice"
        @click="dismiss"
      >
        <Icon name="x" :size="13" aria-hidden="true" />
      </button>
    </div>
    <p class="sidebar-setup-banner__hint">The gateway isn't ready to run yet.</p>
    <div class="sidebar-setup-banner__actions">
      <button type="button" class="sidebar-setup-banner__cta" @click="openSetup">
        Finish setup
      </button>
      <button type="button" class="sidebar-setup-banner__link" @click="openReadiness">
        View readiness
      </button>
    </div>
  </section>
</template>
