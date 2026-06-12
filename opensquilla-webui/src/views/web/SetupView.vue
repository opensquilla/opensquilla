<template>
  <!-- Intentionally empty: this route renders nothing of its own. -->
  <div aria-hidden="true"></div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

// /setup deep link: opens the settings dialog on the first section that
// still needs action (Provider when everything is ready).
const appStore = useAppStore()
const router = useRouter()

onMounted(() => {
  appStore.setSettingsOpen(true, 'auto')
  router.replace('/')
})
</script>
