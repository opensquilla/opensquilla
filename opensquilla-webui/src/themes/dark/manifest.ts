import type { ThemeManifest } from '../types'

// Value theme "dark" — the default ground (its tokens.css keeps `:root` in the
// selector). The applied token VALUES live in ./tokens.css, the single source of
// truth validated by check-theme-contract.mjs; they are not duplicated here.
const dark: ThemeManifest = {
  id: 'dark',
  name: 'theme.dark',
  kind: 'value',
  icon: 'moon',
  capabilities: { colorScheme: 'dark', userSelectable: true },
}

export default dark
