import { computed, ref } from 'vue'
import {
  deleteLocalTrack,
  listLocalTracks,
  renameLocalTrack as renameStoredTrack,
  saveLocalTrack,
} from './bgmLibrary'

/**
 * One entry from `public/music/playlist.json`. `src` is either a filename
 * relative to the music directory (bundled into the build) or an absolute
 * HTTPS URL streamed at runtime.
 */
export interface BgmTrack {
  id: string
  title: string
  src: string
}

/**
 * Synthetic id for an ad-hoc "Add local music…" pick that could NOT be
 * persisted (IndexedDB unavailable). Session-only: the object URL cannot be
 * restored after a reload, so on init this id falls back to the playlist
 * default with playback off. Persisted uploads use `local:<uuid>` ids instead.
 */
export const BGM_LOCAL_TRACK_ID = '__local__'

/** How playback continues when a track ends (multi-track lists only). */
export type BgmPlayMode = 'order' | 'shuffle' | 'one'

const LOCAL_ID_PREFIX = 'local:'
const STORAGE_KEY = 'opensquilla-bgm'
const DEFAULT_VOLUME = 0.6
const ABSOLUTE_URL_SCHEME = /^[a-z][a-z\d+.-]*:/i
const HTTPS_STREAM = /^https:\/\//i
const URL_ESCAPE = /%[0-9a-f]{2}/i

// Module-level singleton state (mirrors useAgentOptions/useConfirm): one
// <audio> element and one state tree app-wide, however many components mount.
const tracks = ref<BgmTrack[]>([])
// Uploads restored from IndexedDB, listed after the manifest tracks. `src`
// here is a display placeholder; playback resolves through `localUrls`.
const localTracks = ref<BgmTrack[]>([])
const playMode = ref<BgmPlayMode>('order')
const playing = ref(false)
const currentTrackId = ref('')
const volume = ref(DEFAULT_VOLUME)
const muted = ref(false)
// Playback position of the current track, in seconds. duration is 0 until
// the element has metadata (streams without a length stay at 0 — no seek UI).
const progress = ref(0)
const duration = ref(0)
const playlistError = ref(false)
// Display name of the session-only local file; '' until one has been picked.
const localTrackTitle = ref('')

let audio: HTMLAudioElement | null = null
let localObjectUrl = ''
// Object URLs for persisted uploads, id → URL, created once per session.
const localUrls = new Map<string, string>()
let localSeqCounter = 0
// Dedupes concurrent initBgm() calls onto a single load, like useAgentOptions.
let initPromise: Promise<void> | null = null
// Async play() settlements may arrive after a disable, pause, or newer play
// request. Only the latest generation may publish state; the intent tells a
// stale successful request whether it must re-pause the shared element.
let playbackGeneration = 0
let playbackIntent = false

interface PersistedBgm {
  enabled?: boolean
  playing?: boolean
  trackId?: string
  volume?: number
  muted?: boolean
  mode?: string
}

function readPersisted(): PersistedBgm {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as PersistedBgm) : {}
  } catch {
    return {}
  }
}

// Opt-in feature gate: the topbar control only renders when this is on
// (Settings → Appearance, or the command palette). Read synchronously at
// module init — App.vue's v-if needs the answer before any component mounts
// or initBgm() runs.
const enabled = ref(readPersisted().enabled === true)

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        enabled: enabled.value,
        playing: playing.value,
        trackId: currentTrackId.value,
        volume: volume.value,
        muted: muted.value,
        mode: playMode.value,
      }),
    )
  } catch {}
}

function isPlayMode(value: unknown): value is BgmPlayMode {
  return value === 'order' || value === 'shuffle' || value === 'one'
}

function isSafeRelativeMusicSource(file: string): boolean {
  if (!file || ABSOLUTE_URL_SCHEME.test(file) || file.startsWith('//')) return false

  // Check the path independently from its query/fragment. Repeated decoding
  // catches both ordinary and nested percent-encoded traversal; every
  // successful pass shortens the string, so the loop is naturally bounded.
  let decodedPath = file.split(/[?#]/, 1)[0]
  try {
    while (URL_ESCAPE.test(decodedPath)) {
      const next = decodeURIComponent(decodedPath)
      if (next === decodedPath) break
      decodedPath = next
    }
  } catch {
    return false
  }

  const slashPath = decodedPath.replace(/\\/g, '/')
  if (!slashPath || slashPath.startsWith('/')) return false
  return slashPath.split('/').every(segment => segment !== '.' && segment !== '..')
}

/**
 * Resolve a playlist `src` to a fetchable URL. Absolute HTTPS URLs pass
 * through; bundled filenames mirror App.vue's brandMarkUrl: Vite serves
 * `public/` at the root in dev, while the packaged UI serves those assets from
 * `${base}/static/dist/` under the gateway's base path.
 */
function musicAssetUrl(file: string): string {
  if (HTTPS_STREAM.test(file)) return file
  if (!isSafeRelativeMusicSource(file)) return ''
  if (import.meta.env.DEV) return `/music/${file}`
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base.replace(/\/$/, '')}/static/dist/music/${file}`
}

/** Manifest tracks first, then persisted uploads — the picker's visual order. */
function combinedTracks(): BgmTrack[] {
  return [...tracks.value, ...localTracks.value]
}

// --- fades -------------------------------------------------------------
// Short volume ramps on play/pause so background music never pops in or cuts
// off abruptly. Only the element volume is ramped; `volume` (the user's
// setting) is untouched, and any direct volume/mute change cancels the ramp.
const FADE_MS = 250
const FADE_STEPS = 10
let fadeTimer: ReturnType<typeof setInterval> | null = null

function cancelFade() {
  if (fadeTimer) {
    clearInterval(fadeTimer)
    fadeTimer = null
  }
}

function fadeElementVolume(el: HTMLAudioElement, from: number, to: number, done?: () => void) {
  cancelFade()
  el.volume = Math.min(1, Math.max(0, from))
  if (from === to) {
    done?.()
    return
  }
  let step = 0
  fadeTimer = setInterval(() => {
    step += 1
    el.volume = Math.min(1, Math.max(0, from + (to - from) * (step / FADE_STEPS)))
    if (step >= FADE_STEPS) {
      cancelFade()
      done?.()
    }
  }, FADE_MS / FADE_STEPS)
}

// --- OS media integration ----------------------------------------------
// Publish the current track to the platform (macOS Now Playing / control
// center, hardware media keys, headset controls). Everything is
// feature-detected: test DOMs and older embedders simply skip it.
function mediaSessionApi(): MediaSession | null {
  try {
    return 'mediaSession' in navigator ? navigator.mediaSession : null
  } catch {
    return null
  }
}

function updateMediaMetadata() {
  const session = mediaSessionApi()
  if (!session) return
  try {
    const title = currentTrackId.value === BGM_LOCAL_TRACK_ID
      ? localTrackTitle.value
      : trackById(currentTrackId.value)?.title || ''
    session.metadata = typeof MediaMetadata !== 'undefined' && title
      ? new MediaMetadata({ title })
      : null
  } catch {}
}

function syncMediaPlaybackState() {
  const session = mediaSessionApi()
  if (!session) return
  try {
    session.playbackState = playing.value ? 'playing' : 'paused'
  } catch {}
}

let mediaHandlersInstalled = false
function installMediaHandlers() {
  if (mediaHandlersInstalled) return
  const session = mediaSessionApi()
  if (!session) return
  mediaHandlersInstalled = true
  try {
    session.setActionHandler('play', () => {
      if (enabled.value && currentTrackId.value) void playTrack(currentTrackId.value)
    })
    session.setActionHandler('pause', () => pausePlayback())
    session.setActionHandler('nexttrack', () => void playAdjacent(1))
    session.setActionHandler('previoustrack', () => void playAdjacent(-1))
  } catch {}
}

/**
 * Single-track semantics stay "loop forever". With more than one track the
 * element must actually end so the `ended` listener can advance — unless the
 * user chose single-track repeat. The session-only local slot is not part of
 * the list, so it always loops.
 */
function applyLoopMode() {
  if (!audio) return
  const inList = combinedTracks().some(t => t.id === currentTrackId.value)
  audio.loop = playMode.value === 'one' || !inList || combinedTracks().length <= 1
}

/**
 * Pick the track `direction` away from the current one. Forward respects
 * shuffle; backward is always sequential (matching common player behavior,
 * where "previous" retraces the list even while shuffling).
 */
function adjacentTrackId(direction: 1 | -1): string {
  const list = combinedTracks()
  if (!list.length) return ''
  const idx = list.findIndex(t => t.id === currentTrackId.value)
  if (direction === 1 && playMode.value === 'shuffle' && list.length > 1) {
    const others = list.filter(t => t.id !== currentTrackId.value)
    return others[Math.floor(Math.random() * others.length)]!.id
  }
  return list[(idx + direction + list.length) % list.length]!.id
}

/** User- or OS-initiated skip. Plays even from a paused state. */
async function playAdjacent(direction: 1 | -1): Promise<void> {
  if (!enabled.value) return
  const id = adjacentTrackId(direction)
  if (!id) return
  // Same-id (single-track list): restart from the top instead of a no-op.
  if (id === currentTrackId.value && audio) audio.currentTime = 0
  await playTrack(id)
}

/** Hard state flip shared by toggle(), media-key pause, and the fade-out. */
function pausePlayback() {
  if (!playing.value) return
  playbackGeneration += 1
  playbackIntent = false
  playing.value = false
  const el = audio
  if (el) {
    // Fade the element down, then actually pause and restore its volume for
    // the next play. State above is already flipped — the UI never waits.
    // (Mute is the orthogonal `el.muted` property; fades never touch it.)
    fadeElementVolume(el, el.volume, 0, () => {
      el.pause()
      el.volume = volume.value
    })
  }
  syncMediaPlaybackState()
  persist()
}

function getAudio(): HTMLAudioElement {
  if (!audio) {
    audio = new Audio()
    audio.loop = true
    audio.preload = 'none'
    audio.volume = volume.value
    audio.muted = muted.value
    installMediaHandlers()
    // Auto-advance: continuing on the same element after `ended` keeps the
    // original user-gesture activation, so play() is not autoplay-blocked.
    audio.addEventListener('ended', () => {
      if (!enabled.value) return
      const next = adjacentTrackId(1)
      if (next) void playTrack(next)
    })
    audio.addEventListener('timeupdate', () => {
      progress.value = audio?.currentTime || 0
    })
    // durationchange covers both initial metadata and source swaps.
    audio.addEventListener('durationchange', () => {
      const d = audio?.duration
      duration.value = typeof d === 'number' && Number.isFinite(d) ? d : 0
    })
    // Belt-and-braces state sync: toggle()/playTrack() set `playing` directly
    // (test DOMs don't fire media events), while these listeners keep the ref
    // honest when playback changes outside our calls — OS media keys, a
    // mid-stream network failure, or the element pausing itself on error.
    audio.addEventListener('play', () => {
      playbackGeneration += 1
      if (!enabled.value) {
        playbackIntent = false
        audio?.pause()
        playing.value = false
      } else {
        playbackIntent = true
        playing.value = true
      }
      syncMediaPlaybackState()
      persist()
    })
    audio.addEventListener('pause', () => {
      playbackGeneration += 1
      playbackIntent = false
      playing.value = false
      syncMediaPlaybackState()
      persist()
    })
    audio.addEventListener('error', () => {
      playbackGeneration += 1
      playbackIntent = false
      playing.value = false
      syncMediaPlaybackState()
      persist()
    })
  }
  return audio
}

function trackById(id: string): BgmTrack | undefined {
  return combinedTracks().find(t => t.id === id)
}

function sourceForId(id: string): string {
  if (id === BGM_LOCAL_TRACK_ID) return localObjectUrl
  if (id.startsWith(LOCAL_ID_PREFIX)) return localUrls.get(id) || ''
  const track = trackById(id)
  return track ? musicAssetUrl(track.src) : ''
}

async function fetchManifest(name: string): Promise<BgmTrack[] | null> {
  const res = await fetch(musicAssetUrl(name), { cache: 'no-cache' })
  if (!res.ok) return null
  const data = (await res.json()) as { tracks?: Array<Partial<BgmTrack>> }
  if (!Array.isArray(data.tracks)) return null
  return data.tracks
    .map(t => ({
      id: String(t.id || '').trim(),
      title: String(t.title || '').trim(),
      src: String(t.src || '').trim(),
    }))
    .filter(t => (
      !!t.id
      && !!t.src
      && (HTTPS_STREAM.test(t.src) || isSafeRelativeMusicSource(t.src))
    ))
    .map(t => ({ ...t, title: t.title || t.src }))
}

async function loadPlaylist(): Promise<void> {
  playlistError.value = false
  try {
    // `playlist.local.json` is the user's gitignored personal manifest (it
    // rides along with the gitignored audio files); when present it replaces
    // the tracked, deliberately-empty `playlist.json` entirely. Its absence is
    // the normal case, not an error.
    const local = await fetchManifest('playlist.local.json').catch(() => null)
    if (local) {
      tracks.value = local
      return
    }
    const base = await fetchManifest('playlist.json')
    if (base === null) throw new Error('playlist.json missing or malformed')
    tracks.value = base
  } catch (err: unknown) {
    // Missing manifests are a supported setup (no bundled music): the control
    // degrades to "Choose local file…" only.
    console.warn('[useBgm] playlist load failed:', err instanceof Error ? err.message : err)
    playlistError.value = true
    tracks.value = []
  }
}

async function playAudio(el: HTMLAudioElement, failureLabel: string): Promise<void> {
  if (!enabled.value) return
  // A still-running fade-out would pause the element from under this play().
  cancelFade()
  const generation = ++playbackGeneration
  playbackIntent = true
  try {
    await el.play()
    if (generation !== playbackGeneration || !enabled.value) {
      if (!enabled.value || !playbackIntent) el.pause()
      return
    }
    playing.value = true
    // Fade in from silence to the user's volume.
    fadeElementVolume(el, 0, volume.value)
  } catch (err: unknown) {
    if (generation !== playbackGeneration) return
    // Autoplay policy or a missing/broken file: reflect reality as paused
    // rather than a stuck "playing" button.
    playbackIntent = false
    console.warn(`[useBgm] ${failureLabel}:`, err instanceof Error ? err.message : err)
    playing.value = false
    el.volume = volume.value
  }
  syncMediaPlaybackState()
  persist()
}

async function playTrack(id: string): Promise<void> {
  if (!enabled.value) return
  const src = sourceForId(id)
  if (!src) return
  const el = getAudio()
  // Only swap the source on a genuine track change so re-playing the current
  // track resumes from where it paused instead of restarting. The session
  // slot compares URLs too: a new pick replaces the slot's object URL in
  // place, and playing the stale (revoked) one would error.
  if (
    currentTrackId.value !== id
    || !el.src
    || (id === BGM_LOCAL_TRACK_ID && el.src !== src)
  ) {
    el.src = src
    currentTrackId.value = id
    progress.value = 0
    duration.value = 0
  }
  applyLoopMode()
  updateMediaMetadata()
  await playAudio(el, 'play blocked/failed')
}

/** Restore persisted uploads from IndexedDB into the picker (once per boot). */
async function loadLocalLibrary(): Promise<void> {
  const stored = await listLocalTracks()
  const restored: BgmTrack[] = []
  for (const row of stored) {
    if (!localUrls.has(row.id)) {
      try {
        localUrls.set(row.id, URL.createObjectURL(row.blob))
      } catch {
        continue
      }
    }
    localSeqCounter = Math.max(localSeqCounter, (row.seq || 0) + 1)
    restored.push({ id: row.id, title: row.title || 'audio', src: row.id })
  }
  localTracks.value = restored
}

function newLocalTrackId(): string {
  try {
    return `${LOCAL_ID_PREFIX}${crypto.randomUUID()}`
  } catch {
    return `${LOCAL_ID_PREFIX}${localSeqCounter}-${Math.random().toString(36).slice(2, 10)}`
  }
}

/**
 * Background-music state + controls, backed by a single shared `Audio`
 * element. Persisted (localStorage `opensquilla-bgm`): the opt-in feature
 * gate, the selected playlist track, volume, and whether playback was left
 * on — `initBgm()` restores them, degrading to paused when the browser
 * rejects the resume without a user gesture.
 */
export function useBgm() {
  function initBgm(): Promise<void> {
    if (initPromise) return initPromise
    initPromise = (async () => {
      const saved = readPersisted()
      const restoreGeneration = playbackGeneration
      if (typeof saved.volume === 'number' && Number.isFinite(saved.volume)) {
        volume.value = Math.min(1, Math.max(0, saved.volume))
      }
      muted.value = saved.muted === true
      if (isPlayMode(saved.mode)) playMode.value = saved.mode
      await Promise.all([loadPlaylist(), loadLocalLibrary()])
      // Loading manifests yields to user interaction. Never apply the stale
      // startup snapshot over a local-file selection or an intervening
      // disable/re-enable cycle. Keep a real selection, otherwise choose the
      // new default, and persist the current (necessarily non-stale) state.
      if (restoreGeneration !== playbackGeneration) {
        if (!currentTrackId.value) currentTrackId.value = combinedTracks()[0]?.id || ''
        persist()
        return
      }
      // Restore the selection: a persisted playlist or upload id wins; the
      // session-only local slot (or an id gone from the manifest/library)
      // falls back to a selection made while loading (an upload picked
      // mid-boot) and then to the first entry — the designated default —
      // unplayed.
      const savedId = String(saved.trackId || '')
      const restorable = savedId !== BGM_LOCAL_TRACK_ID && !!trackById(savedId)
      currentTrackId.value = restorable
        ? savedId
        : currentTrackId.value || combinedTracks()[0]?.id || ''
      // Object URLs and removed playlist entries cannot survive a reload.
      // Normalize that stale persisted state now so the fallback selection is
      // visibly paused and a later reload cannot reinterpret it as playable.
      if (!restorable && (savedId !== '' || saved.playing === true)) persist()
      // Resume only while the feature gate is on: a disable while a session
      // was left playing must never come back as sound on the next launch. A
      // stale/local selection also falls back paused instead of silently
      // switching to and starting the playlist default.
      if (enabled.value && saved.playing === true && restorable) {
        await playTrack(currentTrackId.value)
      }
    })()
    return initPromise
  }

  function setEnabled(on: boolean) {
    enabled.value = on
    if (!on) {
      // Invalidate even a play() that has not yet set `playing`; its eventual
      // settlement cannot restore sound or persisted playback state. Hard
      // cut, no fade: disabling must be silent immediately.
      playbackGeneration += 1
      playbackIntent = false
      cancelFade()
      audio?.pause()
      if (audio) audio.volume = volume.value
      playing.value = false
      syncMediaPlaybackState()
    }
    persist()
  }

  async function toggle(): Promise<void> {
    if (!enabled.value) return
    if (playing.value) {
      pausePlayback()
      return
    }
    // Nothing selected yet (fresh profile): start the default first track.
    const id = currentTrackId.value && sourceForId(currentTrackId.value)
      ? currentTrackId.value
      : combinedTracks()[0]?.id || ''
    if (!id) return
    await playTrack(id)
  }

  async function selectTrack(id: string): Promise<void> {
    if (!enabled.value) return
    if (id === currentTrackId.value && playing.value) return
    await playTrack(id)
  }

  function setVolume(v: number) {
    // Round to two decimals: the slider is step="any", and persisting raw
    // drag positions would store noise like 0.6300000000000001.
    const clamped = Math.round(Math.min(1, Math.max(0, v)) * 100) / 100
    volume.value = clamped
    cancelFade()
    if (audio) audio.volume = clamped
    persist()
  }

  function toggleMute() {
    muted.value = !muted.value
    if (audio) audio.muted = muted.value
    persist()
  }

  /** Jump to `seconds` in the current track (clamped to the known duration). */
  function seek(seconds: number) {
    if (!audio || !duration.value) return
    const clamped = Math.min(duration.value, Math.max(0, seconds))
    audio.currentTime = clamped
    progress.value = clamped
  }

  function setPlayMode(mode: BgmPlayMode) {
    playMode.value = mode
    applyLoopMode()
    persist()
  }

  /**
   * Add picked files to the library. Nothing starts playing — the user picks
   * a track themselves (playback stays whatever it was). Returns how many
   * files could not be persisted (IndexedDB unavailable/full) so the UI can
   * warn that those will not survive a restart.
   */
  async function addLocalFiles(files: File[]): Promise<{ unsaved: number }> {
    if (!enabled.value || !files.length) return { unsaved: 0 }
    let saved = 0
    let sessionFallback: File | null = null
    for (const file of files) {
      const id = newLocalTrackId()
      const stored = await saveLocalTrack({ id, title: file.name, blob: file, seq: localSeqCounter })
      if (stored) {
        localSeqCounter += 1
        localUrls.set(id, URL.createObjectURL(file))
        localTracks.value = [...localTracks.value, { id, title: file.name, src: id }]
        saved += 1
      } else if (!sessionFallback) {
        // Degraded mode keeps the single pre-library session slot for the
        // first unsaved file; the rest are lost (and counted).
        sessionFallback = file
      }
    }
    if (sessionFallback) {
      if (localObjectUrl) URL.revokeObjectURL(localObjectUrl)
      localObjectUrl = URL.createObjectURL(sessionFallback)
      localTrackTitle.value = sessionFallback.name
    }
    // A fresh profile with no selection yet: point at the first new track so
    // the topbar play button has something to start — still paused.
    if (!currentTrackId.value) {
      currentTrackId.value = combinedTracks()[0]?.id
        || (sessionFallback ? BGM_LOCAL_TRACK_ID : '')
    }
    applyLoopMode()
    persist()
    return { unsaved: files.length - saved }
  }

  async function playLocalFile(file: File): Promise<void> {
    await addLocalFiles([file])
  }

  async function renameLocalTrack(id: string, title: string): Promise<boolean> {
    const trimmed = title.trim()
    if (!id.startsWith(LOCAL_ID_PREFIX) || !trimmed) return false
    const ok = await renameStoredTrack(id, trimmed)
    if (!ok) return false
    localTracks.value = localTracks.value.map(t => (t.id === id ? { ...t, title: trimmed } : t))
    if (currentTrackId.value === id) updateMediaMetadata()
    return true
  }

  async function removeLocalTrack(id: string): Promise<void> {
    if (!id.startsWith(LOCAL_ID_PREFIX)) return
    await deleteLocalTrack(id)
    const url = localUrls.get(id)
    if (url) URL.revokeObjectURL(url)
    localUrls.delete(id)
    localTracks.value = localTracks.value.filter(t => t.id !== id)
    if (currentTrackId.value === id) {
      // The removed track may be mid-playback on the shared element.
      playbackGeneration += 1
      playbackIntent = false
      cancelFade()
      audio?.pause()
      if (audio) {
        audio.removeAttribute('src')
        audio.volume = volume.value
      }
      playing.value = false
      progress.value = 0
      duration.value = 0
      currentTrackId.value = combinedTracks()[0]?.id || ''
      updateMediaMetadata()
      syncMediaPlaybackState()
    }
    applyLoopMode()
    persist()
  }

  const currentTitle = computed(() => {
    if (currentTrackId.value === BGM_LOCAL_TRACK_ID) return localTrackTitle.value
    return trackById(currentTrackId.value)?.title || ''
  })

  return {
    enabled,
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
    playlistError,
    localTrackTitle,
    initBgm,
    setEnabled,
    toggle,
    playNext: () => playAdjacent(1),
    playPrevious: () => playAdjacent(-1),
    selectTrack,
    setVolume,
    toggleMute,
    seek,
    setPlayMode,
    playLocalFile,
    addLocalFiles,
    renameLocalTrack,
    removeLocalTrack,
  }
}
