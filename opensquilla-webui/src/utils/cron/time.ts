export function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm ' + (s % 60) + 's'
  const h = Math.floor(m / 60)
  if (h < 24) return h + 'h ' + (m % 60) + 'm'
  const d = Math.floor(h / 24)
  return d + 'd ' + (h % 24) + 'h'
}

export function humanCountdown(date: Date, now = Date.now()): string {
  const diff = date.getTime() - now
  if (diff < 0) return formatDuration(-diff) + ' ago'
  if (diff < 1000) return 'now'
  return 'in ' + formatDuration(diff)
}

export function humanCountdownPast(date: Date, now = Date.now()): string {
  const diff = now - date.getTime()
  if (diff < 0) return 'in ' + formatDuration(-diff)
  if (diff < 1000) return 'just now'
  return formatDuration(diff) + ' ago'
}

export function humanTime(date: Date): string {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const tomorrow = new Date(today.getTime() + 86400000)
  const dayAfter = new Date(today.getTime() + 2 * 86400000)
  const t = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (date >= today && date < tomorrow) return `today ${t}`
  if (date >= tomorrow && date < dayAfter) return `tomorrow ${t}`
  return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ' ' + t
}

export function relTime(ts: string): string {
  const date = new Date(ts)
  if (isNaN(date.getTime())) return '—'
  return humanCountdownPast(date)
}
