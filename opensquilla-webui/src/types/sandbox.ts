export type SandboxRunMode = 'standard' | 'trusted' | 'full'

export const SANDBOX_RUN_MODES: readonly SandboxRunMode[] = ['standard', 'trusted', 'full']

export function isSandboxRunMode(value: unknown): value is SandboxRunMode {
  return value === 'standard' || value === 'trusted' || value === 'full'
}

export function normalizeSandboxRunMode(value: unknown, fallback: SandboxRunMode = 'trusted'): SandboxRunMode {
  return isSandboxRunMode(value) ? value : fallback
}
