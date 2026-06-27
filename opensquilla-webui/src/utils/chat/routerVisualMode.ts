export type RouterVisualMode = 'real_candidates' | 'legacy_grid'

export const DEFAULT_ROUTER_VISUAL_MODE: RouterVisualMode = 'real_candidates'

export function normalizeRouterVisualMode(value: unknown): RouterVisualMode {
  const raw = String(value || '').trim().replace(/-/g, '_')
  if (raw === 'legacy_grid' || raw === 'model_space' || raw === 'modelspace') return 'legacy_grid'
  return DEFAULT_ROUTER_VISUAL_MODE
}
