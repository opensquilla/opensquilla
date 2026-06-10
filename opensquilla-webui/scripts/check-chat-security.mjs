import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('..', import.meta.url).pathname

function read(rel) {
  return readFileSync(join(root, rel), 'utf8')
}

const failures = []

function assertAbsent(rel, pattern, message) {
  const body = read(rel)
  if (pattern.test(body)) failures.push(`${rel}: ${message}`)
}

function assertPresent(rel, pattern, message) {
  const body = read(rel)
  if (!pattern.test(body)) failures.push(`${rel}: ${message}`)
}

assertAbsent(
  'src/utils/chat/artifacts.ts',
  /\btoken\??:\s*string|searchParams\.set\(['"]token['"]|includeSessionKey\s*!==\s*false/,
  'artifact URLs must not carry bearer tokens or default session keys in query params.',
)

assertPresent(
  'src/utils/chat/artifacts.ts',
  /searchParams\.delete\(['"]token['"]\)[\s\S]+searchParams\.delete\(['"]sessionKey['"]\)[\s\S]+searchParams\.delete\(['"]session_key['"]\)/,
  'artifact URL sanitizer must strip sensitive same-origin query params.',
)

assertAbsent(
  'src/composables/chat/useChatMarkdownExport.ts',
  /\bsessionKey\b|\bauthToken\b|\btoken\b|artifactDownloadUrl/,
  'Markdown export must not persist raw sessions, bearer tokens, or signed artifact URLs.',
)

assertAbsent(
  'src/components/chat/ChatArtifactList.vue',
  /artifactPreviewUrl\(|:href="artifactUrl\(|:src="artifactUrl\(/,
  'artifact previews must not render credential-bearing artifact URLs directly into the DOM.',
)

assertPresent(
  'src/components/chat/ChatArtifactList.vue',
  /URL\.createObjectURL\(blob\)/,
  'artifact previews must render fetched blob object URLs.',
)

if (failures.length > 0) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('Chat security guard passed.')
