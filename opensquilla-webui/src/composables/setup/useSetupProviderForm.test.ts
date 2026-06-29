import { describe, it, expect } from 'vitest'
import { useSetupProviderForm, buildProviderPayload } from './useSetupProviderForm'

describe('buildProviderPayload', () => {
  it('camel-cases keys and drops empty values', () => {
    expect(buildProviderPayload('openrouter', { api_key: 'k', api_key_env: '', model: 'm/x' }))
      .toEqual({ providerId: 'openrouter', apiKey: 'k', model: 'm/x' })
  })
})

// Regression: the gateway rejects a provider save that carries BOTH a pasted
// api_key and an api_key_env reference ("configure either api_key or
// api_key_env, not both"). The env field is frequently pre-filled from a
// detected variable, so the form must keep the two mutually exclusive.
describe('useSetupProviderForm — api_key / api_key_env are mutually exclusive', () => {
  it('pasting an api_key clears a pre-filled api_key_env', () => {
    const f = useSetupProviderForm()
    f.selectProvider('openrouter')
    f.updateField('api_key_env', 'OPENROUTER_API_KEY') // pre-filled from env
    f.updateField('api_key', 'sk-pasted') // user pastes a key
    const p = f.payload()
    expect(p.apiKey).toBe('sk-pasted')
    expect(p.apiKeyEnv).toBeUndefined()
  })

  it('setting api_key_env clears a previously pasted api_key', () => {
    const f = useSetupProviderForm()
    f.selectProvider('openrouter')
    f.updateField('api_key', 'sk-pasted')
    f.updateField('api_key_env', 'OPENROUTER_API_KEY')
    const p = f.payload()
    expect(p.apiKeyEnv).toBe('OPENROUTER_API_KEY')
    expect(p.apiKey).toBeUndefined()
  })

  it('env-only config submits just the env reference', () => {
    const f = useSetupProviderForm()
    f.selectProvider('openrouter')
    f.updateField('api_key_env', 'OPENROUTER_API_KEY')
    const p = f.payload()
    expect(p.apiKeyEnv).toBe('OPENROUTER_API_KEY')
    expect(p.apiKey).toBeUndefined()
  })

  it('a whitespace-only api_key does not count as a credential', () => {
    const f = useSetupProviderForm()
    f.selectProvider('openrouter')
    f.updateField('api_key_env', 'OPENROUTER_API_KEY')
    f.updateField('api_key', '   ')
    const p = f.payload()
    // blank paste must not clear the env reference
    expect(p.apiKeyEnv).toBe('OPENROUTER_API_KEY')
  })
})
