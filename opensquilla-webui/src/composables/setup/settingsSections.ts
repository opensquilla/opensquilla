// Canonical list of Settings rail sections, kept in a standalone module so both
// the catalog composable and the route↔section mapping helpers can import it
// without forming an import cycle.

export const SETTINGS_SECTIONS = [
  // Connection carries a live status dot (driven by the gateway socket state,
  // not readiness RPC) so it works before any config loads. It applies on
  // Connect and never enters the dirty bar, so it is excluded from save/discard.
  { id: 'connection', label: 'Connection', icon: 'home', client: false, desktopOnly: false },
  // Runtime is desktop-only: the owned local gateway's status, log, restart, and
  // reset. It is client-like (no readiness/RPC state, never dirty) and hidden on
  // web, where the host does not own a gateway process.
  { id: 'runtime', label: 'Runtime', icon: 'monitor', client: true, desktopOnly: true },
  { id: 'provider', label: 'Provider', icon: 'agents', client: false, desktopOnly: false },
  { id: 'behavior', label: 'Behavior', icon: 'chat', client: false, desktopOnly: false },
  { id: 'privacy', label: 'Privacy', icon: 'shield', client: false, desktopOnly: false },
  { id: 'router', label: 'Router', icon: 'cron', client: false, desktopOnly: false },
  { id: 'channels', label: 'Channels', icon: 'channels', client: false, desktopOnly: false },
  { id: 'capabilities', label: 'Capabilities', icon: 'skills', client: false, desktopOnly: false },
  // Client-only sections carry no readiness/RPC state: they edit local browser
  // preferences that apply instantly and never enter the dirty bar. The status
  // dot is suppressed for them in the rail.
  { id: 'appearance', label: 'Appearance', icon: 'monitor', client: true, desktopOnly: false },
  { id: 'keyboard', label: 'Keyboard', icon: 'keyboard', client: true, desktopOnly: false },
  { id: 'advanced', label: 'Advanced', icon: 'gauge', client: true, desktopOnly: false },
] as const

export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]['id']
