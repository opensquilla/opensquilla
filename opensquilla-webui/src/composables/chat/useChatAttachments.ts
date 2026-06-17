import { ref } from 'vue'
import type { Attachment } from '@/types/chat'

const INLINE_THRESHOLD_BYTES = 2_000_000
const ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES
const ATTACHMENT_IMAGE_HARD_CAP_BYTES = 5 * 1024 * 1024
const ATTACHMENT_PDF_HARD_CAP_BYTES = 30 * 1024 * 1024

const ATTACHMENT_IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const ATTACHMENT_TEXT_MIMES = ['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json']
const ATTACHMENT_ALLOWED_MIMES = [...ATTACHMENT_IMAGE_MIMES, 'application/pdf', ...ATTACHMENT_TEXT_MIMES]
const ATTACHMENT_EXTENSION_MIMES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown',
  markdown: 'text/markdown', html: 'text/html', htm: 'text/html', csv: 'text/csv', json: 'application/json',
}

function isAllowedAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_ALLOWED_MIMES.includes(mime)
}

function isImageAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_IMAGE_MIMES.includes(mime)
}

function canStageAttachmentMime(mime: string): boolean {
  return mime === 'application/pdf' || isImageAttachmentMime(mime)
}

function attachmentHardCapBytes(mime: string): number {
  if (mime === 'application/pdf') return ATTACHMENT_PDF_HARD_CAP_BYTES
  if (isImageAttachmentMime(mime)) return ATTACHMENT_IMAGE_HARD_CAP_BYTES
  if (['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json'].includes(mime)) return ATTACHMENT_TEXT_HARD_CAP_BYTES
  return ATTACHMENT_IMAGE_HARD_CAP_BYTES
}

function resolveAttachmentMime(file: File): string {
  const name = file.name || ''
  const ext = name.includes('.') ? name.split('.').pop()?.toLowerCase() || '' : ''
  const extensionMime = ATTACHMENT_EXTENSION_MIMES[ext]
  if (file.type && isAllowedAttachmentMime(file.type)) return file.type
  return extensionMime || file.type || 'application/octet-stream'
}

export function useChatAttachments() {
  const pendingAttachments = ref<Attachment[]>([])
  const nextAttachmentId = ref(1)

  function onFileInputChange(e: Event) {
    const target = e.target as HTMLInputElement
    if (target.files) {
      Array.from(target.files).forEach(addAttachment)
      target.value = ''
    }
  }

  function addAttachment(file: File) {
    const mime = resolveAttachmentMime(file)
    if (!isAllowedAttachmentMime(mime)) {
      console.warn(`Unsupported file: ${file.name} (${mime})`)
      return
    }
    const hardCap = attachmentHardCapBytes(mime)
    if (file.size > hardCap) {
      console.warn(`File too large: ${file.name}`)
      return
    }

    const localId = nextAttachmentId.value++

    if (file.size <= INLINE_THRESHOLD_BYTES) {
      pendingAttachments.value.push({ kind: 'inline_pending', local_id: localId, name: file.name, mime, size: file.size })
      const reader = new FileReader()
      reader.onload = (e) => {
        const dataUrl = e.target?.result as string
        const b64 = dataUrl?.split(',')[1] || ''
        const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
        if (idx >= 0) {
          pendingAttachments.value[idx] = { kind: 'inline', local_id: localId, name: file.name, mime, size: file.size, data: b64, dataUrl }
        }
      }
      reader.onerror = () => {
        removeAttachmentByLocalId(localId)
        console.warn(`Could not read file: ${file.name}`)
      }
      reader.readAsDataURL(file)
      return
    }

    if (!canStageAttachmentMime(mime)) {
      console.warn(`File too large: ${file.name}`)
      return
    }

    pendingAttachments.value.push({ kind: 'uploading', local_id: localId, name: file.name, mime, size: file.size })
    uploadAttachmentStaged(file, mime, localId).catch((err) => {
      removeAttachmentByLocalId(localId)
      console.warn(`Upload failed for ${file.name}:`, err?.message || err)
    })
  }

  async function uploadAttachmentStaged(file: File, mime: string, localId: number) {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('mime', mime)
    const response = await fetch('/api/v1/files/upload', {
      method: 'POST',
      body: form,
      credentials: 'same-origin',
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(`HTTP ${response.status} ${detail}`)
    }
    const result = await response.json()
    const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
    if (idx >= 0) {
      pendingAttachments.value[idx] = { kind: 'staged', local_id: localId, name: file.name, mime, size: file.size, file_uuid: result.file_uuid }
    }
  }

  function removeAttachment(index: number) {
    pendingAttachments.value.splice(index, 1)
  }

  function removeAttachmentByLocalId(localId: number) {
    pendingAttachments.value = pendingAttachments.value.filter(a => a.local_id !== localId)
  }

  function hasPendingAttachmentWork(): boolean {
    return pendingAttachments.value.some(a => a.kind === 'inline_pending' || a.kind === 'uploading')
  }

  return {
    pendingAttachments,
    onFileInputChange,
    addAttachment,
    removeAttachment,
    hasPendingAttachmentWork,
  }
}
