<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { useDocumentEvent } from '@/composables/useDocumentEvent'
import { useToasts } from '@/composables/useToasts'
import { useBgm, BGM_LOCAL_TRACK_ID } from '@/composables/useBgm'

// Topbar background-music control: a split button next to the language/theme
// menus. The note button toggles play/pause of the current track; the caret
// opens a picker (reusing the global .theme-menu* classes so the three topbar
// popovers can never drift in look) with the playlist.json tracks, uploads
// persisted in the in-app library, a play-mode row, a volume slider, and an
// "Add local music…" picker.

const { t } = useI18n()
const { pushToast } = useToasts()
const {
  tracks,
  localTracks,
  playing,
  currentTrackId,
  currentTitle,
  volume,
  muted,
  progress,
  duration,
  playMode,
  localTrackTitle,
  initBgm,
  toggle,
  playNext,
  playPrevious,
  selectTrack,
  setVolume,
  toggleMute,
  seek,
  setPlayMode,
  addLocalFiles,
  renameLocalTrack,
  removeLocalTrack,
} = useBgm()

// Single cycling control, like most music players: each click advances to the
// next mode in this order.
const PLAY_MODES = [
  { mode: 'order', icon: 'repeat', labelKey: 'chrome.bgm.modeOrder' },
  { mode: 'shuffle', icon: 'shuffle', labelKey: 'chrome.bgm.modeShuffle' },
  { mode: 'one', icon: 'repeat-one', labelKey: 'chrome.bgm.modeOne' },
] as const

const currentMode = computed(() =>
  PLAY_MODES.find(entry => entry.mode === playMode.value) ?? PLAY_MODES[0])

function cycleMode() {
  const idx = PLAY_MODES.findIndex(entry => entry.mode === playMode.value)
  setPlayMode(PLAY_MODES[(idx + 1) % PLAY_MODES.length]!.mode)
}

const menuOpen = ref(false)
const toggleRef = ref<HTMLButtonElement | null>(null)
const caretRef = ref<HTMLButtonElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

onMounted(() => { void initBgm() })

function onToggle() {
  void toggle()
}

function pickTrack(id: string) {
  rowMenuId.value = ''
  void selectTrack(id)
  menuOpen.value = false
  toggleRef.value?.focus()
}

function onVolumeInput(e: Event) {
  const target = e.target as HTMLInputElement
  setVolume(Number(target.value))
}

function onSeekInput(e: Event) {
  const target = e.target as HTMLInputElement
  seek(Number(target.value))
}

// m:ss for the progress readout; durations over an hour are unusual for BGM
// but still render sensibly (61:05).
function fmtTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

function chooseLocalFile() {
  fileInputRef.value?.click()
}

function onLocalFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  // Clear so re-picking the same file fires change again.
  input.value = ''
  if (!files.length) return
  void addLocalFiles(files).then(({ unsaved }) => {
    if (unsaved > 0) pushToast(t('chrome.bgm.uploadNotSaved', { count: unsaved }), { tone: 'danger' })
  })
  // Keep the menu open: nothing auto-plays, so the new rows being visible is
  // the feedback — the user picks one to start it.
}

function onRemoveTrack(id: string) {
  if (editingId.value === id) editingId.value = ''
  rowMenuId.value = ''
  void removeLocalTrack(id)
}

// --- per-row "more" (⋮) menu for library uploads ---
const rowMenuId = ref('')

function toggleRowMenu(id: string) {
  rowMenuId.value = rowMenuId.value === id ? '' : id
}

// --- inline rename for library uploads ---
const editingId = ref('')
const editingTitle = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

function startRename(track: { id: string; title: string }) {
  rowMenuId.value = ''
  editingId.value = track.id
  editingTitle.value = track.title
  void nextTick(() => renameInputRef.value?.select())
}

function commitRename() {
  const id = editingId.value
  const title = editingTitle.value.trim()
  editingId.value = ''
  if (!id || !title) return
  void renameLocalTrack(id, title)
}

function cancelRename() {
  editingId.value = ''
}

// Close on pointerdown (not click): a click's target is the common ancestor
// of mousedown and mouseup, so dragging the volume thumb and releasing past
// the menu edge would otherwise dismiss the menu mid-adjustment.
useDocumentEvent('pointerdown', (e) => {
  if (!menuOpen.value || !(e.target instanceof Node)) return
  const wrap = caretRef.value?.closest('.bgm-menu-wrap')
  if (wrap && !wrap.contains(e.target)) {
    menuOpen.value = false
    rowMenuId.value = ''
    return
  }
  // Inside the menu but outside the open ⋮ popover: close just the popover.
  if (rowMenuId.value && e.target instanceof Element && !e.target.closest('.bgm-menu__row-menu, .bgm-menu__more')) {
    rowMenuId.value = ''
  }
})

useDocumentEvent('keydown', (e) => {
  if (e.key !== 'Escape') return
  // Escape peels one layer at a time: row popover, then the whole menu.
  if (rowMenuId.value) {
    rowMenuId.value = ''
    return
  }
  if (menuOpen.value) {
    menuOpen.value = false
    caretRef.value?.focus()
  }
})
</script>

<template>
  <div class="theme-menu-wrap bgm-menu-wrap">
    <button
      ref="toggleRef"
      type="button"
      class="btn btn--icon btn--ghost bgm-toggle"
      :class="{ 'is-playing': playing }"
      :title="playing ? t('chrome.bgm.pause') : t('chrome.bgm.play')"
      :aria-label="playing ? t('chrome.bgm.pause') : t('chrome.bgm.play')"
      :aria-pressed="playing"
      data-testid="bgm-toggle"
      @click="onToggle"
    >
      <Icon :name="playing ? 'pause' : 'music'" :size="16" />
    </button>
    <button
      ref="caretRef"
      type="button"
      class="btn btn--ghost bgm-caret"
      :title="t('chrome.bgm.label')"
      :aria-label="t('chrome.bgm.label')"
      aria-haspopup="menu"
      :aria-expanded="menuOpen"
      data-testid="bgm-menu-trigger"
      @click.stop="menuOpen = !menuOpen"
    >
      <Icon name="chevronDown" :size="12" />
    </button>
    <div v-if="menuOpen" class="theme-menu bgm-menu" role="menu" :aria-label="t('chrome.bgm.label')">
      <button
        v-for="track in tracks"
        :key="track.id"
        type="button"
        class="theme-menu__item"
        role="menuitemradio"
        :aria-checked="currentTrackId === track.id"
        :data-testid="`bgm-track-${track.id}`"
        @click="pickTrack(track.id)"
      >
        <Icon name="music" :size="14" />
        <span class="bgm-menu__title">{{ track.title }}</span>
        <Icon v-if="currentTrackId === track.id" class="theme-menu__check" name="check" :size="14" />
      </button>
      <!-- Uploads persisted in the in-app library (IndexedDB): selectable like
           playlist tracks, each removable without dismissing the menu. -->
      <div
        v-for="track in localTracks"
        :key="track.id"
        class="bgm-menu__local-row"
        role="none"
      >
        <input
          v-if="editingId === track.id"
          ref="renameInputRef"
          v-model="editingTitle"
          type="text"
          class="bgm-menu__rename-input"
          :aria-label="t('chrome.bgm.renameTrack')"
          :data-testid="`bgm-rename-input-${track.id}`"
          @click.stop
          @keydown.enter.prevent="commitRename"
          @keydown.esc.stop="cancelRename"
          @blur="commitRename"
        />
        <button
          v-else
          type="button"
          class="theme-menu__item bgm-menu__local-item"
          role="menuitemradio"
          :aria-checked="currentTrackId === track.id"
          :data-testid="`bgm-track-${track.id}`"
          @click="pickTrack(track.id)"
        >
          <Icon name="music" :size="14" />
          <span class="bgm-menu__title">{{ track.title }}</span>
          <Icon v-if="currentTrackId === track.id" class="theme-menu__check" name="check" :size="14" />
        </button>
        <!-- Row actions live behind a ⋮ popover (like most music players), so
             a stray click near the title cannot rename or delete anything. -->
        <button
          v-if="editingId !== track.id"
          type="button"
          class="btn btn--icon btn--ghost bgm-menu__row-action bgm-menu__more"
          :title="t('chrome.bgm.trackActions')"
          :aria-label="t('chrome.bgm.trackActions')"
          aria-haspopup="menu"
          :aria-expanded="rowMenuId === track.id"
          :data-testid="`bgm-more-${track.id}`"
          @click.stop="toggleRowMenu(track.id)"
        >
          <Icon name="more-vertical" :size="14" />
        </button>
        <div
          v-if="rowMenuId === track.id"
          class="theme-menu bgm-menu__row-menu"
          role="menu"
          :aria-label="t('chrome.bgm.trackActions')"
        >
          <button
            type="button"
            class="theme-menu__item"
            role="menuitem"
            :data-testid="`bgm-rename-${track.id}`"
            @click.stop="startRename(track)"
          >
            <Icon name="pencil" :size="14" />
            <span>{{ t('chrome.bgm.renameTrack') }}</span>
          </button>
          <button
            type="button"
            class="theme-menu__item bgm-menu__remove"
            role="menuitem"
            :data-testid="`bgm-remove-${track.id}`"
            @click.stop="onRemoveTrack(track.id)"
          >
            <Icon name="trash" :size="14" />
            <span>{{ t('chrome.bgm.removeTrack') }}</span>
          </button>
        </div>
      </div>
      <!-- Session-only local pick (IndexedDB unavailable): shown as a
           selectable row once a file has been chosen, so it can be toggled
           back to after a playlist track. -->
      <button
        v-if="localTrackTitle"
        type="button"
        class="theme-menu__item"
        role="menuitemradio"
        :aria-checked="currentTrackId === BGM_LOCAL_TRACK_ID"
        data-testid="bgm-track-local"
        @click="pickTrack(BGM_LOCAL_TRACK_ID)"
      >
        <Icon name="music" :size="14" />
        <span class="bgm-menu__title">{{ localTrackTitle }}</span>
        <Icon v-if="currentTrackId === BGM_LOCAL_TRACK_ID" class="theme-menu__check" name="check" :size="14" />
      </button>
      <div v-if="!tracks.length && !localTracks.length && !localTrackTitle" class="bgm-menu__empty">
        {{ t('chrome.bgm.noTracks') }}
      </div>
      <!-- Progress: appears once the element knows the track length; ad-hoc
           streams without one keep the compact menu. -->
      <div v-if="duration > 0" class="bgm-menu__progress" role="none" @click.stop>
        <input
          type="range"
          min="0"
          :max="duration"
          step="any"
          :value="progress"
          :aria-label="t('chrome.bgm.seek')"
          data-testid="bgm-seek"
          @input="onSeekInput"
        />
        <span class="bgm-menu__time">{{ fmtTime(progress) }} / {{ fmtTime(duration) }}</span>
      </div>
      <!-- Transport: previous / next, and the play-mode cycler (one control,
           each click advances to the next mode, like most music players).
           Keeps the menu open so the switch is visible. -->
      <div class="bgm-menu__transport" role="none" @click.stop>
        <button
          type="button"
          class="btn btn--icon btn--ghost bgm-menu__transport-btn"
          :title="t('chrome.bgm.previous')"
          :aria-label="t('chrome.bgm.previous')"
          data-testid="bgm-previous"
          @click="playPrevious()"
        >
          <Icon name="skip-back" :size="14" />
        </button>
        <button
          type="button"
          class="btn btn--icon btn--ghost bgm-menu__transport-btn"
          :title="t('chrome.bgm.next')"
          :aria-label="t('chrome.bgm.next')"
          data-testid="bgm-next"
          @click="playNext()"
        >
          <Icon name="skip-forward" :size="14" />
        </button>
        <span class="bgm-menu__transport-spacer" />
        <button
          type="button"
          class="btn btn--icon btn--ghost bgm-menu__transport-btn"
          :class="{ 'is-active': playMode !== 'order' }"
          :title="t(currentMode.labelKey)"
          :aria-label="t(currentMode.labelKey)"
          data-testid="bgm-mode-cycle"
          @click="cycleMode"
        >
          <Icon :name="currentMode.icon" :size="14" />
        </button>
      </div>
      <!-- Volume row: adjusting must not dismiss the menu. The icon doubles
           as a mute toggle (element-level mute; the slider keeps its value). -->
      <div class="bgm-menu__volume" role="none" @click.stop>
        <button
          type="button"
          class="btn btn--icon btn--ghost bgm-menu__mute"
          :class="{ 'is-muted': muted }"
          :title="muted ? t('chrome.bgm.unmute') : t('chrome.bgm.mute')"
          :aria-label="muted ? t('chrome.bgm.unmute') : t('chrome.bgm.mute')"
          :aria-pressed="muted"
          data-testid="bgm-mute"
          @click="toggleMute()"
        >
          <Icon :name="muted ? 'volume-x' : 'volume'" :size="14" />
        </button>
        <!-- step="any": a fractional fixed step (0.05) makes `max` itself an
             invalid stepped value in float math, so the thumb could never
             reach the far right. -->
        <input
          type="range"
          min="0"
          max="1"
          step="any"
          :value="volume"
          :aria-label="t('chrome.bgm.volume')"
          data-testid="bgm-volume"
          @input="onVolumeInput"
        />
      </div>
      <button
        type="button"
        class="theme-menu__item theme-menu__item--more"
        role="menuitem"
        data-testid="bgm-choose-local"
        @click="chooseLocalFile"
      >
        <Icon name="paperclip" :size="14" />
        <span>{{ t('chrome.bgm.chooseLocalFile') }}</span>
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept="audio/*"
        multiple
        class="bgm-file-input"
        tabindex="-1"
        aria-hidden="true"
        @change="onLocalFilePicked"
      />
    </div>
    <!-- Screen-reader note of what is currently playing; visual users get the
         accent-lit note button instead. -->
    <span v-if="playing && currentTitle" class="bgm-sr-now-playing">{{ currentTitle }}</span>
  </div>
</template>

<style scoped>
.bgm-toggle {
  color: var(--text-muted);
}

.bgm-toggle.is-playing {
  color: var(--accent);
}

/* Narrow caret hugging the note button so the pair reads as one control. */
.bgm-caret {
  display: inline-flex;
  align-items: center;
  width: auto;
  padding: 0 2px;
  margin-left: -6px;
  color: var(--text-muted);
}

.bgm-caret:hover {
  color: var(--text);
}

.bgm-menu {
  min-width: 200px;
  max-width: 280px;
}

.bgm-menu__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bgm-menu__empty {
  padding: 7px 10px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.bgm-menu__volume {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 7px 10px;
  color: var(--text-muted);
}

/* The global input rule (base.css) dresses every non-radio/checkbox input as
   a text field — padding, border, and background. On a range input that
   insets the native track so the thumb visually stops well short of both
   ends. Opt out and draw the slider explicitly (volume and seek alike). */
.bgm-menu input[type='range'] {
  flex: 1;
  min-width: 0;
  appearance: none;
  -webkit-appearance: none;
  height: 20px;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}

.bgm-menu input[type='range']:focus {
  border: none;
  box-shadow: none;
}

.bgm-menu input[type='range']:focus-visible {
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-md);
}

.bgm-menu input[type='range']::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: var(--radius-xs);
  background: var(--border);
}

.bgm-menu input[type='range']::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  margin-top: -4px; /* center the 12px thumb on the 4px track */
  border: none;
  border-radius: 50%;
  background: var(--accent);
}

.bgm-menu input[type='range']::-moz-range-track {
  height: 4px;
  border-radius: var(--radius-xs);
  background: var(--border);
}

.bgm-menu input[type='range']::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border: none;
  border-radius: 50%;
  background: var(--accent);
}

.bgm-menu__progress {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 2px 10px 0;
}

.bgm-menu__time {
  flex: none;
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.bgm-menu__transport {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 2px 8px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}

.bgm-menu__transport-spacer {
  flex: 1;
}

.bgm-menu__transport-btn {
  width: 24px;
  height: 24px;
  color: var(--text-muted);
}

.bgm-menu__transport-btn:hover {
  color: var(--text);
}

/* The cycler lights up when the mode deviates from the loop-playlist default. */
.bgm-menu__transport-btn.is-active {
  color: var(--accent);
}

.bgm-menu__mute {
  flex: none;
  width: 24px;
  height: 24px;
  color: var(--text-muted);
}

.bgm-menu__mute.is-muted {
  color: var(--accent);
}

.bgm-menu__rename-input {
  flex: 1;
  min-width: 0;
  margin: 2px 4px 2px 6px;
  padding: 3px 6px;
  font-size: var(--fs-sm);
}

/* Upload row: the radio item flexes, the ⋮ button hugs the right edge; its
   popover anchors to the row. */
.bgm-menu__local-row {
  position: relative;
  display: flex;
  align-items: center;
}

.bgm-menu__row-menu {
  /* Overrides the shared .theme-menu top-right anchor to sit by the ⋮. */
  top: calc(100% - 4px);
  right: 6px;
  min-width: 120px;
  z-index: 61;
}

.bgm-menu__remove:hover {
  color: var(--danger, var(--text));
}

.bgm-menu__local-item {
  flex: 1;
  min-width: 0;
}

.bgm-menu__row-action {
  flex: none;
  width: 22px;
  height: 22px;
  color: var(--text-muted);
}

.bgm-menu__row-action:last-child {
  margin-right: 6px;
}

.bgm-menu__row-action:hover {
  color: var(--text);
}

.bgm-file-input {
  display: none;
}

/* Off-screen but screen-reader-reachable "now playing" note. */
.bgm-sr-now-playing {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
