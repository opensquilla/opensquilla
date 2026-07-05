import { describe, expect, it } from 'vitest'

import source from './OverviewView.vue?raw'

describe('OverviewView health command copy feedback', () => {
  it('shows visible copy success feedback and reports copy failures', () => {
    expect(source).toContain('health-step__copy--ok')
    expect(source).toContain("t('setup.toast.copiedCommand')")
    expect(source).toContain("pushToast(t('setup.toast.copiedCommand'), { tone: 'ok' })")
    expect(source).toContain("pushToast(t('setup.toast.copyFailed', { error }), { tone: 'danger' })")
    expect(source).not.toContain('Silently ignore copy failures')
  })
})
