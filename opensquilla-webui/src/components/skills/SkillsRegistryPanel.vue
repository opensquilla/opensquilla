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
        <table class="sk-registry__table">
          <thead>
            <tr><th>Name</th><th>Description</th><th>Source</th><th>Trust</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="r in results" :key="r.identifier || r.name">
              <td class="sk-registry__name">{{ r.name }}</td>
              <td class="sk-registry__desc">{{ (r.description || '').slice(0, 80) }}</td>
              <td class="sk-mono sk-dim">{{ r.source || '' }}</td>
              <td>
                <span class="sk-chip" :class="r.trust_level === 'trusted' ? 'sk-chip--ok' : 'sk-chip--warn'">{{ r.trust_level || 'community' }}</span>
              </td>
              <td>
                <button
                  v-if="r.installed"
                  class="btn btn--sm"
                  disabled
                >Installed</button>
                <button
                  v-else
                  class="btn btn--primary btn--sm"
                  :disabled="installingId === (r.identifier || r.name)"
                  @click="emit('install', r.identifier || r.name, r.source || 'clawhub')"
                >
                  {{ installingId === (r.identifier || r.name) ? 'Installing...' : 'Install' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { RegistryResult } from '@/types/skills'

defineProps<{
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
</script>
