// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi } from 'vitest'

// useBgm keeps module-level singleton state (one Audio element app-wide), so
// each test re-imports a fresh module via vi.resetModules().

// In-memory stand-in for the IndexedDB library. Hoisted so it survives
// vi.resetModules() — like real IndexedDB survives a reload — which lets
// tests restart the module and assert uploads are restored.
const bgmLibrary = vi.hoisted(() => ({
  rows: new Map<string, { id: string; title: string; blob: Blob; seq: number }>(),
  available: true,
}))

vi.mock('./bgmLibrary', () => ({
  listLocalTracks: async () =>
    bgmLibrary.available
      ? [...bgmLibrary.rows.values()].sort((a, b) => a.seq - b.seq)
      : [],
  saveLocalTrack: async (track: { id: string; title: string; blob: Blob; seq: number }) => {
    if (!bgmLibrary.available) return false
    bgmLibrary.rows.set(track.id, track)
    return true
  },
  renameLocalTrack: async (id: string, title: string) => {
    const row = bgmLibrary.available ? bgmLibrary.rows.get(id) : undefined
    if (!row) return false
    bgmLibrary.rows.set(id, { ...row, title })
    return true
  },
  deleteLocalTrack: async (id: string) => {
    bgmLibrary.rows.delete(id)
  },
}))

class FakeAudio {
  loop = false
  preload = ''
  volume = 1
  muted = false
  currentTime = 0
  duration = 0
  src = ''
  paused = true
  static instances: FakeAudio[] = []
  static playError: Error | null = null
  static playDeferred: Promise<void> | null = null
  private listeners: Record<string, Array<() => void>> = {}
  constructor() {
    FakeAudio.instances.push(this)
  }
  addEventListener(type: string, fn: () => void) {
    ;(this.listeners[type] ||= []).push(fn)
  }
  emit(type: string) {
    for (const fn of this.listeners[type] || []) fn()
  }
  play = vi.fn(async () => {
    if (FakeAudio.playError) throw FakeAudio.playError
    if (FakeAudio.playDeferred) await FakeAudio.playDeferred
    this.paused = false
  })
  pause = vi.fn(() => {
    this.paused = true
  })
  removeAttribute(name: string) {
    if (name === 'src') this.src = ''
  }
}

const PLAYLIST = {
  tracks: [
    { id: 'sun-yanzi-yujian', title: '孙燕姿 - 遇见', src: 'yu-jian.mp3' },
    { id: 'stream', title: 'Stream', src: 'https://example.com/track.mp3' },
  ],
}

// URL-aware stub: `playlist.local.json` (the gitignored personal manifest) is
// probed before the tracked `playlist.json`; localPayload=null → local 404s.
function stubFetch(payload: unknown = PLAYLIST, ok = true, localPayload: unknown = null) {
  const fetchMock = vi.fn(async (url: unknown) => {
    if (String(url).includes('playlist.local.json')) {
      const localOk = localPayload !== null
      return { ok: localOk, status: localOk ? 200 : 404, json: async () => localPayload }
    }
    return { ok, status: ok ? 200 : 404, json: async () => payload }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function stubDeferredBaseManifest(payload: unknown = PLAYLIST) {
  let resolveBase!: (response: unknown) => void
  const baseResponse = new Promise<unknown>((resolve) => { resolveBase = resolve })
  const fetchMock = vi.fn(async (url: unknown) => {
    if (String(url).includes('playlist.local.json')) {
      return { ok: false, status: 404, json: async () => ({}) }
    }
    return baseResponse
  })
  vi.stubGlobal('fetch', fetchMock)
  return {
    fetchMock,
    resolve: () => resolveBase({ ok: true, status: 200, json: async () => payload }),
  }
}

async function freshBgm() {
  vi.resetModules()
  return import('./useBgm')
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  bgmLibrary.rows.clear()
  bgmLibrary.available = true
  FakeAudio.instances = []
  FakeAudio.playError = null
  FakeAudio.playDeferred = null
  vi.stubGlobal('Audio', FakeAudio)
})

describe('useBgm — init', () => {
  it('loads the playlist and defaults to the first track, paused', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.tracks.value.map(t => t.id)).toEqual(['sun-yanzi-yujian', 'stream'])
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances.every(a => !a.play.mock.calls.length)).toBe(true)
  })

  it('keeps relative and HTTPS sources while rejecting other absolute sources', async () => {
    stubFetch({
      tracks: [
        { id: 'relative', title: 'Relative', src: 'relative.mp3' },
        { id: 'nested', title: 'Nested', src: 'album/track.mp3' },
        { id: 'https', title: 'HTTPS', src: 'https://example.com/track.mp3' },
        { id: 'http', title: 'HTTP', src: 'http://example.com/track.mp3' },
        { id: 'scheme-relative', title: 'Scheme relative', src: '//example.com/track.mp3' },
        { id: 'data', title: 'Data', src: 'data:audio/mpeg;base64,AA==' },
        { id: 'root-relative', title: 'Root relative', src: '/outside.mp3' },
        { id: 'parent', title: 'Parent traversal', src: '../outside.mp3' },
        { id: 'nested-parent', title: 'Nested traversal', src: 'album/../outside.mp3' },
        { id: 'encoded-parent', title: 'Encoded traversal', src: '%2e%2e/outside.mp3' },
        { id: 'double-encoded-parent', title: 'Double encoded traversal', src: '%252e%252e%252foutside.mp3' },
        { id: 'backslash-parent', title: 'Backslash traversal', src: '..\\outside.mp3' },
      ],
    })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    expect(bgm.tracks.value.map(t => t.id)).toEqual(['relative', 'nested', 'https'])
  })

  it('restores the persisted track and volume', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ playing: false, trackId: 'stream', volume: 0.25 }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.currentTrackId.value).toBe('stream')
    expect(bgm.volume.value).toBe(0.25)
    expect(bgm.playing.value).toBe(false)
  })

  it('resumes playback when the last session was left playing', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ enabled: true, playing: true, trackId: 'sun-yanzi-yujian', volume: 0.5 }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.playing.value).toBe(true)
    expect(FakeAudio.instances[0].src).toContain('yu-jian.mp3')
  })

  it('never resumes while the feature gate is off, even if playing was persisted', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ playing: true, trackId: 'sun-yanzi-yujian' }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.enabled.value).toBe(false)
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances.every(a => !a.play.mock.calls.length)).toBe(true)
  })

  it('degrades to paused when the browser blocks the autoplay resume', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ enabled: true, playing: true, trackId: 'sun-yanzi-yujian' }),
    )
    FakeAudio.playError = new Error('NotAllowedError')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.playing.value).toBe(false)
  })

  it('falls back to the default track when the persisted id is gone or local', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ playing: false, trackId: '__local__' }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
  })

  it('falls back from a persisted local track without resuming playback', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ enabled: true, playing: true, trackId: '__local__' }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()

    await bgm.initBgm()

    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances).toHaveLength(0)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      trackId: 'sun-yanzi-yujian',
      playing: false,
    })
  })

  it('keeps a local file added while the playlist is loading as the selection', async () => {
    localStorage.setItem('opensquilla-bgm', JSON.stringify({ enabled: true }))
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:during-init')
    const manifest = stubDeferredBaseManifest()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()

    const pendingInit = bgm.initBgm()
    await bgm.playLocalFile(new File(['music'], 'chosen.mp3', { type: 'audio/mpeg' }))
    manifest.resolve()
    await pendingInit

    // Uploads never auto-play; the mid-boot pick stays selected, paused.
    expect(bgm.currentTrackId.value).toMatch(/^local:/)
    expect(bgm.currentTitle.value).toBe('chosen.mp3')
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances).toHaveLength(0)
  })

  it('does not resume a stale snapshot after disable and re-enable during init', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ enabled: true, playing: true, trackId: 'sun-yanzi-yujian' }),
    )
    const manifest = stubDeferredBaseManifest()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()

    const pendingInit = bgm.initBgm()
    bgm.setEnabled(false)
    bgm.setEnabled(true)
    manifest.resolve()
    await pendingInit

    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances).toHaveLength(0)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      enabled: true,
      trackId: 'sun-yanzi-yujian',
      playing: false,
    })
  })

  it('prefers the gitignored playlist.local.json over the tracked manifest', async () => {
    stubFetch(PLAYLIST, true, {
      tracks: [{ id: 'personal-default', title: '孙燕姿 - 遇见', src: 'yu-jian.mp3' }],
    })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.tracks.value.map(t => t.id)).toEqual(['personal-default'])
    expect(bgm.currentTrackId.value).toBe('personal-default')
    expect(bgm.playlistError.value).toBe(false)
  })

  it('treats the deliberately-empty tracked manifest as valid, not an error', async () => {
    // Mirrors the shipped playlist.json: a "//" comment key (JSON has no real
    // comments) carrying an example entry, plus empty tracks. Comment keys are
    // ignored, never loaded.
    stubFetch({
      '//': ['example:', { tracks: [{ id: 'example', title: 'Example', src: 'x.mp3' }] }],
      tracks: [],
    })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.tracks.value).toEqual([])
    expect(bgm.playlistError.value).toBe(false)
  })

  it('degrades to an empty playlist when the manifest is missing', async () => {
    stubFetch({}, false)
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.playlistError.value).toBe(true)
    expect(bgm.tracks.value).toEqual([])
    // toggle() with nothing playable is a safe no-op.
    await bgm.toggle()
    expect(bgm.playing.value).toBe(false)
  })
})

describe('useBgm — feature gate', () => {
  it('defaults to disabled on a fresh profile', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    expect(useBgm().enabled.value).toBe(false)
  })

  it('restores a persisted enable synchronously at module init', async () => {
    localStorage.setItem('opensquilla-bgm', JSON.stringify({ enabled: true }))
    stubFetch()
    const { useBgm } = await freshBgm()
    // No initBgm() yet — App.vue's v-if reads this before anything mounts.
    expect(useBgm().enabled.value).toBe(true)
  })

  it('setEnabled(true) persists the gate', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ enabled: true })
  })

  it('setEnabled(false) silences playback immediately and persists paused', async () => {
    localStorage.setItem('opensquilla-bgm', JSON.stringify({ enabled: true }))
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    await bgm.toggle()
    expect(bgm.playing.value).toBe(true)
    bgm.setEnabled(false)
    expect(bgm.playing.value).toBe(false)
    expect(FakeAudio.instances[0].pause).toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      enabled: false,
      playing: false,
    })
  })

  it('toggle() does not start playback while disabled', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    await bgm.toggle()

    expect(FakeAudio.instances).toHaveLength(0)
    expect(bgm.playing.value).toBe(false)
  })

  it('selectTrack() does not start playback while disabled', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    await bgm.selectTrack('stream')

    expect(FakeAudio.instances).toHaveLength(0)
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(bgm.playing.value).toBe(false)
  })

  it('playLocalFile() does not start playback while disabled', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    await bgm.playLocalFile(new File(['music'], 'local.mp3', { type: 'audio/mpeg' }))

    expect(createObjectURL).not.toHaveBeenCalled()
    expect(FakeAudio.instances).toHaveLength(0)
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(bgm.localTracks.value).toEqual([])
    expect(bgm.localTrackTitle.value).toBe('')
    expect(bgm.playing.value).toBe(false)
  })
})

describe('useBgm — controls', () => {
  it('toggle() starts the default track, persists, and pauses on re-toggle', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    await bgm.toggle()
    expect(bgm.playing.value).toBe(true)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      playing: true,
      trackId: 'sun-yanzi-yujian',
    })

    await bgm.toggle()
    expect(bgm.playing.value).toBe(false)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ playing: false })
  })

  it('selectTrack() switches the source; absolute URLs pass through', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.selectTrack('stream')
    expect(bgm.currentTrackId.value).toBe('stream')
    expect(FakeAudio.instances[0].src).toBe('https://example.com/track.mp3')
    expect(bgm.playing.value).toBe(true)
  })

  it('setVolume() clamps, applies to the element, and persists', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    bgm.setVolume(1.4)
    expect(bgm.volume.value).toBe(1)
    expect(FakeAudio.instances[0].volume).toBe(1)
    bgm.setVolume(-2)
    expect(bgm.volume.value).toBe(0)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ volume: 0 })
    // step="any" sliders report raw drag positions; persist two decimals.
    bgm.setVolume(0.6300000000000001)
    expect(bgm.volume.value).toBe(0.63)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ volume: 0.63 })
  })

  it('external play events sync and persist the playing state', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    await bgm.toggle()
    expect(bgm.playing.value).toBe(false)

    FakeAudio.instances[0].emit('play')

    expect(bgm.playing.value).toBe(true)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ playing: true })
  })

  it.each(['pause', 'error'] as const)(
    'external %s events sync and persist the paused state',
    async event => {
      stubFetch()
      const { useBgm } = await freshBgm()
      const bgm = useBgm()
      await bgm.initBgm()
      bgm.setEnabled(true)
      await bgm.toggle()
      expect(bgm.playing.value).toBe(true)

      FakeAudio.instances[0].emit(event)

      expect(bgm.playing.value).toBe(false)
      expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ playing: false })
    },
  )

  it('immediately pauses and persists an external play event while disabled', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    bgm.setEnabled(false)
    const el = FakeAudio.instances[0]
    el.pause.mockClear()

    el.emit('play')

    expect(el.pause).toHaveBeenCalledOnce()
    expect(el.paused).toBe(true)
    expect(bgm.playing.value).toBe(false)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      enabled: false,
      playing: false,
    })
  })
})

describe('useBgm — pending playback', () => {
  it('setEnabled(false) cancels pending playlist playback before it settles', async () => {
    let resolvePlay!: () => void
    FakeAudio.playDeferred = new Promise<void>(resolve => { resolvePlay = resolve })
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    const pendingPlay = bgm.toggle()
    const el = FakeAudio.instances[0]
    bgm.setEnabled(false)

    expect(el.pause).toHaveBeenCalledOnce()
    expect(el.paused).toBe(true)
    expect(bgm.playing.value).toBe(false)
    resolvePlay()
    await pendingPlay
    expect(el.paused).toBe(true)
    expect(bgm.enabled.value).toBe(false)
    expect(bgm.playing.value).toBe(false)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      enabled: false,
      playing: false,
    })
  })

  it('setEnabled(false) cancels pending local-track playback before it settles', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.playLocalFile(new File(['music'], 'local.mp3', { type: 'audio/mpeg' }))
    const localId = bgm.localTracks.value[0]!.id

    let resolvePlay!: () => void
    FakeAudio.playDeferred = new Promise<void>(resolve => { resolvePlay = resolve })
    const pendingPlay = bgm.selectTrack(localId)
    await Promise.resolve()
    const el = FakeAudio.instances[0]
    bgm.setEnabled(false)

    expect(el.pause).toHaveBeenCalledOnce()
    expect(el.paused).toBe(true)
    expect(bgm.playing.value).toBe(false)
    resolvePlay()
    await pendingPlay
    expect(el.paused).toBe(true)
    expect(bgm.enabled.value).toBe(false)
    expect(bgm.playing.value).toBe(false)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      enabled: false,
      playing: false,
    })
  })

  it('ignores an older rejected request after a newer request starts playing', async () => {
    let rejectFirst!: (error: Error) => void
    FakeAudio.playDeferred = new Promise<void>((_resolve, reject) => { rejectFirst = reject })
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    const olderPlay = bgm.toggle()
    FakeAudio.playDeferred = null
    await bgm.selectTrack('stream')
    expect(bgm.currentTrackId.value).toBe('stream')
    expect(bgm.playing.value).toBe(true)

    rejectFirst(new Error('older request failed'))
    await olderPlay

    expect(bgm.currentTrackId.value).toBe('stream')
    expect(bgm.playing.value).toBe(true)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      trackId: 'stream',
      playing: true,
    })
  })
})

describe('useBgm — local library', () => {
  it('persists an upload and restores it after a restart, resuming playback', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    stubFetch()
    {
      const { useBgm } = await freshBgm()
      const bgm = useBgm()
      await bgm.initBgm()
      bgm.setEnabled(true)
      await bgm.playLocalFile(new File(['music'], 'mine.mp3', { type: 'audio/mpeg' }))
      expect(bgm.localTracks.value.map(t => t.title)).toEqual(['mine.mp3'])
      // Uploads never auto-play; the user starts it from the picker.
      expect(bgm.playing.value).toBe(false)
      await bgm.selectTrack(bgm.localTracks.value[0]!.id)
      expect(bgm.currentTrackId.value).toMatch(/^local:/)
      expect(bgm.playing.value).toBe(true)
    }
    const savedId = [...bgmLibrary.rows.keys()][0]

    // "Restart": fresh module, same localStorage + library store.
    FakeAudio.instances = []
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    expect(bgm.localTracks.value.map(t => t.title)).toEqual(['mine.mp3'])
    expect(bgm.currentTrackId.value).toBe(savedId)
    expect(bgm.currentTitle.value).toBe('mine.mp3')
    expect(bgm.playing.value).toBe(true)
    expect(FakeAudio.instances[0].src).toBe('blob:lib')
  })

  it('lists uploads after the manifest tracks, oldest first', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.playLocalFile(new File(['a'], 'first.mp3', { type: 'audio/mpeg' }))
    await bgm.playLocalFile(new File(['b'], 'second.mp3', { type: 'audio/mpeg' }))

    expect(bgm.localTracks.value.map(t => t.title)).toEqual(['first.mp3', 'second.mp3'])
    expect(bgm.tracks.value.length).toBe(2)
  })

  it('removeLocalTrack deletes the upload and falls back paused when it was playing', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.playLocalFile(new File(['music'], 'mine.mp3', { type: 'audio/mpeg' }))
    const id = bgm.localTracks.value[0]!.id
    await bgm.selectTrack(id)
    expect(bgm.playing.value).toBe(true)

    await bgm.removeLocalTrack(id)

    expect(bgm.localTracks.value).toEqual([])
    expect(bgmLibrary.rows.size).toBe(0)
    expect(revoke).toHaveBeenCalledWith('blob:lib')
    expect(bgm.playing.value).toBe(false)
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({
      trackId: 'sun-yanzi-yujian',
      playing: false,
    })
  })

  it('removing a non-current upload does not interrupt playback', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.playLocalFile(new File(['music'], 'mine.mp3', { type: 'audio/mpeg' }))
    const uploadId = bgm.localTracks.value[0]!.id
    await bgm.selectTrack('stream')
    expect(bgm.playing.value).toBe(true)

    await bgm.removeLocalTrack(uploadId)

    expect(bgm.localTracks.value).toEqual([])
    expect(bgm.currentTrackId.value).toBe('stream')
    expect(bgm.playing.value).toBe(true)
  })

  it('degrades to the session-only slot when the library is unavailable', async () => {
    bgmLibrary.available = false
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:session')
    stubFetch()
    const { useBgm, BGM_LOCAL_TRACK_ID } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    await bgm.playLocalFile(new File(['music'], 'mine.mp3', { type: 'audio/mpeg' }))

    // The pick lands in the session slot, selectable but not auto-played.
    expect(bgm.localTracks.value).toEqual([])
    expect(bgm.localTrackTitle.value).toBe('mine.mp3')
    expect(bgm.playing.value).toBe(false)

    await bgm.selectTrack(BGM_LOCAL_TRACK_ID)
    expect(bgm.currentTrackId.value).toBe(BGM_LOCAL_TRACK_ID)
    expect(bgm.playing.value).toBe(true)
    expect(FakeAudio.instances[0].src).toBe('blob:session')
  })
})

describe('useBgm — play modes', () => {
  it('defaults to order and persists mode changes across restarts', async () => {
    stubFetch()
    {
      const { useBgm } = await freshBgm()
      const bgm = useBgm()
      await bgm.initBgm()
      expect(bgm.playMode.value).toBe('order')
      bgm.setPlayMode('shuffle')
      expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ mode: 'shuffle' })
    }
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.playMode.value).toBe('shuffle')
  })

  it('order mode: disables loop for multi-track lists and advances on ended, wrapping', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    const el = FakeAudio.instances[0]
    expect(el.loop).toBe(false)

    el.emit('ended')
    await vi.waitFor(() => expect(bgm.currentTrackId.value).toBe('stream'))
    expect(bgm.playing.value).toBe(true)

    el.emit('ended')
    await vi.waitFor(() => expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian'))
  })

  it('shuffle mode: advances to a different track on ended', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    bgm.setPlayMode('shuffle')
    await bgm.toggle()
    const el = FakeAudio.instances[0]
    expect(el.loop).toBe(false)

    el.emit('ended')
    await vi.waitFor(() => expect(bgm.currentTrackId.value).toBe('stream'))
  })

  it('repeat-one mode keeps the element looping so it never advances', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    const el = FakeAudio.instances[0]
    expect(el.loop).toBe(false)

    bgm.setPlayMode('one')
    expect(el.loop).toBe(true)
  })

  it('a single-track list keeps looping regardless of mode', async () => {
    stubFetch({ tracks: [{ id: 'only', title: 'Only', src: 'only.mp3' }] })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    expect(FakeAudio.instances[0].loop).toBe(true)
  })

  it('playNext/playPrevious step through the list with wrap-around', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')

    await bgm.playNext()
    expect(bgm.currentTrackId.value).toBe('stream')
    await bgm.playNext()
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    await bgm.playPrevious()
    expect(bgm.currentTrackId.value).toBe('stream')
    expect(bgm.playing.value).toBe(true)
  })

  it('skip controls are no-ops while the feature gate is off', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    await bgm.playNext()
    await bgm.playPrevious()

    expect(FakeAudio.instances).toHaveLength(0)
    expect(bgm.playing.value).toBe(false)
  })

  it('ended does not advance while the feature gate is off', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    const el = FakeAudio.instances[0]
    bgm.setEnabled(false)
    el.play.mockClear()

    el.emit('ended')
    await Promise.resolve()

    expect(el.play).not.toHaveBeenCalled()
    expect(bgm.playing.value).toBe(false)
  })
})

describe('useBgm — mute, seek, and library management', () => {
  it('toggleMute flips element mute without touching the volume, and persists', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    const el = FakeAudio.instances[0]

    bgm.toggleMute()
    expect(bgm.muted.value).toBe(true)
    expect(el.muted).toBe(true)
    expect(bgm.volume.value).toBe(0.6)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ muted: true })

    bgm.toggleMute()
    expect(bgm.muted.value).toBe(false)
    expect(el.muted).toBe(false)
  })

  it('restores a persisted mute on init', async () => {
    localStorage.setItem(
      'opensquilla-bgm',
      JSON.stringify({ enabled: true, playing: true, trackId: 'sun-yanzi-yujian', muted: true }),
    )
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    expect(bgm.muted.value).toBe(true)
    expect(FakeAudio.instances[0].muted).toBe(true)
  })

  it('tracks progress/duration from media events and seeks with clamping', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()
    const el = FakeAudio.instances[0]

    el.duration = 200
    el.emit('durationchange')
    expect(bgm.duration.value).toBe(200)
    el.currentTime = 42
    el.emit('timeupdate')
    expect(bgm.progress.value).toBe(42)

    bgm.seek(500)
    expect(el.currentTime).toBe(200)
    expect(bgm.progress.value).toBe(200)
    bgm.seek(-5)
    expect(el.currentTime).toBe(0)
  })

  it('seek is a no-op before the duration is known', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.toggle()

    bgm.seek(30)

    expect(FakeAudio.instances[0].currentTime).toBe(0)
    expect(bgm.progress.value).toBe(0)
  })

  it('addLocalFiles stores every pick without starting playback', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    const result = await bgm.addLocalFiles([
      new File(['a'], 'first.mp3', { type: 'audio/mpeg' }),
      new File(['b'], 'second.mp3', { type: 'audio/mpeg' }),
    ])

    expect(result).toEqual({ unsaved: 0 })
    expect(bgm.localTracks.value.map(t => t.title)).toEqual(['first.mp3', 'second.mp3'])
    expect(bgmLibrary.rows.size).toBe(2)
    // Playback state and the existing selection are untouched.
    expect(bgm.playing.value).toBe(false)
    expect(bgm.currentTrackId.value).toBe('sun-yanzi-yujian')
    expect(FakeAudio.instances).toHaveLength(0)
  })

  it('addLocalFiles selects the first upload when nothing was selected yet', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    stubFetch({ tracks: [] })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    expect(bgm.currentTrackId.value).toBe('')

    await bgm.addLocalFiles([new File(['a'], 'first.mp3', { type: 'audio/mpeg' })])

    expect(bgm.currentTrackId.value).toMatch(/^local:/)
    expect(bgm.playing.value).toBe(false)
  })

  it('addLocalFiles reports every file unsaved when the library is unavailable', async () => {
    bgmLibrary.available = false
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:session')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)

    const result = await bgm.addLocalFiles([
      new File(['a'], 'first.mp3', { type: 'audio/mpeg' }),
      new File(['b'], 'second.mp3', { type: 'audio/mpeg' }),
    ])

    expect(result).toEqual({ unsaved: 2 })
    // Degraded mode keeps the first file in the single session slot, paused.
    expect(bgm.localTrackTitle.value).toBe('first.mp3')
    expect(bgm.playing.value).toBe(false)
  })

  it('renameLocalTrack renames in the store and the picker, rejecting blanks', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:lib')
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    bgm.setEnabled(true)
    await bgm.playLocalFile(new File(['music'], 'raw-name.mp3', { type: 'audio/mpeg' }))
    const id = bgm.localTracks.value[0]!.id

    expect(await bgm.renameLocalTrack(id, '  遇见 (live)  ')).toBe(true)
    expect(bgm.localTracks.value[0]!.title).toBe('遇见 (live)')
    expect([...bgmLibrary.rows.values()][0]!.title).toBe('遇见 (live)')

    expect(await bgm.renameLocalTrack(id, '   ')).toBe(false)
    expect(bgm.localTracks.value[0]!.title).toBe('遇见 (live)')
    expect(await bgm.renameLocalTrack('not-a-local-id', 'x')).toBe(false)
  })
})
