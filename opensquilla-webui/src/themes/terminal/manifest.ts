import type { ThemeManifest } from '../types'

// A full aesthetic WORLD (not just a palette): an amber CRT terminal identity
// applied globally when selected. The palette lives in ./tokens.css (eager,
// contract + contrast checked); the world layer (mono type, hard frames,
// amber glow, scanlines, blinking cursor) is ./world.css, loaded lazily on
// activation so other-theme users download none of it. Reuses the bundled
// IBM Plex Mono, so it ships no extra fonts.
const terminal: ThemeManifest = {
  id: 'terminal',
  name: 'Terminal',
  kind: 'value',
  icon: 'gauge',
  capabilities: { colorScheme: 'dark', userSelectable: true, respectsReducedMotion: true },
  world: { styles: () => import('./world.css') },
}

export default terminal
