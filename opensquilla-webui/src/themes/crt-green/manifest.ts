import type { ThemeManifest } from "../types"

// Value theme "crt-green" -- a green-screen CRT terminal look -- a faintly
// green-tinted near-black ground lit by one vivid electric-green accent, a
// cyan-teal secondary, and bright terminal status colours.
// Applied token values live in ./tokens.css (contract + contrast guards).
const crtGreen: ThemeManifest = {
  id: "crt-green",
  name: "CRT Green",
  kind: "value",
  icon: "monitor",
  capabilities: { colorScheme: "dark", userSelectable: true },
}

export default crtGreen
