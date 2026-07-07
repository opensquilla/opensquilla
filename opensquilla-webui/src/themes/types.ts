// Pluggable theme engine — type contract.
//
// Two axes (see the theme architecture spec):
//   • value theme  — a global L1 value re-skin applied via `data-theme` on <html>,
//     with its token block in a co-located tokens.css (validated by
//     check-theme-contract.mjs) and an optional global "world" layer.
//   • expressive skin — a route-scoped skin applied via `data-skin`, with its
//     token pack + structural rules in a co-located skin.css.
// Deliberately minimal: a field earns its place here when something reads it.

export type ThemeKind = 'value' | 'expressive'
export type ColorScheme = 'light' | 'dark' | 'both'

/** Expressive-skin payload (Axis B). Every asset is a lazy thunk so a skin
 *  never enters the base bundle. */
export interface ThemeSkin {
  fonts?: { family: string; load: () => Promise<unknown> }[]
  variants?: string[]
  styles?: () => Promise<unknown>
}

/** A value theme's optional "world": a GLOBAL expressive layer (type faces,
 *  texture, glow, motion, shape) applied app-wide when the theme is active, on
 *  top of its palette. Loaded lazily on activation, so themes without a world
 *  (light/dark) stay a clean value swap and console users never pay for it. */
export interface ThemeWorld {
  fonts?: { family: string; load: () => Promise<unknown> }[]
  styles?: () => Promise<unknown>
}

export interface ThemeCapabilities {
  /** Value themes: which OS colour-scheme slot(s) this fills (drives `system`). */
  colorScheme?: ColorScheme
  /** Appears in the global appearance switcher? (skins are always false) */
  userSelectable: boolean
  /** Skins: grounds they compose cleanly over. */
  compatibleGrounds?: string[] | '*'
  respectsReducedMotion?: boolean
}

export interface ThemeManifest {
  /** value → the `data-theme` value; skin → the `data-skin` value. */
  id: string
  /** i18n key; falls back to a titlecased id if the key is absent. */
  name: string
  kind: ThemeKind
  /** Icon (from the icon set) shown next to this theme in the appearance picker. */
  icon?: import('@/utils/icons').IconName
  /** Route-scoped expressive skin (Axis B). */
  skin?: ThemeSkin
  /** Global expressive "world" layer (structure/type/texture) for a value theme,
   *  applied app-wide via data-theme and loaded lazily on activation. */
  world?: ThemeWorld
  capabilities: ThemeCapabilities
}
