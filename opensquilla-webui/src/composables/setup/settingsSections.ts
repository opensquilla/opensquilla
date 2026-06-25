// Canonical list of Settings rail sections, kept in a standalone module so both
// the catalog composable and the route↔section mapping helpers can import it
// without forming an import cycle.

export const SETTINGS_SECTIONS = [
  // Connection carries a live status dot (driven by the gateway socket state,
  // not readiness RPC) so it works before any config loads. It applies on
  // Connect and never enters the dirty bar, so it is excluded from save/discard.
  { id: 'connection', label: 'Connection', icon: 'home', client: false },
  { id: 'provider', label: 'Provider', icon: 'agents', client: false },
  { id: 'router', label: 'Router', icon: 'cron', client: false },
  { id: 'channels', label: 'Channels', icon: 'channels', client: false },
  { id: 'capabilities', label: 'Capabilities', icon: 'skills', client: false },
  // Client-only sections carry no readiness/RPC state: they edit local browser
  // preferences that apply instantly and never enter the dirty bar. The status
  // dot is suppressed for them in the rail.
  { id: 'appearance', label: 'Appearance', icon: 'monitor', client: true },
  { id: 'keyboard', label: 'Keyboard', icon: 'keyboard', client: true },
  { id: 'advanced', label: 'Advanced', icon: 'gauge', client: true },
] as const

export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]['id']
