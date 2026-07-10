import assert from 'node:assert/strict'

import { buildCliInvocation } from '../dist/cli-invocation.js'

// --- bundled posix: env pair + quoted binary, spaces survive quoting ---
{
  const result = buildCliInvocation({
    platform: 'darwin',
    mode: 'bundled',
    binaryPath: '/Applications/OpenSquilla.app/Contents/Resources/runtime/gateway/opensquilla-gateway/opensquilla-gateway',
    // OPENSQUILLA_STATE_DIR is the OpenSquilla home root; runtime databases
    // remain under the config-pinned <home>/state directory.
    stateDir: '/opt/OpenSquilla Data',
    configPath: '/opt/OpenSquilla Data/config.toml',
  })
  assert.equal(result.mode, 'bundled')
  assert.equal(
    result.prefix,
    "OPENSQUILLA_STATE_DIR='/opt/OpenSquilla Data' "
      + "OPENSQUILLA_GATEWAY_CONFIG_PATH='/opt/OpenSquilla Data/config.toml' "
      + "'/Applications/OpenSquilla.app/Contents/Resources/runtime/gateway/opensquilla-gateway/opensquilla-gateway'",
  )
}

// --- posix: single quotes inside paths get the '\'' escape ---
{
  const result = buildCliInvocation({
    platform: 'linux',
    mode: 'bundled',
    binaryPath: "/opt/o'brien apps/opensquilla-gateway",
    stateDir: "/opt/o'brien data",
    configPath: "/opt/o'brien data/config.toml",
  })
  assert.ok(result.prefix.includes("'/opt/o'\\''brien apps/opensquilla-gateway'"))
  assert.ok(result.prefix.includes("OPENSQUILLA_STATE_DIR='/opt/o'\\''brien data'"))
}

// --- windows: PowerShell $env: syntax, '' doubling, & call operator ---
{
  const result = buildCliInvocation({
    platform: 'win32',
    mode: 'bundled',
    binaryPath: 'C:\\Program Files\\OpenSquilla\\resources\\runtime\\gateway\\opensquilla-gateway.exe',
    stateDir: "C:\\Users\\o'brien\\AppData\\Roaming\\OpenSquilla\\opensquilla",
    configPath: 'C:\\Users\\jo\\AppData\\Roaming\\OpenSquilla\\opensquilla\\config.toml',
  })
  assert.ok(result.prefix.startsWith("$env:OPENSQUILLA_STATE_DIR = 'C:\\Users\\o''brien\\AppData"))
  assert.ok(result.prefix.includes("$env:OPENSQUILLA_GATEWAY_CONFIG_PATH = 'C:\\Users\\jo\\AppData"))
  assert.ok(result.prefix.includes("& 'C:\\Program Files\\OpenSquilla\\resources\\runtime\\gateway\\opensquilla-gateway.exe'"))
}

// --- windows: unicode smart quotes are single-quote delimiters in PowerShell ---
{
  const result = buildCliInvocation({
    platform: 'win32',
    mode: 'bundled',
    binaryPath: 'C:\\Apps\\OpenSquilla\\opensquilla-gateway.exe',
    stateDir: 'C:\\Users\\O’Brien\\AppData\\Roaming\\OpenSquilla\\opensquilla',
    configPath: 'C:\\Users\\O’Brien\\AppData\\Roaming\\OpenSquilla\\opensquilla\\config.toml',
  })
  assert.ok(result.prefix.includes("$env:OPENSQUILLA_STATE_DIR = 'C:\\Users\\O’’Brien\\AppData"))
  assert.ok(result.prefix.includes("$env:OPENSQUILLA_GATEWAY_CONFIG_PATH = 'C:\\Users\\O’’Brien\\AppData"))
}

// --- windows dev mode: PowerShell env syntax composes with the uv runner ---
{
  const result = buildCliInvocation({
    platform: 'win32',
    mode: 'dev',
    repoRoot: 'C:\\Dev Projects\\opensquilla',
    stateDir: 'C:\\Users\\jo\\AppData\\Roaming\\OpenSquilla\\opensquilla',
    configPath: 'C:\\Users\\jo\\AppData\\Roaming\\OpenSquilla\\opensquilla\\config.toml',
  })
  assert.equal(result.mode, 'dev')
  assert.ok(result.prefix.startsWith("$env:OPENSQUILLA_STATE_DIR = 'C:\\Users\\jo\\AppData"))
  assert.ok(result.prefix.endsWith("uv run --directory 'C:\\Dev Projects\\opensquilla' opensquilla"))
}

// --- dev mode: uv run with an explicit checkout directory, no cwd dependence ---
{
  const result = buildCliInvocation({
    platform: 'darwin',
    mode: 'dev',
    repoRoot: '/opt/dev projects/opensquilla',
    stateDir: '/opt/OpenSquilla Data',
    configPath: '/opt/OpenSquilla Data/config.toml',
  })
  assert.equal(result.mode, 'dev')
  assert.ok(result.prefix.endsWith("uv run --directory '/opt/dev projects/opensquilla' opensquilla"))
}

console.log('cli-invocation: all assertions passed')
