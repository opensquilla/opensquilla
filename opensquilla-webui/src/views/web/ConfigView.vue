<template>
  <!-- Intentionally empty: this route renders nothing of its own. -->
  <div aria-hidden="true"></div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

// /config deep link: opens the settings dialog on the default section
// over the default view instead of rendering a standalone page.
const appStore = useAppStore()
const router = useRouter()

onMounted(() => {
  appStore.setSettingsOpen(true)
  router.replace('/')
})
</script>
