export type DesktopOnboardingDataFlow = 'portable-transfer' | 'continue-current'

export type DesktopOnboardingCandidateKind =
  | 'cli-home'
  | 'desktop-home'
  | 'windows-portable'

export interface DesktopProfileInspectionLike {
  outcome?: unknown
  stable_code?: unknown
}

export interface DesktopOnboardingDataFlowInput {
  platform: NodeJS.Platform
  profileKind: 'primary' | 'recovery'
  pendingProviderSetup: boolean
  candidateKinds: readonly DesktopOnboardingCandidateKind[]
  inspection: DesktopProfileInspectionLike | null
}

export function isProvenFreshPrimaryDesktopProfile(
  input: Pick<DesktopOnboardingDataFlowInput, 'profileKind' | 'pendingProviderSetup' | 'inspection'>,
): boolean {
  return input.profileKind === 'primary'
    && !input.pendingProviderSetup
    && input.inspection?.outcome === 'ready'
    && input.inspection.stable_code === 'fresh_profile'
}

/**
 * Decide whether the Windows Portable transfer belongs in first-run onboarding.
 *
 * The transfer step is only safe and useful on Windows when the recovery
 * engine has proved the Desktop profile empty and a Portable source exists.
 * CLI homes and other Desktop profiles remain explicit Settings actions.
 */
export function classifyDesktopOnboardingDataFlow(
  input: DesktopOnboardingDataFlowInput,
): DesktopOnboardingDataFlow {
  if (
    input.platform === 'win32'
    && isProvenFreshPrimaryDesktopProfile(input)
    && input.candidateKinds.includes('windows-portable')
  ) {
    return 'portable-transfer'
  }
  return 'continue-current'
}
