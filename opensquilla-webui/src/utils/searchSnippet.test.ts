import { describe, it, expect } from 'vitest'
import { highlightFtsSnippet } from './searchSnippet'

describe('highlightFtsSnippet', () => {
  it('wraps the FTS >>> / <<< delimiters in a mark span', () => {
    expect(highlightFtsSnippet('the >>>deploy<<< failed')).toBe(
      'the <mark class="cmdp-mark">deploy</mark> failed',
    )
  })

  it('escapes HTML in the snippet body so it cannot inject markup', () => {
    const out = highlightFtsSnippet('<script>alert(1)</script> >>>hit<<<')
    expect(out).not.toContain('<script>')
    expect(out).toContain('&lt;script&gt;')
    expect(out).toContain('<mark class="cmdp-mark">hit</mark>')
  })

  it('escapes ampersands before delimiter substitution', () => {
    expect(highlightFtsSnippet('a & b')).toBe('a &amp; b')
  })

  it('handles an empty snippet', () => {
    expect(highlightFtsSnippet('')).toBe('')
  })
})
