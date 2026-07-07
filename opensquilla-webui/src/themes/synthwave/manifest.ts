import type { ThemeManifest } from "../types"

// Value theme "synthwave" -- retrowave '80s neon sunset -- indigo/violet-black ground under electric magenta, cyan and hot-pink neon with a sunset-orange strike.
// Applied token values live in ./tokens.css (contract + contrast guards); the
// world layer (scrolling neon perspective grid, breathing accent glow, chrome
// uppercase display headings) is ./world.css, loaded lazily on activation so
// other-theme users download none of it. Reuses the bundled fonts.
const synthwave: ThemeManifest = {
  id: "synthwave",
  name: "Synthwave",
  kind: "value",
  icon: "moon",
  capabilities: { colorScheme: "dark", userSelectable: true, respectsReducedMotion: true },
  world: { styles: () => import("./world.css") },
}

export default synthwave
