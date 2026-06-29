import { existsSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '..', '..')
const runtimeGatewayDir = join(packageRoot, 'runtime', 'gateway')
const pyinstallerWorkDir = join(packageRoot, '.pyinstaller')
const entryPath = join(scriptDir, 'gateway-entry.py')
const controlUiDistDir = join(repoRoot, 'src', 'opensquilla', 'gateway', 'static', 'dist')
const addDataSeparator = process.platform === 'win32' ? ';' : ':'

if (!existsSync(join(controlUiDistDir, 'index.html'))) {
  throw new Error(`Built Control UI not found at ${controlUiDistDir}. Run npm run build:web before npm run build:gateway.`)
}

rmSync(runtimeGatewayDir, { recursive: true, force: true })
mkdirSync(runtimeGatewayDir, { recursive: true })
mkdirSync(pyinstallerWorkDir, { recursive: true })

const args = [
  'run',
  '--with',
  'pyinstaller',
  'pyinstaller',
  '--noconfirm',
  '--clean',
  '--onedir',
  '--name',
  'opensquilla-gateway',
  '--distpath',
  runtimeGatewayDir,
  '--workpath',
  pyinstallerWorkDir,
  '--specpath',
  pyinstallerWorkDir,
  '--collect-all',
  'opensquilla',
  '--collect-all',
  'sqlite_vec',
  '--copy-metadata',
  'opensquilla',
  '--copy-metadata',
  'yoyo-migrations',
  '--hidden-import',
  'yoyo.backends.core.sqlite3',
  '--add-data',
  `${join(repoRoot, 'migrations')}${addDataSeparator}opensquilla/_migrations`,
  '--add-data',
  `${controlUiDistDir}${addDataSeparator}opensquilla/gateway/static/dist`,
  entryPath,
]

const result = spawnSync('uv', args, {
  cwd: repoRoot,
  env: {
    ...process.env,
    PYTHONUNBUFFERED: '1',
  },
  stdio: 'inherit',
})

if (result.error) {
  throw result.error
}
if (result.status !== 0) {
  process.exit(result.status ?? 1)
}
