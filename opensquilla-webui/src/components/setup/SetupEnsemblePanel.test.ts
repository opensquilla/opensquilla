import { describe, expect, it } from 'vitest'
import source from './SetupEnsemblePanel.vue?raw'

describe('SetupEnsemblePanel contract', () => {
  it('keeps the ensemble Settings panel focused on model membership', () => {
    expect(source).not.toContain('Runs the G8 proposers before the aggregator answers.')
    expect(source).not.toContain('Enable ensemble')
    expect(source).not.toContain('ControlSwitch')
  })

  it('supports dynamic proposer rows with add and remove actions', () => {
    expect(source).toContain('addProposer')
    expect(source).toContain('removeProposer')
    expect(source).toContain('Add proposer')
    expect(source).toContain('row.canRemove')
  })
})
