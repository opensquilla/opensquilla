import type { ThemeManifest } from '../types'

// The first expressive skin (Axis B), and the reference implementation that
// validates the contract. Everything heavy — the serif faces, the scoped
// stylesheet — is a lazy thunk, so a console user who never opens a skinned
// route downloads none of it (proven in CI by check-theme-bundle.mjs). The
// token pack + structural rules live in the co-located skin.css, scoped to
// [data-skin="out-of-register"]; nothing here can touch the operational UI.
const outOfRegister: ThemeManifest = {
  id: 'out-of-register',
  name: 'theme.outOfRegister',
  kind: 'expressive',
  capabilities: {
    userSelectable: false,
    compatibleGrounds: '*',
    respectsReducedMotion: true,
  },
  skin: {
    fonts: [
      { family: 'Fraunces', load: () => import('./fonts/fraunces.css') },
      { family: 'Newsreader', load: () => import('./fonts/newsreader.css') },
    ],
    variants: ['serif', 'flat', 'newsprint'],
    styles: () => import('./skin.css'),
  },
}

export default outOfRegister
