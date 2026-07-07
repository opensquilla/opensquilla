import type { ThemeManifest } from "../types"

// Value theme "ember" -- Volcanic warm-dark -- a charcoal-ember ground with a red-brown cast, lit by molten orange, gold, coral and lava red.
// Applied token values live in ./tokens.css (contract + contrast guards).
const ember: ThemeManifest = {
  id: "ember",
  name: "Ember",
  kind: "value",
  icon: "gauge",
  world: { styles: () => import("./world.css") },
  capabilities: { colorScheme: "dark", userSelectable: true, respectsReducedMotion: true },
}

export default ember
