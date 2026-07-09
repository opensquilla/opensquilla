import { describe, expect, it } from 'vitest'

import overviewSource from './OverviewView.vue?raw'
import cliStepsSource from '@/components/overview/AdvancedCliSteps.vue?raw'

describe('health command copy feedback', () => {
  it('the CLI steps component shows visible copy success feedback and reports copy failures', () => {
    expect(cliStepsSource).toContain('health-step__copy--ok')
    expect(cliStepsSource).toContain("t('setup.toast.copiedCommand')")
    expect(cliStepsSource).toContain("pushToast(t('setup.toast.copiedCommand'), { tone: 'ok' })")
    expect(cliStepsSource).toContain("pushToast(t('setup.toast.copyFailed', { error }), { tone: 'danger' })")
    expect(cliStepsSource).not.toContain('Silently ignore copy failures')
  })

  it('the overview keeps toast feedback for its remaining copy paths', () => {
    expect(overviewSource).toContain("pushToast(t('setup.toast.copiedCommand'), { tone: 'ok' })")
    expect(overviewSource).toContain("pushToast(t('setup.toast.copyFailed', { error }), { tone: 'danger' })")
  })
})
