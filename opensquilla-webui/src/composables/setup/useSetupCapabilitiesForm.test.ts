import { describe, it, expect } from 'vitest'
import { buildImagePayload, parseImageFallbacks } from './useSetupCapabilitiesForm'

// Image generation: size / output_format / fallbacks are honored at runtime but
// were unreachable from the UI. These cover the payload shaping for the new fields.

describe('parseImageFallbacks', () => {
  it('splits on commas and newlines, trims, and drops empties', () => {
    expect(parseImageFallbacks('a/b, c/d\n , e/f')).toEqual(['a/b', 'c/d', 'e/f'])
    expect(parseImageFallbacks('   ')).toEqual([])
  })
})

describe('buildImagePayload — size/format/fallbacks', () => {
  const base = { providerId: 'openrouter', enabled: true, primary: 'openrouter/x', apiKey: '', apiKeyEnv: '', baseUrl: '' }

  it('includes size, outputFormat, and parsed fallbacks', () => {
    const p = buildImagePayload({ ...base, size: '1536x1024', outputFormat: 'webp', fallbacks: 'openai/gpt-image-1, openrouter/y' })
    expect(p.size).toBe('1536x1024')
    expect(p.outputFormat).toBe('webp')
    expect(p.fallbacks).toEqual(['openai/gpt-image-1', 'openrouter/y'])
  })

  it('sends an empty fallbacks array when none entered (backend keeps current)', () => {
    const p = buildImagePayload({ ...base, size: '1024x1024', outputFormat: 'png', fallbacks: '' })
    expect(p.fallbacks).toEqual([])
  })
})
