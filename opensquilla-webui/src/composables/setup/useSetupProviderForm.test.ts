import { describe, it, expect } from 'vitest'
import { useSetupProviderForm, buildProviderPayload, hasEffectiveProvider } from './useSetupProviderForm'

describe('buildProviderPayload', () => {
  it('camel-cases keys and drops empty values', () => {
    expect(buildProviderPayload('openrouter', { api_key: 'k', api_key_env: '', model: 'm/x' }))
      .toEqual({ providerId: 'openrouter', apiKey: 'k', model: 'm/x' })
  })
})

describe('hasEffectiveProvider', () => {
  it('accepts runtime env-backed providers even before a config file is persisted', () => {
    expect(hasEffectiveProvider(
      { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro' },
      { hasConfig: false, llmConfigured: true, llmSource: 'env' },
    )).toBe(true)
  })

  it('does not accept a missing env key as a usable provider', () => {
    expect(hasEffectiveProvider(
      { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro' },
      { hasConfig: false, llmConfigured: false, llmSource: 'missing_env' },
    )).toBe(false)
  })

  it('treats llmConfigured=false as authoritative even with an env source', () => {
    expect(hasEffectiveProvider(
      { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro' },
      { hasConfig: false, llmConfigured: false, llmSource: 'env' },
    )).toBe(false)
  })
})

// Regression: the gateway rejects a provider save that carries BOTH a pasted
// api_key and an api_key_env reference ("configure either api_key or
// api_key_env, not both"). The env field is frequently pre-filled from a
// detected variable, so the form must keep the two mutually exclusive.
describe('useSetupProviderForm — runtime provider hydration', () => {
  it('hydrates the selected provider from env-backed runtime config', () => {
    const f = useSetupProviderForm()
    f.initFromConfig(
      { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro', api_key_env: 'OPENROUTER_API_KEY' },
      { hasConfig: false, llmConfigured: true, llmSource: 'env' },
      [{ providerId: 'openrouter', fields: [{ name: 'model', label: 'Model' }] }],
    )

    expect(f.selectedProvider.value).toBe('openrouter')
  })
})

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
