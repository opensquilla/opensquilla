import { describe, expect, it } from 'vitest'
import source from './ChatComposerSettings.vue?raw'
import composerSource from './ChatComposer.vue?raw'
import viewSource from '../../views/ChatView.vue?raw'

function controlSwitchBlock(label: string) {
  const labelIndex = source.indexOf(`label="${label}"`)
  if (labelIndex === -1) return ''
  const start = source.lastIndexOf('<ControlSwitch', labelIndex)
  const end = source.indexOf('/>', labelIndex)
  return source.slice(start, end)
}

describe('ChatComposerSettings coding mode contract', () => {
  it('places Coding mode after Visual effects', () => {
    const visualEffectsIndex = source.indexOf('label="Visual effects"')
    const codingModeIndex = source.indexOf('label="Coding mode"')

    expect(visualEffectsIndex).toBeGreaterThanOrEqual(0)
    expect(codingModeIndex).toBeGreaterThan(visualEffectsIndex)
  })

  it('binds Coding mode checked and busy state to typed props', () => {
    const block = controlSwitchBlock('Coding mode')

    expect(block).toContain(':checked="codingModeEnabled"')
    expect(block).toContain(':busy="codingModeSettingsBusy"')
    expect(source).toContain('codingModeEnabled: boolean')
    expect(source).toContain('codingModeSettingsBusy: boolean')
  })

  it('emits Coding mode changes through the typed settings event', () => {
    const block = controlSwitchBlock('Coding mode')

    expect(block).toContain('@change="$emit(\'setCodingModeEnabled\', $event)"')
    expect(source).toContain('setCodingModeEnabled: [enabled: boolean]')
  })

  it('threads Coding mode props and events through ChatComposer and ChatView', () => {
    expect(composerSource).toContain(':coding-mode-enabled="codingModeEnabled"')
    expect(composerSource).toContain(':coding-mode-settings-busy="codingModeSettingsBusy"')
    expect(composerSource).toContain('@set-coding-mode-enabled="emit(\'setCodingModeEnabled\', $event)"')
    expect(composerSource).toContain('setCodingModeEnabled: [enabled: boolean]')

    expect(viewSource).toContain(':coding-mode-enabled="codingModeEnabled"')
    expect(viewSource).toContain(':coding-mode-settings-busy="codingModeSettingsBusy"')
    expect(viewSource).toContain('@set-coding-mode-enabled="setComposerCodingModeEnabled"')
    expect(viewSource).toContain('async function setComposerCodingModeEnabled(enabled: boolean)')
    expect(viewSource).toContain('await setCodingModeEnabled(enabled)')
  })
})
