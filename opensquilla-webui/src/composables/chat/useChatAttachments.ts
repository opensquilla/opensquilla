import { ref } from 'vue'
import i18n from '@/i18n'
import { useToasts } from '@/composables/useToasts'
import type { Attachment } from '@/types/chat'

const INLINE_THRESHOLD_BYTES = 2_000_000
const ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES
const ATTACHMENT_IMAGE_HARD_CAP_BYTES = 5 * 1024 * 1024
const ATTACHMENT_PDF_HARD_CAP_BYTES = 30 * 1024 * 1024
const ATTACHMENT_OFFICE_HARD_CAP_BYTES = 30 * 1024 * 1024
const MAX_ATTACHMENTS = 10
const MAX_TOTAL_ATTACHMENT_BYTES = 60 * 1024 * 1024
// Email is held to the text cap (bounded text is extracted; large emails are
// large only due to attachments we never read), so it inlines and never stages.
const ATTACHMENT_EMAIL_HARD_CAP_BYTES = ATTACHMENT_TEXT_HARD_CAP_BYTES

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const EML_MIME = 'message/rfc822'
const MBOX_MIME = 'application/mbox'
const MSG_MIME = 'application/vnd.ms-outlook'

const ATTACHMENT_IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const ATTACHMENT_TEXT_MIMES = ['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json']
const ATTACHMENT_OFFICE_MIMES = [DOCX_MIME, XLSX_MIME, PPTX_MIME]
const ATTACHMENT_EMAIL_MIMES = [EML_MIME, MBOX_MIME, MSG_MIME]
const ATTACHMENT_ALLOWED_MIMES = [...ATTACHMENT_IMAGE_MIMES, 'application/pdf', ...ATTACHMENT_TEXT_MIMES, ...ATTACHMENT_OFFICE_MIMES, ...ATTACHMENT_EMAIL_MIMES]
const ATTACHMENT_EXTENSION_MIMES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown',
  markdown: 'text/markdown', html: 'text/html', htm: 'text/html', csv: 'text/csv', json: 'application/json',
  docx: DOCX_MIME, xlsx: XLSX_MIME, pptx: PPTX_MIME,
  eml: EML_MIME, mbox: MBOX_MIME, msg: MSG_MIME,
}

function isAllowedAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_ALLOWED_MIMES.includes(mime)
}

function isImageAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_IMAGE_MIMES.includes(mime)
}

function canStageAttachmentMime(mime: string): boolean {
  // Email is capped at the text limit, so it inlines and is never staged.
  return (
    mime === 'application/pdf' ||
    isImageAttachmentMime(mime) ||
    ATTACHMENT_OFFICE_MIMES.includes(mime)
  )
}

function attachmentHardCapBytes(mime: string): number {
  if (mime === 'application/pdf') return ATTACHMENT_PDF_HARD_CAP_BYTES
  if (isImageAttachmentMime(mime)) return ATTACHMENT_IMAGE_HARD_CAP_BYTES
  if (ATTACHMENT_OFFICE_MIMES.includes(mime)) return ATTACHMENT_OFFICE_HARD_CAP_BYTES
  if (ATTACHMENT_EMAIL_MIMES.includes(mime)) return ATTACHMENT_EMAIL_HARD_CAP_BYTES
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

// Unknown-but-textual uploads degrade to text/plain so the gateway's UTF-8
// fallback is reachable from the WebUI (the gateway re-validates). Bounded to
// the text cap range; binary (NUL byte / invalid UTF-8) stays rejected.
const TEXT_FALLBACK_MAX_SNIFF_BYTES = 4_000_000
async function fileLooksLikeUtf8Text(file: File): Promise<boolean> {
  if (file.size === 0 || file.size > TEXT_FALLBACK_MAX_SNIFF_BYTES) return false
  try {
    const bytes = new Uint8Array(await file.arrayBuffer())
    if (bytes.includes(0)) return false
    new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return true
  } catch {
    return false
  }
}

export function useChatAttachments() {
  const { pushToast } = useToasts()
  const pendingAttachments = ref<Attachment[]>([])
  const nextAttachmentId = ref(1)

  function onFileInputChange(e: Event) {
    const target = e.target as HTMLInputElement
    if (target.files) {
      void addAttachments(Array.from(target.files))
      target.value = ''
    }
  }

  async function addAttachments(files: File[]) {
    for (const file of files) {
      await addAttachmentFile(file)
    }
  }

  async function addAttachment(file: File) {
    await addAttachments([file])
  }

  async function addAttachmentFile(file: File) {
    const fileName = file.name || 'Untitled file'
    if (file.size === 0) {
      pushToast(`Empty file: ${fileName}`, { tone: 'danger' })
      return
    }

    let mime = resolveAttachmentMime(file)
    if (!isAllowedAttachmentMime(mime)) {
      if (await fileLooksLikeUtf8Text(file)) {
        mime = 'text/plain'
      } else {
        pushToast(i18n.global.t('chat.toast.unsupportedFile', { name: fileName, mime }), { tone: 'danger' })
        return
      }
    }
    const hardCap = attachmentHardCapBytes(mime)
    if (file.size > hardCap) {
      pushToast(i18n.global.t('chat.toast.fileTooLarge', { name: fileName }), { tone: 'danger' })
      return
    }
    if (!canAcceptAttachment(fileName, file.size)) return

    const localId = nextAttachmentId.value++

    if (file.size <= INLINE_THRESHOLD_BYTES) {
      pendingAttachments.value.push({ kind: 'inline_pending', local_id: localId, name: fileName, mime, size: file.size, file })
      const reader = new FileReader()
      reader.onload = (e) => {
        const dataUrl = e.target?.result as string
        const b64 = dataUrl?.split(',')[1] || ''
        const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
        if (idx >= 0) {
          pendingAttachments.value[idx] = { kind: 'inline', local_id: localId, name: fileName, mime, size: file.size, data: b64, dataUrl }
        }
      }
      reader.onerror = () => {
        const message = i18n.global.t('chat.toast.couldNotReadFile', { name: fileName })
        markAttachmentFailed(localId, file, mime, message)
        pushToast(message, { tone: 'danger' })
      }
      reader.readAsDataURL(file)
      return
    }

    if (!canStageAttachmentMime(mime)) {
      pushToast(i18n.global.t('chat.toast.fileTooLarge', { name: fileName }), { tone: 'danger' })
      return
    }

    pendingAttachments.value.push({ kind: 'uploading', local_id: localId, name: fileName, mime, size: file.size, file })
    uploadAttachmentStaged(file, mime, localId).catch((err) => {
      const message = uploadFailureMessage(err)
      markAttachmentFailed(localId, file, mime, message)
      pushToast(`${i18n.global.t('chat.toast.uploadFailed', { name: fileName })}: ${message}`, { tone: 'danger' })
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
      headers: uploadAuthHeaders(),
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(`HTTP ${response.status} ${detail}`)
    }
    const result = await response.json()
    const fileUuid = uploadResponseFileUuid(result)
    const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
    if (idx >= 0) {
      pendingAttachments.value[idx] = { kind: 'staged', local_id: localId, name: file.name || 'Untitled file', mime, size: file.size, file_uuid: fileUuid }
    }
  }

  function removeAttachment(index: number) {
    pendingAttachments.value.splice(index, 1)
  }

  async function retryAttachment(index: number) {
    const attachment = pendingAttachments.value[index]
    if (!attachment || attachment.kind !== 'failed') return
    if (!attachment.file) {
      pushToast(`Cannot retry ${attachment.name}: select the file again`, { tone: 'danger' })
      return
    }
    pendingAttachments.value.splice(index, 1)
    await addAttachment(attachment.file)
  }

  function markAttachmentFailed(localId: number, file: File, mime: string, error: string) {
    const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
    if (idx >= 0) {
      pendingAttachments.value[idx] = {
        kind: 'failed',
        local_id: localId,
        name: file.name || 'Untitled file',
        mime,
        size: file.size,
        error,
        file,
      }
    }
  }

  function hasPendingAttachmentWork(): boolean {
    return pendingAttachments.value.some(a => a.kind === 'inline_pending' || a.kind === 'uploading')
  }

  function canAcceptAttachment(fileName: string, size: number): boolean {
    const activeAttachments = pendingAttachments.value.filter(attachmentCountsTowardLimits)
    if (activeAttachments.length >= MAX_ATTACHMENTS) {
      pushToast(`Too many attachments: max ${MAX_ATTACHMENTS}`, { tone: 'danger' })
      return false
    }
    const totalBytes = activeAttachments.reduce((sum, attachment) => sum + (attachment.size || 0), 0) + size
    if (totalBytes > MAX_TOTAL_ATTACHMENT_BYTES) {
      pushToast(`Attachments too large: ${fileName} would exceed ${formatMiB(MAX_TOTAL_ATTACHMENT_BYTES)} total`, { tone: 'danger' })
      return false
    }
    return true
  }

  return {
    pendingAttachments,
    onFileInputChange,
    addAttachments,
    addAttachment,
    removeAttachment,
    retryAttachment,
    hasPendingAttachmentWork,
  }
}

function uploadAuthHeaders(): HeadersInit | undefined {
  try {
    const token = globalThis.sessionStorage?.getItem('opensquilla.wsToken')?.trim()
    return token ? { Authorization: `Bearer ${token}` } : undefined
  } catch {
    return undefined
  }
}

function uploadFailureMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

function uploadResponseFileUuid(result: unknown): string {
  const fileUuid = typeof (result as { file_uuid?: unknown } | null)?.file_uuid === 'string'
    ? (result as { file_uuid: string }).file_uuid.trim()
    : ''
  if (!fileUuid) throw new Error('Upload response missing file_uuid')
  return fileUuid
}

function attachmentCountsTowardLimits(attachment: Attachment): boolean {
  return attachment.kind !== 'failed'
}

function formatMiB(bytes: number): string {
  return `${Math.round(bytes / 1024 / 1024)} MiB`
}
