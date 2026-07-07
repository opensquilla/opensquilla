<template>
  <!-- A read-not-operated surface: the first route to opt into the Out-of-Register
       expressive skin (meta.skin). Structure/type/colour come from the scoped
       skin.css via the .oor-* classes; this view only owns layout. -->
  <div class="oor-page">
    <p class="oor-kicker">OpenSquilla &middot; Field Notes</p>
    <h1 class="oor-mast" data-word="Changelog">Changelog</h1>
    <p class="oor-lead">
      What shipped, in the house editorial voice &mdash; a page you read, not one
      you operate, so it can afford the broadsheet treatment the console never should.
    </p>
    <div class="oor-meter">
      <span class="oor-tag">Theme engine &middot; rollout</span>
      <CoverageBar :value="3" :max="4" label="3 / 4 stages" />
    </div>
    <hr class="oor-rule" />
    <article v-for="entry in entries" :key="entry.version" class="oor-entry">
      <span class="oor-tag">{{ entry.version }} &middot; {{ entry.date }}</span>
      <h3>{{ entry.title }}</h3>
      <p>{{ entry.body }}</p>
    </article>
  </div>
</template>

<script setup lang="ts">
import CoverageBar from '@/components/CoverageBar.vue'

interface Entry {
  version: string
  date: string
  title: string
  body: string
}

const entries: Entry[] = [
  {
    version: 'v0.3',
    date: '2026-07-06',
    title: 'A pluggable theme engine',
    body:
      'Light and dark moved onto a layered token contract, and expressive skins can now plug in per route. This page is the first one to opt in — the console itself stays on the Instrument system.',
  },
  {
    version: 'v0.2',
    date: '2026-06',
    title: 'Instrument redesign',
    body:
      'Radius-as-rank, machined elevation, and a single strike accent replaced the uniform, over-rounded look — the foundation the theme layer now generalises.',
  },
]
</script>

<style scoped>
.oor-page {
  max-width: 940px;
  margin: 0 auto;
  padding: clamp(28px, 5vw, 64px) clamp(16px, 4vw, 48px) 80px;
}
.oor-page > * + * {
  margin-top: 1rem;
}
.oor-mast {
  margin-top: 0.5rem;
}
.oor-meter {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 420px;
}
</style>
