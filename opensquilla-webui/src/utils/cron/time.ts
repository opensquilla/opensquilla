import i18n from '@/i18n'

// Duration is rendered as compact unit tokens (e.g. "2h 30m"). The unit
// abbreviations are localized, but the structure (number + unit) is kept by
// concatenation since it is largely locale-neutral for these short forms.
export function formatDuration(ms: number): string {
  const t = i18n.global.t
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + t('cronSkills.duration.s')
  const m = Math.floor(s / 60)
  if (m < 60) return m + t('cronSkills.duration.m') + ' ' + (s % 60) + t('cronSkills.duration.s')
  const h = Math.floor(m / 60)
  if (h < 24) return h + t('cronSkills.duration.h') + ' ' + (m % 60) + t('cronSkills.duration.m')
  const d = Math.floor(h / 24)
  return d + t('cronSkills.duration.d') + ' ' + (h % 24) + t('cronSkills.duration.h')
}

export function humanCountdown(date: Date, now = Date.now()): string {
  const t = i18n.global.t
  const diff = date.getTime() - now
  if (diff < 0) return t('cronSkills.time.ago', { duration: formatDuration(-diff) })
  if (diff < 1000) return t('cronSkills.time.now')
  return t('cronSkills.time.in', { duration: formatDuration(diff) })
}

export function humanCountdownPast(date: Date, now = Date.now()): string {
  const t = i18n.global.t
  const diff = now - date.getTime()
  if (diff < 0) return t('cronSkills.time.in', { duration: formatDuration(-diff) })
  if (diff < 1000) return t('cronSkills.time.justNow')
  return t('cronSkills.time.ago', { duration: formatDuration(diff) })
}

export function humanTime(date: Date): string {
  const i18nt = i18n.global.t
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const tomorrow = new Date(today.getTime() + 86400000)
  const dayAfter = new Date(today.getTime() + 2 * 86400000)
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (date >= today && date < tomorrow) return i18nt('cronSkills.time.todayAt', { time })
  if (date >= tomorrow && date < dayAfter) return i18nt('cronSkills.time.tomorrowAt', { time })
  return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ' ' + time
}

export function relTime(ts: string): string {
  const date = new Date(ts)
  if (isNaN(date.getTime())) return '—'
  return humanCountdownPast(date)
}
