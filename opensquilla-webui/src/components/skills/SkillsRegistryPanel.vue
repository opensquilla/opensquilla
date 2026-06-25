<template>
  <div class="sk-registry">
    <div class="sk-registry__head">
      <div class="sk-search-wrap sk-search-wrap--lg">
        <span class="sk-search-icon">
          <Icon name="search" :size="16" />
        </span>
        <input
          :value="registryQuery"
          class="sk-search-input sk-search-input--lg"
          type="search"
          placeholder="Search community skills..."
          autocomplete="off"
          @input="emit('update:registryQuery', ($event.target as HTMLInputElement).value)"
          @keydown.enter="emit('search')"
        />
      </div>
      <button class="btn btn--primary" @click="emit('search')">Search</button>
    </div>
    <div class="sk-github-install">
      <div class="sk-search-wrap sk-search-wrap--lg">
        <span class="sk-search-icon">
          <Icon name="download" :size="16" />
        </span>
        <input
          :value="githubUrl"
          class="sk-search-input sk-search-input--lg"
          type="url"
          placeholder="https://github.com/owner/repo/tree/main/path/to/skill"
          autocomplete="off"
          @input="emit('update:githubUrl', ($event.target as HTMLInputElement).value)"
          @keydown.enter="emit('installGithub')"
        />
      </div>
      <button class="btn btn--primary" @click="emit('installGithub')">Install GitHub URL</button>
    </div>
    <div class="sk-registry__results">
      <template v-if="loading">
        <div class="sk-registry__loading">
          <span class="sk-spinner" />
          Searching ClawHub...
        </div>
      </template>
      <template v-else-if="results.length === 0">
        <div class="sk-registry__hint">
          <div class="sk-registry__hint-icon">
            <Icon name="skills" :size="36" />
          </div>
          <p>Search ClawHub skills to browse and install.</p>
          <p class="sk-dim">Paste a GitHub skill URL above for direct install.</p>
        </div>
      </template>
      <template v-else>
        <DataTable class="sk-registry-table" :columns="resultColumns" :rows="resultRows">
          <template #name="{ row }">
            <span class="sk-registry__name">{{ row.name }}</span>
          </template>
          <template #description="{ row }">
            <span class="sk-registry__desc">{{ row.description }}</span>
          </template>
          <template #source="{ row }">
            <span class="sk-mono sk-dim">{{ row.source }}</span>
          </template>
          <template #trust="{ row }">
            <span class="sk-chip" :class="row.trusted ? 'sk-chip--ok' : 'sk-chip--warn'">{{ row.trustLabel }}</span>
          </template>
          <template #_install="{ row }">
            <button v-if="row.installed" class="btn btn--sm" disabled>Installed</button>
            <button
              v-else
              class="btn btn--primary btn--sm"
              :disabled="installingId === row.installId"
              @click="emit('install', String(row.installId), String(row.installSource))"
            >
              {{ installingId === row.installId ? 'Installing...' : 'Install' }}
            </button>
          </template>
        </DataTable>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DataTable from '@/components/DataTable.vue'
import Icon from '@/components/Icon.vue'
import type { RegistryResult } from '@/types/skills'

const props = defineProps<{
  registryQuery: string
  githubUrl: string
  results: RegistryResult[]
  loading: boolean
  installingId: string | null
}>()

const emit = defineEmits<{
  'update:registryQuery': [value: string]
  'update:githubUrl': [value: string]
  search: []
  installGithub: []
  install: [identifier: string, source: string]
}>()

const resultColumns = [
  { key: 'name', label: 'Name' },
  { key: 'description', label: 'Description' },
  { key: 'source', label: 'Source' },
  { key: 'trust', label: 'Trust' },
  { key: '_install', label: '' },
]

const resultRows = computed(() =>
  props.results.map(r => ({
    name: r.name,
    description: (r.description || '').slice(0, 80),
    source: r.source || '',
    trusted: r.trust_level === 'trusted',
    trustLabel: r.trust_level || 'community',
    installed: !!r.installed,
    installId: r.identifier || r.name,
    installSource: r.source || 'clawhub',
  })),
)
</script>
