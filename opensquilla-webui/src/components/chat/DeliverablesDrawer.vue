<template>
  <div v-if="open" class="deliv-overlay" @click.self="emit('close')">
    <aside
      ref="drawerRef"
      class="deliv-drawer"
      role="dialog"
      aria-modal="true"
      :aria-label="`Deliverables (${artifacts.length})`"
    >
      <header class="deliv-head">
        <h3 class="deliv-head__title">Deliverables</h3>
        <span class="deliv-head__count" aria-hidden="true">{{ artifacts.length }}</span>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          aria-label="Close"
          title="Close"
          @click="emit('close')"
        >
          <Icon name="x" :size="16" />
        </button>
      </header>

      <div class="deliv-body" aria-label="Session deliverables">
        <p v-if="artifacts.length === 0" class="deliv-empty">No deliverables yet.</p>
        <ul v-else class="deliv-grid">
          <li v-for="artifact in artifacts" :key="artifactKey(artifact)" class="deliv-tile-wrap">
            <button
              type="button"
              class="deliv-tile"
              :title="artifactFileTitle(artifact)"
              @click="openPreview(artifact)"
            >
              <span class="deliv-tile__thumb" :data-kind="artifactCategory(artifact)">
                <img
                  v-if="previewUrlFor(artifact)"
                  :src="previewUrlFor(artifact)"
                  :alt="artifactFileTitle(artifact)"
                  loading="lazy"
                />
                <Icon v-else :name="artifactIconName(artifact)" :size="26" />
              </span>
              <span class="deliv-tile__name">{{ artifactFileTitle(artifact) }}</span>
              <span class="deliv-tile__meta">{{ artifactTileMeta(artifact) }}</span>
            </button>
          </li>
        </ul>
      </div>
    </aside>

    <!-- Larger preview: image lightbox, or metadata + download for non-images -->
    <div
      v-if="active"
      class="deliv-preview"
      role="dialog"
      aria-modal="true"
      :aria-label="`Preview: ${artifactFileTitle(active)}`"
      @click.self="closePreview"
    >
      <div class="deliv-preview__panel">
        <header class="deliv-preview__head">
          <span class="deliv-preview__title">{{ artifactFileTitle(active) }}</span>
          <button
            ref="previewCloseBtn"
            type="button"
            class="btn btn--icon btn--ghost"
            aria-label="Close preview"
            title="Close preview"
            @click="closePreview"
          >
            <Icon name="x" :size="16" />
          </button>
        </header>
        <div class="deliv-preview__body">
          <img
            v-if="previewUrlFor(active)"
            class="deliv-preview__image"
            :src="previewUrlFor(active)"
            :alt="artifactFileTitle(active)"
          />
          <div v-else class="deliv-preview__file">
            <span class="deliv-preview__icon" :data-kind="artifactCategory(active)" aria-hidden="true">
              <Icon :name="artifactIconName(active)" :size="40" />
            </span>
            <p class="deliv-preview__meta">{{ artifactFileSubtitle(active) }}</p>
          </div>
        </div>
        <footer class="deliv-preview__actions">
          <button type="button" class="btn btn--primary" @click="emit('download', active)">
            <Icon name="download" :size="14" />
            <span>{{ artifactActionLabel(active) === 'Preview' ? 'Download' : artifactActionLabel(active) }}</span>
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ArtifactPayload } from '@/types/rpc'
import {
  artifactActionLabel,
  artifactCategory,
  artifactCategoryLabel,
  artifactDownloadUrl,
  artifactFileSubtitle,
  artifactFileTitle,
  artifactIconName,
  artifactMeta,
} from '@/utils/chat/artifacts'

const props = defineProps<{
  open: boolean
  artifacts: ArtifactPayload[]
  sessionKey?: string
  authToken?: string
}>()

const emit = defineEmits<{
  close: []
  download: [artifact: ArtifactPayload]
}>()

const drawerRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const previewCloseBtn = ref<HTMLButtonElement | null>(null)
const active = ref<ArtifactPayload | null>(null)

let invokerEl: HTMLElement | null = null

/* ── Secure blob previews ──────────────────────────────────────────────
   Mirrors ChatArtifactList: image artifacts are fetched with auth headers
   (never credentials in the URL) and rendered as revocable object URLs. */

const visualArtifacts = computed(() =>
  props.artifacts.filter(artifact => artifactCategory(artifact) === 'visual'))
const previewUrls = ref<Record<string, string>>({})
let previewLoadSeq = 0

function artifactKey(artifact: ArtifactPayload): string {
  return String(artifact.id || artifact.download_url || artifact.name || '')
}

function previewUrlFor(artifact: ArtifactPayload | null): string {
  if (!artifact) return ''
  return previewUrls.value[artifactKey(artifact)] || ''
}

function artifactTileMeta(artifact: ArtifactPayload): string {
  return [artifactCategoryLabel(artifact).toUpperCase(), artifactMeta(artifact)].filter(Boolean).join(' · ')
}

function sameOrigin(url: string): boolean {
  try {
    return new URL(url, window.location.origin).origin === window.location.origin
  } catch { return false }
}

function previewHeaders(url: string): Record<string, string> {
  if (!sameOrigin(url)) return {}
  const headers: Record<string, string> = {}
  if (props.sessionKey) headers['x-opensquilla-session-key'] = props.sessionKey
  if (props.authToken) headers.Authorization = `Bearer ${props.authToken}`
  return headers
}

function revokePreviewUrls(urls: Record<string, string>) {
  for (const url of Object.values(urls)) {
    try { URL.revokeObjectURL(url) } catch {}
  }
}

async function loadPreviewUrls() {
  const seq = ++previewLoadSeq
  const entries = await Promise.all(visualArtifacts.value.map(async artifact => {
    const url = artifactDownloadUrl(artifact, window.location.origin, {
      sessionKey: props.sessionKey,
      includeSessionKey: false,
    })
    if (!url) return null
    try {
      const isSameOrigin = sameOrigin(url)
      const response = await fetch(url, {
        method: 'GET',
        headers: previewHeaders(url),
        credentials: isSameOrigin ? 'same-origin' : 'omit',
      })
      if (!response.ok || seq !== previewLoadSeq) return null
      const blob = await response.blob()
      if (seq !== previewLoadSeq) return null
      return [artifactKey(artifact), URL.createObjectURL(blob)] as const
    } catch {
      return null
    }
  }))
  const nextUrls: Record<string, string> = {}
  for (const entry of entries) {
    if (entry) nextUrls[entry[0]] = entry[1]
  }
  if (seq !== previewLoadSeq) {
    revokePreviewUrls(nextUrls)
    return
  }
  const previousUrls = previewUrls.value
  previewUrls.value = nextUrls
  revokePreviewUrls(previousUrls)
}

/* ── Preview (lightbox / metadata) ─────────────────────────────────────── */

function openPreview(artifact: ArtifactPayload) {
  active.value = artifact
  nextTick(() => previewCloseBtn.value?.focus())
}

function closePreview() {
  active.value = null
  nextTick(() => closeBtn.value?.focus())
}

/* ── Dialog a11y: focus trap, Escape, focus return ─────────────────────── */

function trapFocus(event: KeyboardEvent, rootEl: HTMLElement | null) {
  if (event.key !== 'Tab' || !rootEl) return
  const focusables = Array.from(rootEl.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const activeEl = document.activeElement as HTMLElement | null
  const inside = !!activeEl && rootEl.contains(activeEl)
  if (event.shiftKey && (!inside || activeEl === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || activeEl === last)) {
    event.preventDefault()
    first.focus()
  }
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    if (active.value) closePreview()
    else emit('close')
    return
  }
  // Trap focus inside whichever dialog is on top.
  if (active.value) {
    const panel = drawerRef.value?.parentElement?.querySelector<HTMLElement>('.deliv-preview__panel') || null
    trapFocus(event, panel)
  } else {
    trapFocus(event, drawerRef.value)
  }
}

watch(
  () => props.open,
  (open, wasOpen) => {
    if (open && !wasOpen) {
      invokerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', onDocumentKeydown)
      void loadPreviewUrls()
      nextTick(() => closeBtn.value?.focus())
    } else if (!open && wasOpen) {
      document.removeEventListener('keydown', onDocumentKeydown)
      active.value = null
      if (invokerEl && document.contains(invokerEl)) invokerEl.focus()
      invokerEl = null
    }
  },
)

// Refresh thumbnails when the open drawer's artifact set or auth changes.
watch(
  () => [props.open, visualArtifacts.value.map(artifactKey).join('|'), props.sessionKey || '', props.authToken || ''],
  () => { if (props.open) void loadPreviewUrls() },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  previewLoadSeq += 1
  revokePreviewUrls(previewUrls.value)
})
</script>

<style scoped src="../../styles/chat-view.css"></style>
