import type { ThemeManifest } from '../types'

// A custom value theme, shipped as the reference for "drop a folder → it appears
// in the appearance picker". Cool arctic palette. Its display name is a
// proper-noun literal (like the language names), so no per-locale key is needed;
// built-in light/dark/system keep their translated labels. Token values live in
// ./tokens.css (validated by the contract + contrast guards).
const arctic: ThemeManifest = {
  id: 'arctic',
  name: 'Arctic',
  kind: 'value',
  icon: 'cloud',
  capabilities: { colorScheme: 'dark', userSelectable: true },
}

export default arctic
