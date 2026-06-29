import { describe, expect, it } from 'vitest'
import source from './useSetupCatalog.ts?raw'

describe('useSetupCatalog ensemble save contract', () => {
  it('saves ensemble settings through the operator.write safe config patch', () => {
    expect(source).toContain("'config.patch.safe'")
    expect(source).toContain('ensembleForm.patches()')
    expect(source).not.toContain('patch: ensembleForm.payload()')
  })
})
