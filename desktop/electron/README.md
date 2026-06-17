# OpenSquilla Electron Desktop Shell

This package is the macOS desktop shell for the existing OpenSquilla Control UI.
It does not rewrite the Vue frontend. The Electron main process configures a
desktop credential, starts a local gateway, and loads the backend-served
`/control/` app.

## Development Flow

From the repository root:

```bash
cd opensquilla-webui
npm run build

cd ../desktop/electron
npm install
npm run dev
```

On first run, the shell opens a setup window for provider, model, base URL, and
API key. The key is encrypted with Electron `safeStorage` when available, and a
desktop-specific gateway config is written under Electron `userData`.

The shell looks for the checkout root automatically. To point it at a different
checkout:

```bash
OPENSQUILLA_DESKTOP_REPO_ROOT=/path/to/opensquilla npm run dev
```

To attach to an already-running gateway instead of spawning one:

```bash
OPENSQUILLA_DESKTOP_GATEWAY_URL=http://127.0.0.1:18791 npm run dev
```

## Local Release Build

```bash
cd desktop/electron
npm run dist:local
```

This builds the Vue Control UI, bundles the gateway with PyInstaller, and emits
macOS artifacts under `dist/desktop-electron/`.

For a faster rebuild after the runtime already exists:

```bash
cd desktop/electron
npm run build:web
npm run dist
```

## Current Scope

- Reuses `opensquilla-webui` and the Python gateway exactly as they run in the
  browser.
- Starts a bundled `runtime/gateway/opensquilla-gateway` in packaged builds.
- Falls back to `uv run opensquilla gateway run --bind 127.0.0.1 --port <port>`
  during development when no bundled runtime exists.
- Uses `contextIsolation: true`, `nodeIntegration: false`, and a minimal preload
  bridge.
- Writes credential, config, state, and gateway logs under the Electron
  `userData` directory.

## Release Work Still Needed

- Add macOS code signing and notarization.
- Add updater artifacts and an update feed.
- Add a branded application icon and installer background.
