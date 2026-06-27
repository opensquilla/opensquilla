interface ParsedField {
  all: boolean
  set?: Set<number>
}

export interface ParsedCron {
  minute: ParsedField
  hour: ParsedField
  dom: ParsedField
  month: ParsedField
  dow: ParsedField
  raw: string
}

export function parseCron(expr: string): ParsedCron | null {
  if (!expr) return null
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const monthNames: Record<string, number> = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 }
  const dowNames: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 }
  try {
    const minute = parseField(parts[0], 0, 59)
    const hour = parseField(parts[1], 0, 23)
    const dom = parseField(parts[2], 1, 31)
    const month = parseField(parts[3], 1, 12, monthNames)
    const dow = parseField(parts[4], 0, 7, dowNames)
    if (!dow.all && dow.set?.has(7)) {
      dow.set.delete(7)
      dow.set.add(0)
    }
    return { minute, hour, dom, month, dow, raw: expr }
  } catch {
    return null
  }
}

export function nextRuns(parsed: ParsedCron, count: number, fromTs = Date.now()): Date[] {
  const results: Date[] = []
  const start = new Date(fromTs)
  start.setSeconds(0, 0)
  start.setMinutes(start.getMinutes() + 1)
  let d = new Date(start)
  const endLimit = fromTs + 365 * 24 * 3600 * 1000
  while (results.length < count && d.getTime() < endLimit) {
    const m = d.getMinutes()
    const h = d.getHours()
    const dom = d.getDate()
    const mon = d.getMonth() + 1
    const dow = d.getDay()
    const dayOk = parsed.dom.all && parsed.dow.all
      ? true
      : parsed.dom.all
        ? matches(parsed.dow, dow)
        : parsed.dow.all
          ? matches(parsed.dom, dom)
          : matches(parsed.dom, dom) || matches(parsed.dow, dow)
    if (
      matches(parsed.minute, m) &&
      matches(parsed.hour, h) &&
      matches(parsed.month, mon) &&
      dayOk
    ) {
      results.push(new Date(d))
    }
    d = new Date(d.getTime() + 60_000)
  }
  return results
}

export function explainCron(expr: string): string {
  const p = parseCron(expr)
  if (!p) return ''
  const dowNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const monNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  if (p.minute.all && p.hour.all) return 'Every minute'
  if (!p.minute.all && p.minute.set!.size === 1 && p.hour.all) {
    return `Every hour at :${String([...p.minute.set!][0]).padStart(2, '0')}`
  }
  if (!p.minute.all && p.minute.set!.size === 1 && !p.hour.all && p.hour.set!.size === 1) {
    const m = [...p.minute.set!][0]
    const h = [...p.hour.set!][0]
    const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
    if (p.dom.all && p.dow.all && p.month.all) return `Every day at ${time}`
    if (!p.dow.all && p.dom.all && p.month.all) {
      const days = [...p.dow.set!].sort((a, b) => a - b).map(v => dowNames[v])
      if (days.length === 5 && days[0] === 'Mon' && days[4] === 'Fri') return `Weekdays at ${time}`
      if (days.length === 2 && days.includes('Sat') && days.includes('Sun')) return `Weekends at ${time}`
      return `${days.join(', ')} at ${time}`
    }
    if (!p.dom.all && p.dow.all && p.month.all) {
      return `Day ${[...p.dom.set!].sort((a, b) => a - b).join(', ')} of every month at ${time}`
    }
    if (!p.dom.all && p.dow.all && !p.month.all) {
      const months = [...p.month.set!].sort((a, b) => a - b).map(v => monNames[v]).join(', ')
      const days = [...p.dom.set!].sort((a, b) => a - b).join(', ')
      return `${months} ${days} at ${time}`
    }
  }
  if (!p.minute.all && p.minute.set!.size > 1 && p.hour.all) {
    const arr = [...p.minute.set!].sort((a, b) => a - b)
    const diffs = arr.slice(1).map((v, i) => v - arr[i])
    if (diffs.length && diffs.every(d => d === diffs[0]) && arr[0] % diffs[0] === 0) return `Every ${diffs[0]} minutes`
  }
  return `at minute ${humanizeFieldList(p.minute, 'every minute')}, hour ${humanizeFieldList(p.hour, 'every hour')}`
}

function parseField(field: string, min: number, max: number, names?: Record<string, number>): ParsedField {
  if (field === '*' || field === '?') return { all: true }
  const out = new Set<number>()
  field.split(',').forEach(part => {
    let stepStr = '1'
    let core = part
    const slash = part.indexOf('/')
    if (slash >= 0) {
      core = part.slice(0, slash)
      stepStr = part.slice(slash + 1)
    }
    const step = Math.max(1, parseInt(stepStr, 10) || 1)
    let lo: number | null = min
    let hi: number | null = max
    if (core === '*' || core === '') {
      lo = min
      hi = max
    } else if (core.includes('-')) {
      const [a, b] = core.split('-')
      lo = toNum(a, names)
      hi = toNum(b, names)
    } else {
      const n = toNum(core, names)
      lo = n
      hi = n
    }
    if (lo === null || hi === null || lo > max || hi < min) return
    lo = Math.max(min, lo)
    hi = Math.min(max, hi)
    for (let v = lo; v <= hi; v += step) out.add(v)
  })
  return { all: false, set: out }
}

function toNum(token: string | null, names?: Record<string, number>): number | null {
  if (token == null) return null
  const t = String(token).trim().toLowerCase()
  if (!t) return null
  if (names && names[t] !== undefined) return names[t]
  const n = parseInt(t, 10)
  return Number.isNaN(n) ? null : n
}

function matches(field: ParsedField, v: number): boolean {
  return field.all || field.set!.has(v)
}

function humanizeFieldList(field: ParsedField, allLabel: string): string {
  if (field.all) return allLabel
  const arr = [...field.set!].sort((a, b) => a - b)
  if (arr.length === 0) return '—'
  const display = arr.map(v => String(v).padStart(2, '0'))
  if (display.length === 1) return display[0]
  if (display.length <= 4) return display.join(', ')
  return display.slice(0, 3).join(', ') + ` & ${display.length - 3} more`
}
