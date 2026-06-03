<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { IconName } from '@/utils/icons'
import type { ArtifactPayload } from '@/types/rpc'

defineProps<{
  artifact: ArtifactPayload
  category: string
  iconName: IconName
  title: string
  subtitle: string
  actionLabel: string
}>()

defineEmits<{
  download: [artifact: ArtifactPayload]
}>()
</script>

<template>
  <button
    type="button"
    class="msg-artifact-chip"
    @click="$emit('download', artifact)"
  >
    <span class="msg-artifact-icon" :data-kind="category" aria-hidden="true">
      <Icon :name="iconName" :size="22" />
    </span>
    <span class="msg-artifact-info">
      <span class="msg-artifact-name">{{ title }}</span>
      <span class="msg-artifact-meta">{{ subtitle }}</span>
    </span>
    <span class="msg-artifact-action">{{ actionLabel }}</span>
  </button>
</template>

<style scoped>
.msg-artifact-chip {
  display: grid;
  grid-template-columns: 3rem minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.875rem;
  width: 100%;
  padding: 0.75rem;
  border: 1px solid rgba(31, 35, 40, 0.08);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.14s ease, box-shadow 0.14s ease, transform 0.14s ease;
}

.msg-artifact-chip:hover {
  border-color: rgba(31, 35, 40, 0.18);
  box-shadow: 0 3px 10px rgba(31, 35, 40, 0.08);
  transform: translateY(-1px);
}

.msg-artifact-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 3rem;
  height: 3rem;
  border-radius: 8px;
  color: #315f68;
  background: #f2f8f7;
}

.msg-artifact-icon[data-kind="data"] {
  color: #5d552f;
  background: #faf7ec;
}

.msg-artifact-icon[data-kind="code"] {
  color: #70452b;
  background: #fbf4ef;
}

.msg-artifact-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.msg-artifact-name {
  color: #202722;
  font-size: 0.9375rem;
  font-weight: 500;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-artifact-meta {
  color: #8a9189;
  font-size: 0.8125rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-artifact-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 4rem;
  min-height: 2.125rem;
  padding: 0 0.875rem;
  border-radius: 999px;
  background: #f6f7f4;
  color: #262b27;
  font-size: 0.8125rem;
  font-weight: 500;
  white-space: nowrap;
  transition: background 0.14s ease, color 0.14s ease;
}

.msg-artifact-chip:hover .msg-artifact-action {
  background: #202722;
  color: #fff;
}

@media (max-width: 640px) {
  .msg-artifact-chip {
    grid-template-columns: 2.75rem minmax(0, 1fr);
    gap: 0.75rem;
    padding: 0.625rem;
  }

  .msg-artifact-icon {
    width: 2.75rem;
    height: 2.75rem;
  }

  .msg-artifact-action {
    grid-column: 2;
    justify-self: start;
    min-height: 1.875rem;
    min-width: 3.5rem;
    margin-top: 0.125rem;
  }
}
</style>
