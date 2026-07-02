<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'
import { getPlatform } from '@/platform'

// Passive "a newer version is available" notice. The gateway injects the update
// info into #opensquilla-data (data-update) only when a newer published release
// exists; here we render an unobtrusive, dismissible card for it. No download
// or install happens from the web — the link points at the release page.
//
// Suppressed only where the host applies updates NATIVELY (electron-updater on
// macOS, via the "Check for Updates…" menu + native prompts), to avoid a double
// notice. On hosts without native auto-update — the browser, and desktop
// platforms not yet covered (e.g. unsigned Windows) — the banner stays, guiding
// the user to the release page. When Windows native update is later enabled,
// nativeAutoUpdateEnabled() flips to true there and the banner self-suppresses
// with no change here.

const { t } = useI18n()
const platform = getPlatform()
const isDesktop = platform.id === 'desktop'

const DISMISS_KEY = 'opensquilla-update-dismissed'
const RELEASES_FALLBACK = 'https://github.com/opensquilla/opensquilla/releases/latest'

interface UpdateInfo {
  current?: string
  latest?: string
  available?: boolean
  url?: string
}

function readUpdate(): UpdateInfo | null {
  try {
    const raw = document.getElementById('opensquilla-data')?.dataset.update
    if (!raw) return null
    const parsed = JSON.parse(raw) as UpdateInfo | null
    if (parsed && parsed.available === true && typeof parsed.latest === 'string' && parsed.latest) {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

const info = readUpdate()

// True where the host applies updates natively. Assume native on desktop until
// the shell confirms otherwise, so macOS never flashes the web banner; the
// browser starts false and shows immediately. Windows (pre-signing) resolves to
// false → banner appears; (post-signing) resolves to true → banner stays hidden.
const nativeUpdate = ref(isDesktop)
onMounted(async () => {
  try {
    nativeUpdate.value = await platform.nativeAutoUpdateEnabled()
  } catch {
    nativeUpdate.value = isDesktop
  }
})

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISS_KEY)
  } catch {
    return null
  }
}

// Dismissal is keyed to the version, so a future release re-arms the notice.
const dismissedVersion = ref<string | null>(readDismissed())
const visible = computed(
  () => !!info && !nativeUpdate.value && dismissedVersion.value !== info.latest,
)
const releaseUrl = computed(() => info?.url || RELEASES_FALLBACK)

function dismiss() {
  const latest = info?.latest ?? null
  dismissedVersion.value = latest
  try {
    if (latest) localStorage.setItem(DISMISS_KEY, latest)
  } catch {
    // localStorage unavailable (private mode) — dismissal is just session-local.
  }
}
</script>

<template>
  <div
    v-if="visible && info"
    class="update-banner"
    role="status"
    aria-live="polite"
    data-testid="update-banner"
  >
    <Icon class="update-banner__icon" name="download" :size="16" aria-hidden="true" />
    <div class="update-banner__body">
      <p class="update-banner__title">{{ t('updates.available', { version: info.latest }) }}</p>
      <a
        class="update-banner__link"
        :href="releaseUrl"
        target="_blank"
        rel="noopener noreferrer"
      >{{ t('updates.viewRelease') }}</a>
    </div>
    <button
      type="button"
      class="update-banner__dismiss"
      :title="t('updates.dismiss')"
      :aria-label="t('updates.dismiss')"
      @click="dismiss"
    >
      <Icon name="x" :size="14" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.update-banner {
  position: fixed;
  right: var(--sp-4);
  bottom: var(--sp-4);
  z-index: 950;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  max-width: 340px;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border-strong));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-elevated));
  color: var(--text);
  box-shadow: var(--shadow-md);
  animation: update-banner-in var(--dur-base) var(--ease-out);
}

.update-banner__icon {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--accent);
}

.update-banner__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.update-banner__title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.update-banner__link {
  align-self: flex-start;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--accent);
  text-decoration: none;
}

.update-banner__link:hover {
  text-decoration: underline;
}

.update-banner__link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

.update-banner__dismiss {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: var(--sp-1);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}

.update-banner__dismiss:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.update-banner__dismiss:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

@keyframes update-banner-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .update-banner {
    animation: none;
  }
}

@media (max-width: 768px) {
  .update-banner {
    left: var(--sp-4);
    max-width: none;
  }
}
</style>
