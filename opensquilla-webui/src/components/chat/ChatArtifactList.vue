<template>
  <div v-if="artifacts.length" class="msg-artifacts">
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
import ArtifactChip from '@/components/chat/ArtifactChip.vue'
import type { ArtifactPayload } from '@/types/rpc'
import {
  artifactActionLabel,
  artifactCategory,
  artifactFileSubtitle,
  artifactFileTitle,
  artifactIconName,
} from '@/utils/chat/artifacts'

defineProps<{
  artifacts: ArtifactPayload[]
}>()

defineEmits<{
  download: [artifact: ArtifactPayload]
}>()
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
</style>
