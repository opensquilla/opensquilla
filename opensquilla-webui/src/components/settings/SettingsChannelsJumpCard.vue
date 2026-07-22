<script setup lang="ts">
// Channel setup now lives on the /channels workspace; this settings section
// keeps its rail slot as a compact jump card so the old destination still
// answers, with a live one-line status summary when channels.status responds
// cheaply and static copy when it does not.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { useRpcStore } from '@/stores/rpc'

const { t } = useI18n()
const router = useRouter()
const rpc = useRpcStore()

interface StatusRow {
  configured?: boolean
  connected?: boolean
}

const rows = ref<StatusRow[] | null>(null)

onMounted(async () => {
  try {
    await rpc.waitForConnection()
    const res = await rpc.call<{ channels?: StatusRow[] }>('channels.status')
    rows.value = (res?.channels || []).filter(row => row.configured !== false)
  } catch {
    rows.value = null // static copy stands in
  }
})

const summary = computed(() => {
  if (rows.value === null) return ''
  if (rows.value.length === 0) return t('setup.channels.jump.summaryEmpty')
  return t('setup.channels.jump.summary', {
    count: rows.value.length,
    connected: rows.value.filter(row => row.connected).length,
  })
})

function openWorkspace() {
  void router.push('/channels')
}

function addChannel() {
  void router.push({ path: '/channels', query: { compose: '1' } })
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">{{ t('setup.channels.title') }}</h3>
      <p class="control-section__desc">{{ t('setup.channels.jump.description') }}</p>
    </div>
    <div class="scj">
      <Icon name="channels" :size="20" aria-hidden="true" />
      <p class="scj__summary">{{ summary || t('setup.channels.jump.summaryStatic') }}</p>
      <div class="scj__actions">
        <button type="button" class="btn btn--primary" @click="openWorkspace">
          {{ t('setup.channels.jump.open') }}
        </button>
        <button type="button" class="btn btn--ghost" @click="addChannel">
          {{ t('console.channels.addChannel') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.scj {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}
.scj > svg { color: var(--text-muted); flex: none; }
.scj__summary { color: var(--text-muted); flex: 1 1 220px; font-size: var(--fs-sm); line-height: 1.5; margin: 0; min-width: 0; }
.scj__actions { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-left: auto; }
</style>
