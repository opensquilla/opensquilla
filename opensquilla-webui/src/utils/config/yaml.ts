export function objToYaml(obj: unknown, indent = 0): string {
  const pad = '  '.repeat(indent)
  if (obj === null || obj === undefined) return 'null'
  if (typeof obj === 'boolean') return String(obj)
  if (typeof obj === 'number') return String(obj)
  if (typeof obj === 'string') {
    if (/[\n:#\[\]{}&*!|>'"%@`]/.test(obj) || obj.trim() !== obj) {
      return JSON.stringify(obj)
    }
    return obj
  }
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]'
    return '\n' + obj.map(item => pad + '- ' + objToYaml(item, indent + 1)).join('\n')
  }
  if (typeof obj === 'object') {
    const keys = Object.keys(obj as object)
    if (keys.length === 0) return '{}'
    return '\n' + keys.map(k => {
      const val = (obj as Record<string, unknown>)[k]
      const rendered = objToYaml(val, indent + 1)
      const inline = typeof val !== 'object' || val === null
      return pad + k + ': ' + (inline ? rendered : rendered.trimStart())
    }).join('\n')
  }
  return String(obj)
}
