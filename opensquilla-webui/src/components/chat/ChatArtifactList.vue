<template>
  <div v-if="artifacts.length" class="msg-artifacts">
    <div v-if="visualArtifacts.length" class="msg-artifact-previews">
      <a
        v-for="artifact in visualArtifacts"
        :key="`preview-${artifact.id || artifact.name}`"
        class="msg-artifact-preview"
        :href="previewUrlFor(artifact) || undefined"
        target="_blank"
        rel="noopener noreferrer"
        :title="artifactFileTitle(artifact)"
        @click.prevent="openPreview(artifact)"
      >
        <img
          v-if="previewUrlFor(artifact)"
          :src="previewUrlFor(artifact)"
          :alt="artifactFileTitle(artifact)"
          loading="lazy"
        />
        <span v-else class="msg-artifact-preview__placeholder">Preview loading</span>
      </a>
    </div>
    <div class="msg-artifact-files">
      <ArtifactChip
        v-for="artifact in artifacts"
        :key="artifact.id || artifact.name"
        :artifact="artifact"
        :category="artifactCategory(artifact)"
        :icon-name="artifactIconName(artifact)"
        :title="artifactFileTitle(artifact)"
        :subtitle="artifactFileSubtitle(artifact)"
        :action-label="artifactActionLabel(artifact)"
        @download="$emit('download', $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import ArtifactChip from '@/components/chat/ArtifactChip.vue'
import type { ArtifactPayload } from '@/types/rpc'
import {
  artifactActionLabel,
  artifactCategory,
  artifactDownloadUrl,
  artifactFileSubtitle,
  artifactFileTitle,
  artifactIconName,
} from '@/utils/chat/artifacts'

const props = defineProps<{
  artifacts: ArtifactPayload[]
  sessionKey?: string
  authToken?: string
}>()

defineEmits<{
  download: [artifact: ArtifactPayload]
}>()

const visualArtifacts = computed(() => props.artifacts.filter(artifact => artifactCategory(artifact) === 'visual'))
const previewUrls = ref<Record<string, string>>({})
let previewLoadSeq = 0

function artifactKey(artifact: ArtifactPayload): string {
  return String(artifact.id || artifact.download_url || artifact.name || '')
}

function revokePreviewUrls(urls: Record<string, string>) {
  for (const url of Object.values(urls)) {
    try { URL.revokeObjectURL(url) } catch {}
  }
}

function previewUrlFor(artifact: ArtifactPayload): string {
  return previewUrls.value[artifactKey(artifact)] || ''
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

function openPreview(artifact: ArtifactPayload) {
  const url = previewUrlFor(artifact)
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

watch(
  () => [visualArtifacts.value.map(artifactKey).join('|'), props.sessionKey || '', props.authToken || ''],
  () => { void loadPreviewUrls() },
  { immediate: true },
)

onUnmounted(() => {
  previewLoadSeq += 1
  revokePreviewUrls(previewUrls.value)
})
</script>

<style scoped>
.msg-artifacts {
  margin: 0.75rem 0 0.875rem;
}

.msg-artifact-files {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 100%;
  margin: 0 auto;
}

.msg-artifact-previews {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.msg-artifact-preview {
  display: block;
  overflow: hidden;
  border: 1px solid rgba(32, 39, 34, 0.12);
  border-radius: 8px;
  background: #f7f7f8;
}

.msg-artifact-preview img {
  display: block;
  width: 100%;
  max-height: 320px;
  object-fit: contain;
}

.msg-artifact-preview__placeholder {
  display: flex;
  min-height: 120px;
  align-items: center;
  justify-content: center;
  color: #6f746f;
  font-size: 0.78rem;
}
</style>
