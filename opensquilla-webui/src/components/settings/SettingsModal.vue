<template>
  <!-- Mounted per open so the dialog loads fresh config/readiness each time. -->
  <SettingsDialog v-if="appStore.settingsOpen" />
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import SettingsDialog from './SettingsDialog.vue'

const appStore = useAppStore()
</script>
