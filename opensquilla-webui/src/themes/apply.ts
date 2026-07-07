import { getManifest } from './registry'

// Theme-asset runtime: lazily load a value theme's global "world" layer or an
// expressive skin's assets. A theme/skin's token pack + structural CSS live in
// co-located css files (tokens.css / skin.css / world.css) — the single source
// of truth the CI guards validate — so this module only orchestrates loading.

const worldLoaded = new Set<string>()

/** Lazily load a value theme's global "world" layer (fonts + app-wide stylesheet)
 *  when it becomes the active data-theme. Idempotent; a no-op for themes without
 *  a world (light/dark/arctic and the flat vivid palettes). */
export async function ensureThemeWorld(id: string): Promise<void> {
  if (!id || worldLoaded.has(id)) return
  const m = getManifest(id)
  if (!m || !m.world) return
  worldLoaded.add(id)
  try {
    await Promise.all([
      ...(m.world.fonts ?? []).map((f) => f.load()),
      m.world.styles ? m.world.styles() : Promise.resolve(),
    ])
  } catch (err) {
    worldLoaded.delete(id)
    console.warn(`[themes] failed to load world "${id}":`, err)
  }
}

const assetsLoaded = new Set<string>()

/** Lazily load a skin's fonts + scoped stylesheet. Idempotent, and a no-op for
 *  value themes / unknown ids. Every asset is a manifest thunk, so nothing here
 *  is in the base bundle. */
export async function ensureSkinAssets(id: string): Promise<void> {
  if (assetsLoaded.has(id)) return
  const m = getManifest(id)
  if (!m || m.kind !== 'expressive' || !m.skin) return
  assetsLoaded.add(id) // reserve early so concurrent callers don't double-load
  const { fonts, styles } = m.skin
  try {
    await Promise.all([
      ...(fonts ?? []).map((f) => f.load()),
      styles ? styles() : Promise.resolve(),
    ])
  } catch (err) {
    assetsLoaded.delete(id) // allow a retry on the next navigation
    console.warn(`[themes] failed to load skin "${id}" assets:`, err)
  }
}
