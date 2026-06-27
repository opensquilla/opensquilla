import { existsSync } from 'node:fs'
import { readdir, readFile, stat } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '..', '..')
const runtimeGatewayDir = join(packageRoot, 'runtime', 'gateway')
const compiledMainPath = join(packageRoot, 'dist', 'main.js')
const desktopOutputDir = join(repoRoot, 'dist', 'desktop-electron')

const failures = []

function fail(message) {
  failures.push(message)
}

async function listFiles(root) {
  const files = []

  async function walk(dir) {
    let entries
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch (error) {
      fail(`${root} could not be read: ${error instanceof Error ? error.message : String(error)}`)
      return
    }

    for (const entry of entries) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) {
        await walk(path)
      } else if (entry.isFile() && entry.name !== '.DS_Store') {
        files.push(path)
      }
    }
  }

  await walk(root)
  return files
}

async function verifyRuntime(root, label) {
  if (!existsSync(root)) {
    fail(`${label} runtime is missing at ${root}`)
    return
  }

  const info = await stat(root).catch(() => null)
  if (!info?.isDirectory()) {
    fail(`${label} runtime is not a directory: ${root}`)
    return
  }

  const files = await listFiles(root)
  if (files.length === 0) {
    fail(`${label} runtime is empty: ${root}`)
    return
  }

  const compatFile = files.find((path) => path.endsWith(join('opensquilla', 'compat', 'aiosqlite.py')))
  if (!compatFile) {
    fail(`${label} runtime is missing opensquilla/compat/aiosqlite.py`)
    return
  }

  const source = await readFile(compatFile, 'utf8')
  if (!source.includes('async def create_function(') || !source.includes('self._conn.create_function')) {
    fail(`${label} runtime aiosqlite.py does not contain _AsyncConnection.create_function`)
  }
}

function verifyMainProcess(source, label) {
  for (const expected of ['gatewayStartPromise', 'openOrResumeDesktopApp', 'ensureGatewayStarted']) {
    if (!source.includes(expected)) fail(`${label} main process is missing ${expected}`)
  }

  const helperIndex = source.indexOf('async function openOrResumeDesktopApp')
  const createIndex = source.indexOf('await createMainWindow()', helperIndex)
  const ensureIndex = source.indexOf('ensureGatewayStarted()', helperIndex)
  if (helperIndex === -1 || createIndex === -1 || ensureIndex === -1 || createIndex > ensureIndex) {
    fail(`${label} main process does not create the desktop window before gateway startup`)
  }

  if (!/app\.on\(['"]activate['"][\s\S]{0,240}openOrResumeDesktopApp/.test(source)) {
    fail(`${label} main process activate handler does not route through openOrResumeDesktopApp`)
  }
  if (!/second-instance[\s\S]{0,240}openOrResumeDesktopApp/.test(source)) {
    fail(`${label} main process second-instance handler does not route through openOrResumeDesktopApp`)
  }
}

async function verifyCompiledMain() {
  if (!existsSync(compiledMainPath)) {
    fail(`compiled Electron main process is missing at ${compiledMainPath}; run npm run build first`)
    return
  }

  verifyMainProcess(await readFile(compiledMainPath, 'utf8'), 'compiled')
}

async function findGeneratedApps(root) {
  const apps = []
  if (!existsSync(root)) return apps

  async function walk(dir, depth) {
    if (depth > 5) return
    const entries = await readdir(dir, { withFileTypes: true }).catch(() => [])
    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const path = join(dir, entry.name)
      if (entry.name.endsWith('.app')) {
        apps.push(path)
      } else {
        await walk(path, depth + 1)
      }
    }
  }

  await walk(root, 0)
  return apps
}

async function readAsarText(asarPath, innerPath) {
  const asar = await import('@electron/asar')
  return asar.extractFile(asarPath, innerPath).toString('utf8')
}

async function verifyGeneratedApp(appPath) {
  const resourcesDir = join(appPath, 'Contents', 'Resources')
  await verifyRuntime(join(resourcesDir, 'runtime', 'gateway'), `app bundle ${appPath}`)

  const asarPath = join(resourcesDir, 'app.asar')
  if (!existsSync(asarPath)) {
    fail(`app bundle ${appPath} is missing app.asar`)
    return
  }

  try {
    verifyMainProcess(await readAsarText(asarPath, 'dist/main.js'), `app bundle ${appPath}`)
  } catch (error) {
    fail(`app bundle ${appPath} app.asar could not be inspected: ${error instanceof Error ? error.message : String(error)}`)
  }
}

await verifyRuntime(runtimeGatewayDir, 'source')
await verifyCompiledMain()

const generatedApps = await findGeneratedApps(desktopOutputDir)
for (const appPath of generatedApps) {
  await verifyGeneratedApp(appPath)
}

if (failures.length > 0) {
  console.error('OpenSquilla desktop package verification failed:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exit(1)
}

console.log('OpenSquilla desktop package verification passed.')
