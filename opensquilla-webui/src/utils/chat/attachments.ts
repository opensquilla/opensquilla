import type { Attachment, DisplayAttachment } from '@/types/chat'
import type { ChatHistoryAttachmentPayload, ChatSendAttachmentPayload } from '@/types/rpc'

export type SendableAttachment = Attachment & (
  | { kind: 'inline'; data: string }
  | { kind: 'staged'; file_uuid: string }
)

export function isAttachmentBusy(attachment: Attachment): boolean {
  return attachment.kind === 'inline_pending' || attachment.kind === 'uploading'
}

export function isMimeLike(value: unknown): value is string {
  return typeof value === 'string' && /^[^/\s]+\/[^/\s;]+(?:\s*;.*)?$/.test(value.trim())
}

export function normalizeAttachmentMimeValue(value: unknown, fallback = 'application/octet-stream'): string {
  return isMimeLike(value) ? value.trim().toLowerCase() : fallback
}

export function displayAttachmentMime(attachment: Record<string, unknown>): string {
  for (const key of ['mime', 'mime_type', 'media_type', 'type']) {
    const value = attachment[key]
    if (isMimeLike(value)) return value.trim().toLowerCase()
  }
  return 'application/octet-stream'
}

export function isImageAttachmentMime(mime: unknown): boolean {
  return normalizeAttachmentMimeValue(mime, '').startsWith('image/')
}

export function isImageDisplayAttachment(attachment: Pick<DisplayAttachment, 'mime'> | Pick<Attachment, 'mime'>): boolean {
  return isImageAttachmentMime(attachment.mime)
}

export function isSendableAttachment(attachment: Attachment): attachment is SendableAttachment {
  if (attachment.kind === 'inline') return Boolean(attachment.data)
  if (attachment.kind === 'staged') return Boolean(attachment.file_uuid)
  return false
}

export function serializeSendableAttachment(attachment: SendableAttachment): ChatSendAttachmentPayload {
  if (attachment.kind === 'staged') {
    return {
      type: attachment.mime,
      file_uuid: attachment.file_uuid,
      mime: attachment.mime,
      name: attachment.name,
    }
  }
  return {
    type: attachment.mime || 'image/png',
    data: attachment.data,
    mime: attachment.mime,
    name: attachment.name,
  }
}

export function serializeDisplayAttachment(attachment: SendableAttachment): DisplayAttachment {
  const displayId = `local:${attachment.local_id}`
  const base = {
    displayId,
    renderKey: displayId,
    name: attachment.name,
    mime: attachment.mime,
    size: attachment.size,
  }
  if (attachment.kind === 'staged') {
    return { ...base, kind: 'staged' }
  }
  const isImage = isImageDisplayAttachment(attachment)
  return {
    ...base,
    kind: 'inline',
    data: isImage ? attachment.data : undefined,
    dataUrl: isImage ? attachment.dataUrl : undefined,
  }
}

export function normalizeDisplayAttachment(
  raw: Attachment | DisplayAttachment | ChatHistoryAttachmentPayload,
  options: { messageId?: string, index?: number } = {},
): DisplayAttachment {
  const record = raw as Record<string, unknown>
  const mime = displayAttachmentMime(record)
  const image = isImageAttachmentMime(mime)
  const name = typeof record.name === 'string' && record.name.trim()
    ? record.name.trim()
    : typeof record.filename === 'string' && record.filename.trim()
      ? record.filename.trim()
      : 'attachment'
  const sha = typeof record.sha256_ref === 'string' && record.sha256_ref.trim()
    ? record.sha256_ref.trim()
    : ''
  const existingDisplayId = typeof record.displayId === 'string' && record.displayId.trim()
    ? record.displayId.trim()
    : ''
  const localId = typeof record.local_id === 'number' && Number.isFinite(record.local_id)
    ? `local:${record.local_id}`
    : ''
  const index = typeof options.index === 'number' ? options.index : 0
  const messagePart = options.messageId || 'history'
  const displayId = existingDisplayId || localId || (sha ? `sha:${sha}:${index}` : `${messagePart}:att:${index}`)
  const size = typeof record.size === 'number' && Number.isFinite(record.size)
    ? record.size
    : typeof record.size === 'string' && Number.isFinite(Number(record.size))
      ? Number(record.size)
      : undefined
  const data = typeof record.data === 'string' ? record.data : undefined
  const dataUrl = typeof record.dataUrl === 'string'
    ? record.dataUrl
    : typeof record.data_url === 'string'
      ? record.data_url
      : undefined
  const rawKind = typeof record.kind === 'string' ? record.kind : ''
  const kind: DisplayAttachment['kind'] = rawKind === 'staged' || sha
    ? 'staged'
    : rawKind === 'inline' || data || dataUrl
      ? 'inline'
      : 'file'

  return {
    kind,
    displayId,
    renderKey: typeof record.renderKey === 'string' && record.renderKey.trim()
      ? record.renderKey.trim()
      : displayId,
    name,
    mime,
    size,
    data: image ? data : undefined,
    dataUrl: image ? dataUrl : undefined,
    download_url: typeof record.download_url === 'string' ? record.download_url : undefined,
    sha256_ref: sha || undefined,
  }
}

export function normalizeDisplayAttachments(
  attachments: Array<Attachment | DisplayAttachment | ChatHistoryAttachmentPayload> | undefined,
  options: { messageId?: string } = {},
): DisplayAttachment[] {
  return (attachments || []).map((attachment, index) =>
    normalizeDisplayAttachment(attachment, { messageId: options.messageId, index }),
  )
}
