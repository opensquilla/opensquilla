import { ref } from 'vue'

import { useToasts } from '@/composables/useToasts'

interface TranscriptionResponse {
  text?: string
  error?: string
}

function authToken(): string {
  try {
    return sessionStorage.getItem('opensquilla.wsToken') || ''
  } catch {
    return ''
  }
}

export function useVoiceInput() {
  const { pushToast } = useToasts()
  const voiceBusy = ref(false)
  const voiceRecording = ref(false)
  let recorder: MediaRecorder | null = null
  let activeStream: MediaStream | null = null
  let chunks: BlobPart[] = []

  async function toggleVoiceInput(onText: (text: string) => void) {
    if (voiceRecording.value) {
      stopRecording()
      return
    }
    await startRecording(onText)
  }

  async function startRecording(onText: (text: string) => void) {
    if (voiceBusy.value || voiceRecording.value) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      pushToast('Voice input is not supported in this browser', { tone: 'danger' })
      return
    }
    voiceBusy.value = true
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      activeStream = stream
      chunks = []
      const mediaRecorder = new MediaRecorder(stream)
      recorder = mediaRecorder
      mediaRecorder.ondataavailable = event => {
        if (event.data && event.data.size > 0) chunks.push(event.data)
      }
      mediaRecorder.onstop = () => {
        const mime = mediaRecorder.mimeType || 'audio/webm'
        void transcribeChunks(mime, onText)
      }
      mediaRecorder.start()
      voiceRecording.value = true
    } catch (err) {
      console.warn('Voice recording failed:', err instanceof Error ? err.message : String(err))
      stopTracks()
    } finally {
      voiceBusy.value = false
    }
  }

  function stopRecording() {
    if (!recorder || recorder.state === 'inactive') {
      voiceRecording.value = false
      stopTracks()
      return
    }
    voiceRecording.value = false
    recorder.stop()
  }

  async function transcribeChunks(mime: string, onText: (text: string) => void) {
    const payload = new Blob(chunks, { type: mime })
    chunks = []
    stopTracks()
    recorder = null
    if (!payload.size) return

    voiceBusy.value = true
    try {
      const form = new FormData()
      form.append('file', payload, 'voice.webm')
      form.append('mime', mime)
      const headers: Record<string, string> = {}
      const token = authToken()
      if (token) headers.Authorization = `Bearer ${token}`
      const response = await fetch('/api/audio/transcribe', {
        method: 'POST',
        headers,
        body: form,
        credentials: 'same-origin',
      })
      const data = (await response.json().catch(() => ({}))) as TranscriptionResponse
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`)
      const text = String(data.text || '').trim()
      if (text) onText(text)
    } catch (err) {
      console.warn('Voice transcription failed:', err instanceof Error ? err.message : String(err))
    } finally {
      voiceBusy.value = false
    }
  }

  function stopTracks() {
    if (!activeStream) return
    activeStream.getTracks().forEach(track => track.stop())
    activeStream = null
  }

  function cleanup() {
    try {
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null
        recorder.stop()
      }
    } catch {}
    voiceRecording.value = false
    stopTracks()
  }

  return {
    voiceBusy,
    voiceRecording,
    toggleVoiceInput,
    cleanup,
  }
}
