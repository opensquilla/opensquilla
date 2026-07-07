import type { ThemeManifest } from "../types"

// Value theme "miami" -- Miami daylight -- a warm peachy off-white ground lit by hot flamingo pink, aqua-teal, coral and violet neon accents, with deep plum ink.
// Applied token values live in ./tokens.css (contract + contrast guards).
const miami: ThemeManifest = {
  id: "miami",
  name: "Miami",
  kind: "value",
  icon: "sun",
  world: { styles: () => import("./world.css") },
  capabilities: { colorScheme: "light", userSelectable: true, respectsReducedMotion: true },
}

export default miami
