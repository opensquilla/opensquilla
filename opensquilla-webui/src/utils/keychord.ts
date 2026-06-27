// Keyboard chord model shared by the global shortcut handler (App.vue) and the
// Keyboard settings panel. A binding is platform-relative: `primary` means Cmd
// on Apple platforms and Ctrl elsewhere, so a single stored binding renders and
// matches correctly on both. `secondary` (the other of Ctrl/Cmd) is always
// required-absent at match time — see bindingMatches — so we never steal macOS'
// Ctrl+K (emacs kill-to-end-of-line) when the primary is Cmd.

export interface Binding {
  /** Cmd on macOS / iOS, Ctrl elsewhere. */
  primary?: boolean
  alt?: boolean
  shift?: boolean
  /** Single non-modifier key, lower-cased (e.g. 'k'). */
  key: string
}

const MODIFIER_KEYS = new Set([
  'control',
  'meta',
  'shift',
  'alt',
  'altgraph',
  'os',
  'hyper',
  'super',
  'capslock',
  'fn',
  'fnlock',
])

/**
 * Normalize a KeyboardEvent into a Binding, or null when the event carries only
 * modifier keys (so the rebind recorder ignores a lone Shift press) or no
 * primary modifier (we only record chord shortcuts, not bare letters). `mac`
 * decides whether Cmd or Ctrl counts as the platform-primary modifier.
 */
export function eventToBinding(e: KeyboardEvent, mac: boolean): Binding | null {
  const key = (e.key || '').toLowerCase()
  if (!key || MODIFIER_KEYS.has(key)) return null

  const primary = mac ? e.metaKey : e.ctrlKey
  if (!primary) return null

  return {
    primary: true,
    alt: e.altKey || undefined,
    shift: e.shiftKey || undefined,
    key,
  }
}

/**
 * Whether a live KeyboardEvent satisfies a stored binding. Ports the exact
 * guard the hardcoded handler used: the platform-primary modifier must be set,
 * the platform-secondary modifier must be absent, and Alt/Shift must match the
 * binding exactly. Key comparison is case-insensitive.
 */
export function bindingMatches(e: KeyboardEvent, binding: Binding | null, mac: boolean): boolean {
  if (!binding) return false
  const primary = mac ? e.metaKey : e.ctrlKey
  const secondary = mac ? e.ctrlKey : e.metaKey
  if (!!binding.primary !== primary) return false
  if (secondary) return false
  if (!!binding.alt !== e.altKey) return false
  if (!!binding.shift !== e.shiftKey) return false
  return (e.key || '').toLowerCase() === binding.key
}

/** Two bindings are equal when they describe the same chord. */
export function bindingsEqual(a: Binding | null, b: Binding | null): boolean {
  if (!a || !b) return a === b
  return (
    !!a.primary === !!b.primary &&
    !!a.alt === !!b.alt &&
    !!a.shift === !!b.shift &&
    a.key === b.key
  )
}

/**
 * Render a binding as a display chord, e.g. ⌘⇧K on Mac, Ctrl+Shift+K elsewhere.
 * Modifier order matches platform convention; the key is upper-cased for a
 * single letter and otherwise title-cased (e.g. 'arrowup' → 'Arrowup').
 */
export function formatBinding(binding: Binding | null, mac: boolean): string {
  if (!binding) return ''
  const parts: string[] = []
  if (binding.primary) parts.push(mac ? '⌘' : 'Ctrl')
  if (binding.alt) parts.push(mac ? '⌥' : 'Alt')
  if (binding.shift) parts.push(mac ? '⇧' : 'Shift')
  parts.push(keyLabel(binding.key))
  return parts.join(mac ? '' : '+')
}

function keyLabel(key: string): string {
  if (key.length === 1) return key.toUpperCase()
  return key.charAt(0).toUpperCase() + key.slice(1)
}
