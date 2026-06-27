import { describe, expect, it } from 'vitest'

import {
  completeRun,
  counterText,
  createRibbon,
  progressPercent,
  ribbonCopy,
} from './metaRibbon'

describe('metaRibbon completed progress', () => {
  it('shows a completed run as total of total even when optional steps never emitted terminal states', () => {
    const ribbon = createRibbon({
      run_id: 'run-1',
      meta_skill_name: 'meta-kid-project-planner',
      language: 'en',
      total: 4,
      steps: [
        { id: 'a', label: 'A', kind: 'llm_chat', depends_on: [] },
        { id: 'b', label: 'B', kind: 'llm_chat', depends_on: [] },
        { id: 'optional_c', label: 'Optional C', kind: 'llm_chat', depends_on: [] },
        { id: 'optional_d', label: 'Optional D', kind: 'llm_chat', depends_on: [] },
      ],
    })

    completeRun(ribbon, {
      run_id: 'run-1',
      outcome: 'ok',
      completed_steps: ['a', 'b'],
      failed_steps: [],
      recovered_steps: [],
      skipped_steps: [],
    })

    expect(progressPercent(ribbon)).toBe(100)
    expect(counterText(ribbon, ribbonCopy('en'))).toBe('Step 4 of 4')
  })
})
