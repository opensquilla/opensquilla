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

describe('ChatComposerSettings LLM Ensemble contract', () => {
  it('places LLM Ensemble immediately after Coding mode', () => {
    const codingModeIndex = source.indexOf('label="Coding mode"')
    const ensembleIndex = source.indexOf('label="LLM Ensemble"')

    expect(codingModeIndex).toBeGreaterThanOrEqual(0)
    expect(ensembleIndex).toBeGreaterThan(codingModeIndex)
  })

  it('binds LLM Ensemble checked and busy state to typed props', () => {
    const block = controlSwitchBlock('LLM Ensemble')

    expect(block).toContain(':checked="llmEnsembleEnabled"')
    expect(block).toContain(':busy="llmEnsembleSettingsBusy"')
    expect(source).toContain('llmEnsembleEnabled: boolean')
    expect(source).toContain('llmEnsembleSettingsBusy: boolean')
  })

  it('emits LLM Ensemble changes through the typed settings event', () => {
    const block = controlSwitchBlock('LLM Ensemble')

    expect(block).toContain('@change="$emit(\'setLlmEnsembleEnabled\', $event)"')
    expect(source).toContain('setLlmEnsembleEnabled: [enabled: boolean]')
  })

  it('threads LLM Ensemble props and events through ChatComposer and ChatView', () => {
    expect(composerSource).toContain(':llm-ensemble-enabled="llmEnsembleEnabled"')
    expect(composerSource).toContain(':llm-ensemble-settings-busy="llmEnsembleSettingsBusy"')
    expect(composerSource).toContain('@set-llm-ensemble-enabled="emit(\'setLlmEnsembleEnabled\', $event)"')
    expect(composerSource).toContain('setLlmEnsembleEnabled: [enabled: boolean]')

    expect(viewSource).toContain(':llm-ensemble-enabled="llmEnsembleEnabled"')
    expect(viewSource).toContain(':llm-ensemble-settings-busy="llmEnsembleSettingsBusy"')
    expect(viewSource).toContain('@set-llm-ensemble-enabled="setComposerLlmEnsembleEnabled"')
    expect(viewSource).toContain('async function setComposerLlmEnsembleEnabled(enabled: boolean)')
    expect(viewSource).toContain('await setLlmEnsembleEnabled(enabled)')
  })
})
