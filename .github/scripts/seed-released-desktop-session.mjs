#!/usr/bin/env node

import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'

function option(name) {
  const index = process.argv.indexOf(name)
  if (index < 0 || !process.argv[index + 1]) {
    throw new Error(`Missing value for ${name}`)
  }
  return process.argv[index + 1]
}

function boundedTail(current, chunk, limit = 64 * 1024) {
  const next = current + Buffer.from(chunk).toString('utf8')
  return next.length > limit ? next.slice(-limit) : next
}

function sanitizedEnvironment(profileHome, layout) {
  const inherited = { ...process.env }
  for (const name of Object.keys(inherited)) {
    const upper = name.toUpperCase()
    if (
      name.startsWith('OPENSQUILLA_')
      || ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'].includes(upper)
      || /(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(name)
    ) {
      delete inherited[name]
    }
  }
  const runtimeHome = resolve(dirname(profileHome), 'released-runtime-home')
  return {
    ...inherited,
    HOME: runtimeHome,
    USERPROFILE: runtimeHome,
    MINIMAX_API_KEY: 'synthetic-release-key',
    OPENSQUILLA_GATEWAY_CONFIG_PATH: join(profileHome, 'config.toml'),
    OPENSQUILLA_STATE_DIR: layout === 'pre-rc3' ? join(profileHome, 'state') : profileHome,
    OPENSQUILLA_RECOVERY_OFFLINE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY: '1',
    HTTP_PROXY: 'http://127.0.0.1:1',
    HTTPS_PROXY: 'http://127.0.0.1:1',
    ALL_PROXY: 'http://127.0.0.1:1',
    NO_PROXY: '127.0.0.1,localhost',
    http_proxy: 'http://127.0.0.1:1',
    https_proxy: 'http://127.0.0.1:1',
    all_proxy: 'http://127.0.0.1:1',
    no_proxy: '127.0.0.1,localhost',
    PYTHONUNBUFFERED: '1',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8:replace',
  }
}

async function startProvider() {
  let requestCount = 0
  const server = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    let payload = {}
    try {
      payload = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
    } catch {
      payload = {}
    }

    if (request.method === 'GET' && request.url?.endsWith('/models')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({
        object: 'list',
        data: [{ id: 'synthetic-release-model' }],
      }))
      return
    }
    if (request.method !== 'POST' || !request.url?.endsWith('/chat/completions')) {
      response.writeHead(404, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ error: { message: 'synthetic endpoint not found' } }))
      return
    }
    requestCount += 1
    if (payload.stream === false) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({
        id: 'chatcmpl-released-runtime',
        object: 'chat.completion',
        model: 'synthetic-release-model',
        choices: [{
          index: 0,
          message: { role: 'assistant', content: 'RELEASED_RUNTIME_REPLY' },
          finish_reason: 'stop',
        }],
        usage: { prompt_tokens: 4, completion_tokens: 3, total_tokens: 7 },
      }))
      return
    }
    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'close',
    })
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-released-runtime',
      object: 'chat.completion.chunk',
      model: 'synthetic-release-model',
      choices: [{
        index: 0,
        delta: { role: 'assistant', content: 'RELEASED_RUNTIME_REPLY' },
        finish_reason: null,
      }],
    })}\n\n`)
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-released-runtime',
      object: 'chat.completion.chunk',
      model: 'synthetic-release-model',
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
      usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 },
    })}\n\n`)
    response.end('data: [DONE]\n\n')
  })
  server.listen(18993, '127.0.0.1')
  await once(server, 'listening')
  return {
    requests: () => requestCount,
    close: () => new Promise((resolveClose, rejectClose) => {
      server.close((error) => error ? rejectClose(error) : resolveClose())
    }),
  }
}

async function runReleasedGateway(gateway, profileHome, layout, label, marker) {
  const database = join(profileHome, 'state', 'sessions.db')
  const sessionKey = `agent:main:webchat:${label}-released-runtime`
  const runtimeHome = resolve(dirname(profileHome), 'released-runtime-home')
  await mkdir(runtimeHome, { recursive: true })
  const child = spawn(
    gateway,
    [
      'agent',
      '--message',
      marker,
      '--session-id',
      sessionKey,
      '--session-db-path',
      database,
      '--no-memory-capture',
      '--max-iterations',
      '1',
      '--timeout',
      '90',
      '--json',
    ],
    {
      env: sanitizedEnvironment(profileHome, layout),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', (chunk) => { stdout = boundedTail(stdout, chunk) })
  child.stderr.on('data', (chunk) => { stderr = boundedTail(stderr, chunk) })
  const timeout = setTimeout(() => {
    if (process.platform === 'win32' && child.pid) {
      spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true,
        stdio: 'ignore',
      })
    } else {
      child.kill('SIGKILL')
    }
  }, 120_000)
  let code
  let signal
  try {
    [code, signal] = await once(child, 'close')
  } finally {
    clearTimeout(timeout)
  }
  if (code !== 0) {
    throw new Error(
      `released gateway failed code=${code} signal=${signal}; `
      + `stdout=${stdout}; stderr=${stderr}`,
    )
  }
  return { database, sessionKey, stdout, stderr }
}

const gateway = resolve(option('--gateway'))
const profileHome = resolve(option('--profile-home'))
const layout = option('--layout')
const label = option('--label')
assert.ok(['pre-rc3', 'modern'].includes(layout), `unsupported layout: ${layout}`)
assert.match(label, /^[A-Za-z0-9._-]{1,80}$/)
const marker = `HISTORICAL_RELEASE_SESSION_${label}`
const provider = await startProvider()

try {
  const result = await runReleasedGateway(gateway, profileHome, layout, label, marker)
  assert.ok(provider.requests() >= 1, 'released runtime did not call the synthetic provider')
  console.log(JSON.stringify({
    ok: true,
    marker,
    sessionKey: result.sessionKey,
    database: result.database,
    providerRequests: provider.requests(),
  }))
} finally {
  await provider.close().catch(() => {})
}
