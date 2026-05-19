from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

GATEWAY_ROOT = Path("src/opensquilla/gateway")
TEMPLATE = GATEWAY_ROOT / "templates/index.html"
STATIC_JS = GATEWAY_ROOT / "static/js"
BROWSER_RUNTIME_JS = STATIC_JS / "browser_runtime.js"


def _node() -> str:
    return "node.exe" if subprocess.os.name == "nt" else "node"


def test_browser_runtime_contract_loads_after_core_access_modules() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    rpc_idx = template.index("static/js/rpc.js")
    rpc_access_idx = template.index("static/js/rpc_access.js")
    http_access_idx = template.index("static/js/http_access.js")
    router_idx = template.index("static/js/router.js")
    runtime_idx = template.index("static/js/browser_runtime.js")
    first_component_idx = template.index("static/js/markdown.js")

    assert rpc_idx < rpc_access_idx < http_access_idx < router_idx < runtime_idx
    assert runtime_idx < first_component_idx


def test_browser_runtime_contract_executes_core_modules_in_browser_like_vm(
    tmp_path: Path,
) -> None:
    if shutil.which(_node()) is None:
        msg = "node is required for the browser runtime static contract"
        raise AssertionError(msg)

    harness = tmp_path / "webui_browser_runtime_contract.js"
    harness.write_text(
        textwrap.dedent(
            """
            const fs = require('fs');
            const path = require('path');
            const vm = require('vm');

            const root = process.cwd();
            const storage = () => {
              const map = new Map();
              return {
                getItem: (key) => map.has(key) ? map.get(key) : null,
                setItem: (key, value) => map.set(key, String(value)),
                removeItem: (key) => map.delete(key),
              };
            };

            class HeadersStub {
              constructor(init = {}) { this._entries = Object.entries(init); }
              forEach(callback) {
                for (const [key, value] of this._entries) callback(value, key);
              }
            }

            class WebSocketStub {
              static OPEN = 1;
              constructor(url) {
                this.url = url;
                this.readyState = WebSocketStub.OPEN;
                this.sent = [];
              }
              send(payload) { this.sent.push(payload); }
              close() {
                this.readyState = 3;
                if (typeof this.onclose === 'function') this.onclose();
              }
            }

            const context = {
              console,
              setTimeout,
              clearTimeout,
              setInterval,
              clearInterval,
              Headers: HeadersStub,
              WebSocket: WebSocketStub,
              CustomEvent: class CustomEvent {
                constructor(type, options = {}) {
                  this.type = type;
                  this.detail = options.detail || null;
                }
              },
              location: {
                protocol: 'http:',
                host: '127.0.0.1:60000',
                pathname: '/control',
                search: '',
              },
              history: { pushState() {} },
              localStorage: storage(),
              sessionStorage: storage(),
              fetch: async (url, options = {}) => ({
                ok: true,
                status: 200,
                json: async () => ({ url, options }),
              }),
              document: {
                documentElement: { setAttribute() {} },
                addEventListener() {},
                getElementById() { return null; },
                querySelector() { return null; },
                querySelectorAll() { return []; },
                createElement(tagName) {
                  return {
                    tagName,
                    style: {},
                    dataset: {},
                    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
                    appendChild(child) { return child; },
                    setAttribute() {},
                    removeAttribute() {},
                    contains() { return false; },
                    closest() { return null; },
                    addEventListener() {},
                    removeEventListener() {},
                    innerHTML: '',
                    textContent: '',
                  };
                },
              },
              matchMedia: () => ({ matches: false }),
              addEventListener() {},
              removeEventListener() {},
              dispatchEvent() {},
            };
            context.window = context;
            context.globalThis = context;
            vm.createContext(context);

            for (const rel of [
              'src/opensquilla/gateway/static/js/rpc.js',
              'src/opensquilla/gateway/static/js/rpc_access.js',
              'src/opensquilla/gateway/static/js/http_access.js',
              'src/opensquilla/gateway/static/js/router.js',
              'src/opensquilla/gateway/static/js/browser_runtime.js',
              'src/opensquilla/gateway/static/js/app.js',
            ]) {
              const source = fs.readFileSync(path.join(root, rel), 'utf8');
              vm.runInContext(source, context, { filename: rel });
            }

            const runtime = context.OpenSquillaBrowserRuntime;
            runtime.requireGlobals(['RpcClient', 'WebUiRpc', 'WebUiHttp', 'Router', 'App']);
            const core = runtime.coreContract();
            const app = runtime.appContract();
            const client = new core.RpcClient();
            const seenStates = [];
            client.on('_state', (state) => seenStates.push(state));
            client.connect('ws://127.0.0.1/ws', 'token-1');

            Promise.resolve(context.WebUiHttp.getJson('/api/probe')).then((payload) => {
              const report = {
                globals: runtime.availableGlobals([
                  'RpcClient',
                  'WebUiRpc',
                  'WebUiHttp',
                  'Router',
                  'App',
                ]),
                appApi: Object.keys(app.App).sort(),
                rpcState: client.state,
                rpcPolicyType: typeof core.WebUiRpc.policy,
                httpProbeUrl: payload.url,
                httpProbeMethod: payload.options.method || 'GET',
                seenStates,
              };
              console.log(JSON.stringify(report));
            }).catch((err) => {
              console.error(err && err.stack ? err.stack : String(err));
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [_node(), str(harness)],
        check=True,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["globals"] == {
        "RpcClient": True,
        "WebUiRpc": True,
        "WebUiHttp": True,
        "Router": True,
        "App": True,
    }
    assert "getAuthToken" in payload["appApi"]
    assert "getRpc" in payload["appApi"]
    assert payload["rpcState"] == "connecting"
    assert payload["rpcPolicyType"] == "function"
    assert payload["httpProbeUrl"] == "/api/probe"
    assert payload["httpProbeMethod"] == "GET"
    assert payload["seenStates"] == ["connecting"]
