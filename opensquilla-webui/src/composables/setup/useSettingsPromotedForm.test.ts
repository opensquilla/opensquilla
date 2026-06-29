import { describe, it, expect } from 'vitest'
import { useSettingsPromotedForm } from './useSettingsPromotedForm'

// The audio TTS tuning fields (voice/model/base_url/language_code) are accepted
// and applied by the backend (mutations.upsert_audio_provider); these cover the
// UI round-trip: read from config, mark dirty on edit, send only populated fields.

describe('useSettingsPromotedForm — audio TTS fields', () => {
  it('reads tts voice/model/language_code and provider base_url from config', () => {
    const f = useSettingsPromotedForm()
    f.initFromConfig({
      audio: {
        enabled: true,
        tts: { voice: 'voice-x', model: 'model-y', language_code: 'en-US' },
        providers: { elevenlabs: { api_key_env: 'ELEVENLABS_API_KEY', base_url: 'https://api.example.com', api_key: 'redacted' } },
      },
    })
    expect(f.audioTtsVoice.value).toBe('voice-x')
    expect(f.audioTtsModel.value).toBe('model-y')
    expect(f.audioLanguageCode.value).toBe('en-US')
    expect(f.audioBaseUrl.value).toBe('https://api.example.com')
    expect(f.audioDirty.value).toBe(false) // pristine after load
  })

  it('marks dirty and includes only populated tuning fields in the payload', () => {
    const f = useSettingsPromotedForm()
    f.initFromConfig({ audio: { enabled: true, providers: { elevenlabs: {} } } })
    expect(f.audioDirty.value).toBe(false)
    f.updateAudioField('ttsVoice', 'rachel')
    f.updateAudioField('languageCode', 'zh-CN')
    expect(f.audioDirty.value).toBe(true)
    const p = f.audioPayload()
    expect(p.providerId).toBe('elevenlabs')
    expect(p.enabled).toBe(true)
    expect(p.ttsVoice).toBe('rachel')
    expect(p.languageCode).toBe('zh-CN')
    expect('ttsModel' in p).toBe(false) // empty → omitted (backend keeps current)
    expect('baseUrl' in p).toBe(false)
  })

  it('omits whitespace-only tuning fields from the payload', () => {
    const f = useSettingsPromotedForm()
    f.initFromConfig({ audio: { enabled: true, providers: { elevenlabs: {} } } })
    f.updateAudioField('ttsModel', '   ')
    expect('ttsModel' in f.audioPayload()).toBe(false)
  })
})
