export type SecretStorageBackend = 'safeStorage' | 'plain'

export interface SecretStoragePolicyInput {
  envMode?: string
  platform: NodeJS.Platform
  appPackaged: boolean
  codesignDiagnostic?: string
}

export function macCodeSignatureIsAdHoc(diagnostic: string): boolean {
  return /\bSignature=adhoc\b/.test(diagnostic) || /\bflags=[^\n]*\badhoc\b/.test(diagnostic)
}

export function secretStorageBackendForPolicy(input: SecretStoragePolicyInput): SecretStorageBackend {
  const mode = (input.envMode || '').trim().toLowerCase()
  if (mode === 'plain' || mode === 'plaintext' || mode === 'none') return 'plain'
  if (mode === 'safe' || mode === 'safe-storage' || mode === 'safestorage') return 'safeStorage'

  if (input.platform === 'darwin' && input.appPackaged && macCodeSignatureIsAdHoc(input.codesignDiagnostic || '')) {
    return 'plain'
  }

  return 'safeStorage'
}

export function shouldUseChromiumMockKeychainForPolicy(input: SecretStoragePolicyInput): boolean {
  return input.platform === 'darwin' &&
    input.appPackaged &&
    secretStorageBackendForPolicy(input) === 'plain'
}
