import { describe, expect, it } from 'vitest'
import source from './ChatComposerSettings.vue?raw'
import runModeSource from './ChatComposerRunMode.vue?raw'
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
  it('keeps legacy execution mode choices out of the composer settings panel', () => {
    expect(source).not.toContain('chat.composer.executionMode')
    expect(source).not.toContain('composer-execution-mode')
    expect(source).not.toContain('setElevatedMode')
    expect(source).not.toContain('chat.composer.execOff')
    expect(source).not.toContain('chat.composer.execPrompt')
    expect(source).not.toContain('chat.composer.execBypass')
    expect(source).not.toContain('chat.composer.execFull')
  })

  it('threads the shield run-mode control through ChatComposer and ChatView', () => {
    expect(composerSource).toContain('ChatComposerRunMode')
    expect(composerSource).toContain('<Icon name="shield"')
    expect(composerSource).toContain(':run-mode="runMode"')
    expect(composerSource).toContain('@set-run-mode="emit(\'setRunMode\', $event)"')
    expect(composerSource).toContain("setRunMode: [mode: 'standard' | 'trusted' | 'full']")

    expect(viewSource).toContain(':run-mode="runMode"')
    expect(viewSource).toContain('@set-run-mode="setComposerRunMode"')
    expect(viewSource).toContain("const runMode = ref<SandboxRunMode>('trusted')")
    expect(viewSource).toContain('const runModePolicyDefault = computed<SandboxRunMode>')
    expect(viewSource).toContain('defaultRunMode')
    expect(viewSource).toContain('runModeUserSelected')
    expect(viewSource).toContain('function setComposerRunMode(mode: SandboxRunMode)')
  })

  it('offers exactly the three sandbox run modes from the shield popover', () => {
    expect(runModeSource).toContain("value: 'standard'")
    expect(runModeSource).toContain("value: 'trusted'")
    expect(runModeSource).toContain("value: 'full'")
    expect(runModeSource).not.toContain("value: 'on'")
    expect(runModeSource).not.toContain("value: 'bypass'")
  })

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
