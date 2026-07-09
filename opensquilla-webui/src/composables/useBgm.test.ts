// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi } from 'vitest'

// useBgm keeps module-level singleton state (one Audio element app-wide), so
// each test re-imports a fresh module via vi.resetModules().

class FakeAudio {
  loop = false
  preload = ''
  volume = 1
  src = ''
  paused = true
  static instances: FakeAudio[] = []
  static playError: Error | null = null
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
    this.paused = false
  })
  pause = vi.fn(() => {
    this.paused = true
  })
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

async function freshBgm() {
  vi.resetModules()
  return import('./useBgm')
}

beforeEach(() => {
  localStorage.clear()
  FakeAudio.instances = []
  FakeAudio.playError = null
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
        { id: 'https', title: 'HTTPS', src: 'https://example.com/track.mp3' },
        { id: 'http', title: 'HTTP', src: 'http://example.com/track.mp3' },
        { id: 'scheme-relative', title: 'Scheme relative', src: '//example.com/track.mp3' },
        { id: 'data', title: 'Data', src: 'data:audio/mpeg;base64,AA==' },
      ],
    })
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

    expect(bgm.tracks.value.map(t => t.id)).toEqual(['relative', 'https'])
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
})

describe('useBgm — controls', () => {
  it('toggle() starts the default track, persists, and pauses on re-toggle', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()

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
    await bgm.toggle()
    bgm.setVolume(1.4)
    expect(bgm.volume.value).toBe(1)
    expect(FakeAudio.instances[0].volume).toBe(1)
    bgm.setVolume(-2)
    expect(bgm.volume.value).toBe(0)
    expect(JSON.parse(localStorage.getItem('opensquilla-bgm')!)).toMatchObject({ volume: 0 })
  })

  it('external pause events (e.g. OS media keys) sync the playing ref', async () => {
    stubFetch()
    const { useBgm } = await freshBgm()
    const bgm = useBgm()
    await bgm.initBgm()
    await bgm.toggle()
    expect(bgm.playing.value).toBe(true)
    FakeAudio.instances[0].emit('pause')
    expect(bgm.playing.value).toBe(false)
  })
})
