export const THEME = Object.freeze({
  preset: "daily",
  frameStyle: "card",
  detailMode: "inline",
  answerMode: "panel",
  motion: "pulse",
  text: "#F4F7FB",
  muted: "#667385",
  faint: "#3E4A57",
  frame: "#5a6b7a",
  composerBorder: "#77B7FF",
  // Opaque panel background for floating overlays (completion menu). Without an
  // opaque fill a BoxRenderable defaults to a transparent background, so the
  // conversation behind the menu shows through and the two collide on screen.
  overlayBg: "#11161C",
  composerDisabledBorder: "#354453",
  routerNormal: "#73D0A7",
  routerWarning: "#F6C177",
  routerError: "#FF7B8A",
  toolAccent: "#69D2E7",
  detailText: "#8A96A6",
  answerAccent: "#9AD18B",
  modelText: "#C4B5FD",
  promptAccent: "#FFB86C",
  routeText: "#C4B5FD",
  savingText: "#8BD5CA",
});
export const STATUS_PULSE_FRAMES = Object.freeze({
  thinking: ["∙", "•", "●", "•"],
  tool: ["◌", "◔", "◑", "◕"],
  output: ["◇", "◆", "◇", "◆"],
});
