export function parseDesktopDotenvValue(raw: string): string | null {
  const value = raw.trim()
  if (!value) return ''
  let parsed = ''
  if (value[0] === "'" || value[0] === '"') {
    const quote = value[0]
    let escaped = false
    let end = -1
    for (let index = 1; index < value.length; index += 1) {
      const character = value[index]
      if (quote === '"' && escaped) {
        escaped = false
        continue
      }
      if (quote === '"' && character === '\\') {
        escaped = true
        continue
      }
      if (character === quote) {
        end = index
        break
      }
    }
    const tail = end >= 0 ? value.slice(end + 1).trim() : ''
    if (end < 0 || (tail && !tail.startsWith('#'))) return null
    parsed = value.slice(1, end)
    if (quote === '"') {
      const decoded: Record<string, string> = {
        '\\': '\\',
        '"': '"',
        n: '\n',
        r: '\r',
        t: '\t',
      }
      // A single regex pass prevents an escaped backslash from being decoded
      // again as a newly-created \n, \r, or \t escape in Windows paths.
      parsed = parsed.replace(/\\([\\"nrt])/g, (_encoded, escape: string) => decoded[escape]!)
    } else {
      parsed = parsed.replace(/\\([\\'])/g, (_encoded, escape: string) => escape)
    }
  } else {
    parsed = value.split(/\s+#/, 1)[0]?.trim() || ''
  }
  if (parsed.includes('$') || parsed.includes('\0')) return null
  return parsed
}
