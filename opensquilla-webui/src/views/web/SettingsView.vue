<template>
  <!-- Route-mounted overlay: the dialog keeps the modal look and owns its own
       a11y, section↔URL sync, and close→navigation behavior. -->
  <SettingsDialog />
</template>

<script setup lang="ts">
import SettingsDialog from '@/components/settings/SettingsDialog.vue'
</script>
