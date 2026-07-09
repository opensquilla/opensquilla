import { computed, ref } from 'vue'

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
 * Synthetic id for an ad-hoc "Choose local file…" pick. Session-only: the
 * object URL cannot be restored after a reload, so on init this id falls back
 * to the playlist default with playback off.
 */
export const BGM_LOCAL_TRACK_ID = '__local__'

const STORAGE_KEY = 'opensquilla-bgm'
const DEFAULT_VOLUME = 0.6
const ABSOLUTE_URL_SCHEME = /^[a-z][a-z\d+.-]*:/i
const HTTPS_STREAM = /^https:\/\//i

// Module-level singleton state (mirrors useAgentOptions/useConfirm): one
// <audio> element and one state tree app-wide, however many components mount.
const tracks = ref<BgmTrack[]>([])
const playing = ref(false)
const currentTrackId = ref('')
const volume = ref(DEFAULT_VOLUME)
const playlistError = ref(false)
// Display name of the session-only local file; '' until one has been picked.
const localTrackTitle = ref('')

let audio: HTMLAudioElement | null = null
let localObjectUrl = ''
// Dedupes concurrent initBgm() calls onto a single load, like useAgentOptions.
let initPromise: Promise<void> | null = null

interface PersistedBgm {
  enabled?: boolean
  playing?: boolean
  trackId?: string
  volume?: number
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
      }),
    )
  } catch {}
}

/**
 * Resolve a playlist `src` to a fetchable URL. Absolute HTTPS URLs pass
 * through; bundled filenames mirror App.vue's brandMarkUrl: Vite serves
 * `public/` at the root in dev, while the packaged UI serves those assets from
 * `${base}/static/dist/` under the gateway's base path.
 */
function musicAssetUrl(file: string): string {
  if (HTTPS_STREAM.test(file)) return file
  if (ABSOLUTE_URL_SCHEME.test(file) || file.startsWith('//')) return ''
  if (import.meta.env.DEV) return `/music/${file}`
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base.replace(/\/$/, '')}/static/dist/music/${file}`
}

function getAudio(): HTMLAudioElement {
  if (!audio) {
    audio = new Audio()
    audio.loop = true
    audio.preload = 'none'
    audio.volume = volume.value
    // Belt-and-braces state sync: toggle()/playTrack() set `playing` directly
    // (test DOMs don't fire media events), while these listeners keep the ref
    // honest when playback changes outside our calls — OS media keys, a
    // mid-stream network failure, or the element pausing itself on error.
    audio.addEventListener('play', () => { playing.value = true })
    audio.addEventListener('pause', () => { playing.value = false })
    audio.addEventListener('error', () => { playing.value = false })
  }
  return audio
}

function trackById(id: string): BgmTrack | undefined {
  return tracks.value.find(t => t.id === id)
}

function sourceForId(id: string): string {
  if (id === BGM_LOCAL_TRACK_ID) return localObjectUrl
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
      && (HTTPS_STREAM.test(t.src) || (!ABSOLUTE_URL_SCHEME.test(t.src) && !t.src.startsWith('//')))
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

async function playTrack(id: string): Promise<void> {
  const src = sourceForId(id)
  if (!src) return
  const el = getAudio()
  // Only swap the source on a genuine track change so re-playing the current
  // track resumes from where it paused instead of restarting.
  if (currentTrackId.value !== id || !el.src) {
    el.src = src
    currentTrackId.value = id
  }
  try {
    await el.play()
    playing.value = true
  } catch (err: unknown) {
    // Autoplay policy or a missing/broken file: reflect reality as paused
    // rather than a stuck "playing" button.
    console.warn('[useBgm] play blocked/failed:', err instanceof Error ? err.message : err)
    playing.value = false
  }
  persist()
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
      if (typeof saved.volume === 'number' && Number.isFinite(saved.volume)) {
        volume.value = Math.min(1, Math.max(0, saved.volume))
      }
      await loadPlaylist()
      // Restore the selection: a persisted playlist id wins; the session-only
      // local slot (or an id gone from the manifest) falls back to the first
      // manifest entry — the designated default track — unplayed.
      const savedId = String(saved.trackId || '')
      const restorable = savedId !== BGM_LOCAL_TRACK_ID && !!trackById(savedId)
      currentTrackId.value = restorable ? savedId : tracks.value[0]?.id || ''
      // Resume only while the feature gate is on: a disable while a session
      // was left playing must never come back as sound on the next launch.
      if (enabled.value && saved.playing === true && currentTrackId.value) {
        await playTrack(currentTrackId.value)
      }
    })()
    return initPromise
  }

  function setEnabled(on: boolean) {
    if (!on && playing.value) {
      // Disabling silences immediately; the paused state is what persists.
      audio?.pause()
      playing.value = false
    }
    enabled.value = on
    persist()
  }

  async function toggle(): Promise<void> {
    if (playing.value) {
      getAudio().pause()
      playing.value = false
      persist()
      return
    }
    // Nothing selected yet (fresh profile): start the default first track.
    const id = currentTrackId.value && sourceForId(currentTrackId.value)
      ? currentTrackId.value
      : tracks.value[0]?.id || ''
    if (!id) return
    await playTrack(id)
  }

  async function selectTrack(id: string): Promise<void> {
    if (id === currentTrackId.value && playing.value) return
    await playTrack(id)
  }

  function setVolume(v: number) {
    const clamped = Math.min(1, Math.max(0, v))
    volume.value = clamped
    if (audio) audio.volume = clamped
    persist()
  }

  async function playLocalFile(file: File): Promise<void> {
    if (localObjectUrl) URL.revokeObjectURL(localObjectUrl)
    localObjectUrl = URL.createObjectURL(file)
    localTrackTitle.value = file.name
    // Set the source directly: playTrack's same-id guard would skip the swap
    // when a *different* file is picked into the same local slot.
    const el = getAudio()
    el.src = localObjectUrl
    currentTrackId.value = BGM_LOCAL_TRACK_ID
    try {
      await el.play()
      playing.value = true
    } catch (err: unknown) {
      console.warn('[useBgm] local file play failed:', err instanceof Error ? err.message : err)
      playing.value = false
    }
    persist()
  }

  const currentTitle = computed(() => {
    if (currentTrackId.value === BGM_LOCAL_TRACK_ID) return localTrackTitle.value
    return trackById(currentTrackId.value)?.title || ''
  })

  return {
    enabled,
    tracks,
    playing,
    currentTrackId,
    currentTitle,
    volume,
    playlistError,
    localTrackTitle,
    initBgm,
    setEnabled,
    toggle,
    selectTrack,
    setVolume,
    playLocalFile,
  }
}
