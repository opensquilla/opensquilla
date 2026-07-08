import { describe, it, expect } from 'vitest'
import { filenameFromContentDisposition } from './browser'

describe('filenameFromContentDisposition', () => {
  it('parses a quoted filename', () => {
    expect(
      filenameFromContentDisposition('attachment; filename="opensquilla-bundle-20260708T120000Z.zip"'),
    ).toBe('opensquilla-bundle-20260708T120000Z.zip')
  })

  it('parses an unquoted filename', () => {
    expect(filenameFromContentDisposition('attachment; filename=bundle.zip')).toBe('bundle.zip')
  })

  it('ignores parameters after the filename', () => {
    expect(filenameFromContentDisposition('attachment; filename=bundle.zip; size=42')).toBe(
      'bundle.zip',
    )
  })

  it('prefers the RFC 5987 filename* form and percent-decodes it', () => {
    expect(
      filenameFromContentDisposition(
        `attachment; filename="fallback.zip"; filename*=UTF-8''b%C3%BCndel.zip`,
      ),
    ).toBe('bündel.zip')
  })

  it('falls back to plain filename when filename* is malformed percent-encoding', () => {
    expect(
      filenameFromContentDisposition(`attachment; filename="ok.zip"; filename*=UTF-8''%E0%A4%ZZ`),
    ).toBe('ok.zip')
  })

  it('strips path segments so a hostile header cannot suggest traversal', () => {
    expect(
      filenameFromContentDisposition('attachment; filename="../../etc/passwd"'),
    ).toBe('passwd')
    expect(
      filenameFromContentDisposition('attachment; filename="..\\..\\boot.ini"'),
    ).toBe('boot.ini')
  })

  it('rejects names that reduce to dot segments', () => {
    expect(filenameFromContentDisposition('attachment; filename=".."')).toBeNull()
    expect(filenameFromContentDisposition('attachment; filename="a/.."')).toBeNull()
  })

  it('returns null for a missing or filename-less header', () => {
    expect(filenameFromContentDisposition(null)).toBeNull()
    expect(filenameFromContentDisposition('')).toBeNull()
    expect(filenameFromContentDisposition('attachment')).toBeNull()
    expect(filenameFromContentDisposition('attachment; filename=""')).toBeNull()
  })

  it('is case-insensitive on the parameter name', () => {
    expect(filenameFromContentDisposition('attachment; FILENAME="Bundle.ZIP"')).toBe('Bundle.ZIP')
  })
})
