import { strict as assert } from 'node:assert'

import {
  classifyDesktopOnboardingDataFlow,
  isProvenFreshPrimaryDesktopProfile,
} from '../dist/desktop-data-flow.js'

const freshPrimary = {
  platform: 'win32',
  profileKind: 'primary',
  pendingProviderSetup: false,
  inspection: { outcome: 'ready', stable_code: 'fresh_profile' },
}

assert.equal(isProvenFreshPrimaryDesktopProfile(freshPrimary), true)

for (const candidateKinds of [
  ['windows-portable'],
  ['cli-home', 'windows-portable'],
  ['desktop-home', 'windows-portable'],
]) {
  assert.equal(
    classifyDesktopOnboardingDataFlow({ ...freshPrimary, candidateKinds }),
    'portable-transfer',
  )
}

for (const candidateKinds of [
  [],
  ['cli-home'],
  ['desktop-home'],
  ['cli-home', 'desktop-home'],
]) {
  assert.equal(
    classifyDesktopOnboardingDataFlow({ ...freshPrimary, candidateKinds }),
    'continue-current',
  )
}

for (const platform of ['darwin', 'linux']) {
  assert.equal(classifyDesktopOnboardingDataFlow({
    ...freshPrimary,
    platform,
    candidateKinds: ['windows-portable'],
  }), 'continue-current')
}

for (const inspection of [
  { outcome: 'ready', stable_code: 'canonical_workspace' },
  { outcome: 'ready', stable_code: 'effective_workspace' },
  { outcome: 'attention', stable_code: 'workspace_conflict' },
  { outcome: 'attention', stable_code: 'legacy_workspace_pinned' },
  { outcome: 'recovery_required', stable_code: 'effective_workspace_missing' },
  { outcome: 'ready' },
  { stable_code: 'fresh_profile' },
  null,
]) {
  assert.equal(classifyDesktopOnboardingDataFlow({
    profileKind: 'primary',
    platform: 'win32',
    pendingProviderSetup: false,
    candidateKinds: ['windows-portable'],
    inspection,
  }), 'continue-current')
}

assert.equal(classifyDesktopOnboardingDataFlow({
  ...freshPrimary,
  profileKind: 'recovery',
  candidateKinds: ['windows-portable'],
}), 'continue-current')

assert.equal(classifyDesktopOnboardingDataFlow({
  ...freshPrimary,
  pendingProviderSetup: true,
  candidateKinds: ['windows-portable'],
}), 'continue-current')

console.log(JSON.stringify({
  ok: true,
  windowsFreshProfileOffersPortableTransfer: true,
  cliAndDesktopCandidatesStayInSettings: true,
  nonWindowsOnboardingSuppressesPortableTransfer: true,
  existingProfileContinuesCurrent: true,
  attentionProfileUsesRecoveryFlow: true,
  recoveryProfileImportSuppressed: true,
}))
