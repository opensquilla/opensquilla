export function summariseDiffValue(value: unknown): string {
  const text = JSON.stringify(value)
  if (text === undefined) return String(value)
  return text.length > 120 ? text.slice(0, 117) + '…' : text
}
