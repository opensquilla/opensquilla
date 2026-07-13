<!-- 本檔譯自 README.md @ 46bc8838。英文版 README 為權威來源。 -->
<!-- 檢查是否過期：git log 46bc8838..HEAD -- README.md -->

# OpenSquilla — 高效省 Token 的 AI Agent

<p align="center">
  <img src="assets/opensquilla-long-logo.png" alt="OpenSquilla logo" width="500">
</p>

<p align="center">
  <b>同樣的預算，更多能力，更好的成果。</b><br>
  為你的 CLI、Web UI 與聊天頻道打造的微核心 AI Agent。
</p>

<p align="center">
  <a href="https://github.com/opensquilla/opensquilla/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/opensquilla/opensquilla/ci.yml?style=for-the-badge" alt="CI"></a>
  <a href="https://opensquilla.ai/"><img src="https://img.shields.io/badge/website-opensquilla.ai-blue?style=for-the-badge" alt="Website"></a>
  <a href="https://github.com/opensquilla/opensquilla/releases"><img src="https://img.shields.io/github/v/release/opensquilla/opensquilla?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue?style=for-the-badge" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge" alt="Apache 2.0 License"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-Hans.md">中文</a> · <b>繁體中文</b> · <a href="README.ja.md">日本語</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

> 本翻譯譯自英文 [`README.md`](README.md)，如有出入請以英文版為準。

---

## 最新消息

- 📢 **2026-07-03** — 我們的技術報告 **[Agentic Routing: The Harness-Native Data Flywheel](docs/releases/agentic_routing_v0.pdf)**（預覽版）已發布，與 OpenSquilla **0.5.0 Preview 1** 同步推出。報告詳細說明了 harness 原生路由如何將日常 Agent 流量，轉化為能自我改進的資料飛輪。

---

## 總覽

OpenSquilla 是一個高效運用 Token 的微核心 AI Agent。本地端的模型 router 會把每一輪都送往能夠處理它的最便宜模型，而持久記憶、分層 sandbox、內建網路搜尋，以及裝置端 embedding，則共同組成這個統一共用的輪次迴圈。

每一個入口——Web UI、CLI 與聊天頻道——都會經過同一個迴圈，因此工具調度、重試與決策日誌，在各處的行為都完全一致。可插拔的 provider 層串接 TokenRhythm、OpenRouter、OpenAI、Anthropic、Ollama、DeepSeek、Gemini、Qwen/DashScope，以及其他 20 多個 LLM provider，完全不需要更動你的程式碼或設定結構。

OpenSquilla 0.5.0 Preview 3 是目前的預覽版本。

如需以任務為導向的產品說明，請從 [OpenSquilla 產品指南](README.product.md) 或 [說明索引](docs/README.md) 開始。

---

## 安裝

OpenSquilla 可在 Windows、macOS 與 Linux 上執行。請選擇符合你使用情境的安裝路徑。

桌面安裝程式與終端機快速安裝，會直接給你預先建置好的**發布版**——不需要 Git。另外兩種——從原始碼安裝與從原始碼開發——則是**從 Git checkout** 建置（`git clone` + Git LFS）。

發布版安裝指令使用的是已發布在 GitHub Release 上的資產。Python wheel 的安裝方式使用帶版本號的 wheel 檔名，因為安裝程式會驗證內嵌在 wheel 檔名中的版本號。

若要在桌面環境使用 0.5.0 Preview 3，建議優先選用 GitHub Release 中打包好的桌面安裝程式：macOS 使用 `OpenSquilla-0.5.0-rc3-mac-arm64.dmg`，Windows 使用 `OpenSquilla-0.5.0-rc3-win-x64.exe`。

| 安裝路徑 | 適用對象 | 使用時機 |
| --- | --- | --- |
| [桌面安裝程式](#桌面安裝程式) **（建議桌面版使用）** | macOS 與 Windows 使用者 | 打包好的桌面應用程式 |
| [終端機快速安裝](#終端機快速安裝) **（建議）** | 任何作業系統的一般使用者 | 在終端機中安裝發布版 wheel |
| [從原始碼安裝](#從原始碼安裝) | 追蹤 `main` 分支的使用者 | 從 checkout 執行，而不修改它 |
| [從原始碼開發](#從原始碼開發) | 貢獻者 | 編輯、測試或偵錯原始碼 |

### 前置需求

| 需求 | 終端機快速安裝 | 從原始碼安裝 | 從原始碼開發 |
| --- | :---: | :---: | :---: |
| Python 3.12+ | 透過 `uv` | 透過 `uv` 或系統內建 | 透過 `uv` |
| Git + Git LFS | — | 必要 | 必要 |
| `uv` | 缺少時自動安裝 | 建議安裝 | 必要 |

預設的 `recommended` profile 會安裝 **SquillaRouter**——OpenSquilla 的裝置端模型
router——以及它的模型資產；`OPENSQUILLA_INSTALL_PROFILE=core` 則會省略這些依賴
套件。另一個獨立的 `--router disabled` onboarding 選項，會保留已安裝的依賴套件，
只在執行期關閉 router。

在 Windows 上，SquillaRouter 內建的 ONNX runtime 還需要 Visual C++ runtime。從原始碼
安裝用的 PowerShell 安裝程式會透過 `winget` 自動安裝它；但**終端機快速安裝**
（`uv tool install`）這條路徑不會——如果啟動時記錄了 `DLL load failed` 錯誤，
請手動安裝（見[疑難排解](#疑難排解)）。在裝好之前，OpenSquilla 會以直連單一模型
的路由方式繼續運作。

在 macOS 終端機安裝時，SquillaRouter 的 LightGBM runtime 可能也需要系統的 OpenMP
函式庫。桌面應用程式會內建它所需的 runtime，但**終端機快速安裝**不會安裝
Homebrew／系統函式庫。如果啟動時記錄了 `Library not loaded:
@rpath/libomp.dylib`，請執行 `brew install libomp`，然後重新啟動 gateway。
OpenSquilla 會以直連單一模型的路由方式繼續運作，直到裝好為止。

安裝連結：[Git](https://git-scm.com/downloads) ·
[Git LFS](https://git-lfs.com/) ·
[uv](https://docs.astral.sh/uv/getting-started/installation/)。

### 桌面安裝程式

0.5.0 Preview 3 的桌面安裝程式，會把 Vue 控制台與 gateway runtime 一起打包進
Electron shell 中。

- macOS Apple Silicon: <https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc3/OpenSquilla-0.5.0-rc3-mac-arm64.dmg>
- Windows x64: <https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc3/OpenSquilla-0.5.0-rc3-win-x64.exe>

升級前請先關閉任何正在執行的 OpenSquilla 桌面應用程式。在 macOS 上，安裝或更新時
請把應用程式從 DMG 拖曳到 Applications 資料夾，退出 DMG，然後開啟 Applications
資料夾中的那一份。既有的 `~/.opensquilla/config.toml` 與工作階段資料都會被沿用。

程式碼簽署政策：[`docs/code-signing-policy.md`](docs/code-signing-policy.md)。

> [!NOTE]
> Windows 版本目前尚未簽署。如果出現 SmartScreen 提示，請選擇
> **其他資訊** → **仍要執行**。如果 Smart App Control 或企業政策封鎖了未簽署的
> 應用程式，請改用[終端機快速安裝](#終端機快速安裝)。

### 終端機快速安裝

這是 Windows、macOS 與 Linux 上的建議安裝路徑。`uv` 會把 OpenSquilla 安裝進它
自己的獨立環境，並自行管理專屬的 Python——不需要系統 Python。這條路徑只會安裝
已發布的版本；如果你要用 `main` 分支、開發分支，或本地端的 checkout，請改用
[從原始碼安裝](#從原始碼安裝)。

**1. 安裝 `uv`**——如果 `uv --version` 已經可以執行，可略過此步驟。

Linux / macOS:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
```

Windows PowerShell:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
$env:Path = "$env:USERPROFILE\.local\bin;" + $env:Path
```

**2. 安裝 OpenSquilla**——所有平台使用相同的指令。

```sh
uv tool install --python 3.12 "opensquilla[recommended] @ https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc3/opensquilla-0.5.0rc3-py3-none-any.whl"
```

這個指令會從 release URL 安裝 OpenSquilla wheel，接著讓 `uv` 下載所選 extra
所宣告的依賴套件。預設的 `recommended` extra 包含 SquillaRouter 執行所需的
依賴套件，例如 ONNX Runtime、LightGBM、NumPy 與 tokenizers，因此首次安裝需要
網路連線，除非這些 wheel 已經被快取起來。`uv` 不會安裝系統原生 runtime，例如
macOS 的 `libomp` 或 Windows 的 Visual C++ Redistributable；如果 router runtime
回報原生函式庫載入錯誤，請見[疑難排解](#疑難排解)。

**3. 設定並執行。**

```sh
opensquilla onboard
opensquilla gateway run
```

> [!NOTE]
> 如果全新的 `uv` 安裝完成後立即找不到 `opensquilla`，請開啟一個新的終端機視窗，
> 或重新執行步驟 1 中設定 PATH 的那一行指令。

若要完全鎖定版本進行安裝，請使用帶版本號的 wheel URL：
`https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc3/opensquilla-0.5.0rc3-py3-none-any.whl`。

### 從原始碼安裝

如果你想從 checkout 執行 OpenSquilla、但不打算修改它，請用這條路徑。這份 clone
只是提供給安裝程式當作套件來源；安裝完成後，請使用 `opensquilla` 指令——不要
執行 `uv run`。如果你打算修改程式碼，請改用[從原始碼開發](#從原始碼開發)。

1. **連同 LFS 資產一起 clone**

   ```sh
   git lfs install
   git clone https://github.com/opensquilla/opensquilla.git
   cd opensquilla
   git lfs pull --include="src/opensquilla/squilla_router/models/**"
   ```

2. **執行安裝程式**

   **macOS / Linux**

   ```sh
   bash scripts/install_source.sh
   ```

   **Windows PowerShell**

   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/install_source.ps1
   ```

   這個腳本會透過 `uv tool install` 把 `.[recommended]`（SquillaRouter + 記憶 +
   本地端模型）安裝進一個專屬的使用者環境；當 `uv` 無法使用時，則會退回使用
   `python -m pip install --user`。如果安裝後 `opensquilla` 不在 `PATH` 上
   （在 `~/.local/bin` 尚未加入 `PATH` 的全新主機上很常見），請執行
   `uv tool update-shell` 並開啟一個新的終端機視窗；詳情請見
   [疑難排解](#疑難排解)。

3. **（選用）安裝進階 extra。** 大多數頻道——Feishu（飛書）、Telegram、
   DingTalk（釘釘）、QQ、WeCom（企業微信）與 Discord——在基礎安裝下就能運作。
   可選擇加入的 extra 有：

   - `matrix` — Matrix 頻道（會引入 `matrix-nio`）
   - `matrix-e2e` — 具備端對端加密的 Matrix 頻道（需要 libolm）
   - `document-extras` — 透過 WeasyPrint 產生 PDF

   ```sh
   OPENSQUILLA_INSTALL_EXTRAS=matrix bash scripts/install_source.sh        # macOS / Linux
   ```

   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/install_source.ps1 -Extras matrix   # Windows
   ```

4. **設定並執行**——見[設定](#設定)。

<details>
<summary>從原始碼安裝——終端機前置需求與安裝程式選項</summary>

**從終端機安裝前置需求（Git、Git LFS、uv）**

Windows PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id GitHub.GitLFS -e
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
git lfs install
```

macOS (Homebrew):

```sh
brew install git git-lfs uv
git lfs install
```

Debian / Ubuntu:

```sh
sudo apt update && sudo apt install -y git git-lfs
curl -LsSf https://astral.sh/uv/install.sh | sh
git lfs install
```

在 Fedora 上請使用 `sudo dnf install -y git git-lfs`；在 Arch 上請使用
`sudo pacman -S --needed git git-lfs`；然後用上面的 `curl` 指令安裝 `uv`。
這些安裝程式對 PATH 的變更，會在新的終端機工作階段中生效。

**安裝程式的環境變數與 PATH 檢查**

```sh
OPENSQUILLA_INSTALL_PROFILE=core   bash scripts/install_source.sh   # minimal runtime, no SquillaRouter
OPENSQUILLA_INSTALL_DRY_RUN=1      bash scripts/install_source.sh   # print the plan only
```

用 `command -v opensquilla`（macOS/Linux）或 `where.exe opensquilla`
（Windows）確認你的 shell 實際執行的是哪一個 `opensquilla`。如果它不在
`PATH` 上，請執行 `uv tool update-shell`。從本地端 checkout 重新安裝後，
請重新啟動 gateway，讓它載入更新後的套件。

</details>

### 從原始碼開發

當你要動手處理 OpenSquilla 的原始碼——修改程式碼、跑測試，或針對這份 checkout
偵錯行為時，請用這條路徑。這不是一般的安裝路徑。與[從原始碼安裝](#從原始碼安裝)
不同，這條路徑需要 `uv`：`uv sync` 會建立一個儲存庫本地端的 `.venv`，而
`uv run` 會針對這份 checkout 中的檔案執行指令。

```sh
uv sync --extra recommended --extra dev
uv run opensquilla --help
```

`recommended` extra 在開發時同樣會包含 SquillaRouter；`dev` extra 則會安裝
測試、lint 與型別檢查工具。請把額外的 extra，安裝進你實際執行的同一個環境中：

```sh
uv sync --extra recommended --extra dev --extra matrix
uv run opensquilla channels status matrix --json
```

在這種模式下，請在[設定](#設定)一節出現的每一條 `opensquilla` 指令前面，加上
`uv run` 前綴。不要透過使用者本地端的 `opensquilla` 指令，去偵錯開發用的
checkout——那個指令是在另一個 Python 環境中執行的。

### 解除安裝

使用 `opensquilla uninstall` 來移除 OpenSquilla。它預設會保留你的資料，只移除
程式本身：

```sh
opensquilla uninstall --dry-run   # preview what would be removed and kept
opensquilla uninstall             # remove the program, keep your data
```

如果也要刪除資料，請明確加上對應選項：

```sh
opensquilla uninstall --purge-state    # sessions, logs, cache, scheduler, memory
opensquilla uninstall --purge-config   # config.toml and secrets (.env)
opensquilla uninstall --purge-all      # everything (asks you to type a confirmation)
```

執行中的 gateway 會先排空既有連線再停止，刪除動作僅限於 OpenSquilla 主目錄之內；
若是 Docker 或桌面安裝，則會改為提供有引導的移除步驟。桌面應用程式或作業系統
層級應用程式的移除仍依平台而異；CLI 的指引不會移除桌面應用程式的 app bundle。
完整參考請見 [`docs/cli.md`](docs/cli.md#uninstall)。

---

## 安裝隱私

OpenSquilla 使用匿名的安裝遙測，來估算安裝數量、版本採用情形與 runtime
相容性。資料只會在 gateway 首次啟動時，以及每個 OpenSquilla 版本各上傳一次時
傳送。OpenSquilla 也可能執行被動的更新檢查，包括桌面版啟動時的自動更新檢查。
上傳作業設有短逾時，絕不會阻擋啟動。

完整隱私權政策——涵蓋本地端資料、provider 請求、網路可觀測性、日誌、發布版本
下載與刪除——請見 [`PRIVACY.md`](PRIVACY.md)。

會傳送的內容：

- schema 版本
- 本地端產生的穩定 `install_id` 摘要
- OpenSquilla 版本
- 事件類型（`install` 或 `version_seen`）
- 安裝方式（`pip`、`source`、`docker`、`desktop` 或 `unknown`）
- 作業系統、系統版本、CPU 架構，以及 Python 主／次版本號
- 首次見到與傳送的時間戳記
- CI／測試環境標記（`ci_environment`）

`install_id` 是一個本地端產生的單向 SHA-256 摘要，由可用的 MAC 位址推導而來；
當沒有可用的 MAC 位址時，則改用本地端 IP 位址，並以隨機產生且持久化保存的值
作為備援。原始的 MAC／IP 數值不會被上傳。

不會傳送的內容：使用者名稱、主機名稱、路徑、API key、provider 設定、
聊天／工作階段／記憶／Agent 內容、檔案名稱，或檔案內容。來源 IP 在傳輸層
可能會被 HTTP 伺服器看到，但它並不屬於 payload 的一部分。

若要在啟動前關閉非使用者主動觸發的網路可觀測性：

```sh
OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY=true
```

或設定：

```toml
[privacy]
disable_network_observability = true
```

這個統一開關涵蓋自動安裝遙測、被動更新檢查，以及桌面版啟動時的自動更新檢查。
使用者主動觸發的操作，在確認使用者意圖後，仍可能連線到網路服務，包括手動的
發布版本、下載或更新檢查，以及已設定的 provider、搜尋或頻道。

舊版的停用環境變數仍然有效：

```sh
OPENSQUILLA_TELEMETRY_DISABLED=true
OPENSQUILLA_UPDATE_CHECK_DISABLED=true
```

進階部署可以使用自訂的 endpoint：

```sh
OPENSQUILLA_TELEMETRY_ENDPOINT=https://example.com/v1/install
```

---

## 設定

### 首次設定

`opensquilla onboard` 是互動式的首次設定精靈。它會寫入目前使用中的設定檔；
當你傳入 `--api-key-env` 時，provider 的金鑰會留在環境變數裡。router 預設為
`recommended`（在受支援的 provider 上啟用 SquillaRouter）；傳入
`--router disabled` 則會改用直連單一模型的路由方式。

```sh
opensquilla onboard                # full interactive wizard
opensquilla onboard --if-needed    # idempotent: safe for scripts and re-installs
opensquilla onboard --minimal      # provider only; skip channels and search
opensquilla onboard status         # inspect every setup section without writing
```

在 SSH、CI，或任何沒有 TTY 的環境中，請使用非互動形式——把金鑰留在環境變數裡，
並傳入它的**名稱**，而不是它的值：

**Linux / macOS**

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

**Windows PowerShell**

```powershell
$env:OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

OpenRouter 只是範例——你可以替換成任何受支援的 provider，以及它對應的
API key 變數。

之後如果只想重新設定某一個部分，不需要重跑整個精靈（以下範例假設相關的
API key 已經在環境變數中）：

```sh
opensquilla configure provider --provider openai --model gpt-4o --api-key-env OPENAI_API_KEY
opensquilla configure router --router recommended
opensquilla configure search   --search-provider duckduckgo
opensquilla configure search   --search-provider exa --api-key-env EXA_API_KEY
opensquilla configure channels
```

各設定區段：`provider`、`router`、`channels`、`search`、`image-generation`、
`memory-embedding`。Web UI 在 `/control/setup` 提供相同的項目清單與狀態模型：
Provider 與 Router 是快速路徑，而 Channels、Search、Image generation 與
Memory embedding，則位於能力中心（Capability Center），可以稍後再設定。
頻道留空會被視為主動不使用，而不是設定失敗。

**設定檔載入順序：** `OPENSQUILLA_GATEWAY_CONFIG_PATH` → `./opensquilla.toml`
→ `~/.opensquilla/config.toml` → 內建預設值。個別金鑰的環境變數數值，永遠
優先於設定檔中的數值。

### 從 OpenClaw 或 Hermes Agent 遷移

如果你在 `~/.openclaw` 或 `~/.hermes` 底下已經有狀態資料，請先執行一次
dry run 來檢視遷移報告，然後再明確套用：

```sh
opensquilla migrate openclaw --json
opensquilla migrate openclaw --apply

opensquilla migrate hermes --json
opensquilla migrate hermes --apply
```

使用 `opensquilla migrate --source openclaw,hermes --apply` 可以同時匯入
兩個預設主目錄。只有在檢視過 dry-run 報告之後，才加上 `--migrate-secrets`。
自訂路徑與衝突處理方式，請見 [`MIGRATION.md`](MIGRATION.md)。

### 執行

```sh
opensquilla gateway run                # foreground, 127.0.0.1:18791
opensquilla gateway start --json       # background + health wait
opensquilla chat                       # interactive REPL
opensquilla agent -m "your prompt"     # one-shot, automation-friendly
```

> **預覽功能——OpenTUI 終端機介面。** `opensquilla chat` 預設會執行穩定的
> Python 原生聊天介面。更豐富的 OpenTUI 前端（佈景主題、單卡片輪次、即時
> router HUD、拖曳選取複製）是一項選擇性啟用的預覽功能，**僅能從
> [從原始碼開發](#從原始碼開發)的 checkout 中執行**：其執行環境是從執行中
> 程式碼旁的 OpenTUI package 載入的，而該 package（以及它的
> [Bun](https://bun.sh) 依賴套件）並未包含在發布版 wheel 或
> `Install from source` 的安裝內容中。從該 checkout 出發，先安裝一次 Bun
> 的依賴套件，再用 `uv run` 啟動，讓它針對同一份程式碼樹執行：
>
> ```sh
> bun install --frozen-lockfile --cwd=src/opensquilla/cli/tui/opentui/package
> OPENSQUILLA_TUI_BACKEND=opentui uv run opensquilla chat
> ```
>
> 若要使用穩定版聊天介面，請不要設定 `OPENSQUILLA_TUI_BACKEND`。終端機聊天
> 介面用法請見 [docs/tui.md](docs/tui.md)，後端細節請見
> [docs/features/tui-frontend.md](docs/features/tui-frontend.md)。

在 <http://127.0.0.1:18791/control/> 開啟 Web UI。**Health** 畫面會顯示
OpenSquilla 是否已就緒、哪些項目尚未就緒，以及下一步的復原建議。在 CLI 中，
執行：

```sh
opensquilla doctor
opensquilla doctor --json
opensquilla doctor --config ./opensquilla.toml --json
```

`/health` 與 `/healthz` 是提供給程序檢查用的輕量存活探測端點。`opensquilla
doctor` 與 Web UI 的 Health 畫面，則是檢查就緒狀態的介面，涵蓋 provider
設定、記憶、日誌、搜尋、頻道、sandbox 狀態、router、影像生成，以及復原
指引。按 `Ctrl+C` 可停止在前景執行的 gateway。

其他指令群組包括 `sessions`、`skills`、`memory`、`migrate`、`cron`、
`channels`、`providers`、`models` 與 `cost`。執行 `opensquilla --help` 或
`opensquilla <group> --help` 可查看詳情。

<details>
<summary>進階設定——驗證頻道、公開網路綁定、Docker</summary>

**連接並驗證訊息頻道**

儲存頻道設定只是變更了設定，並不代表執行期真的連得上。編輯頻道設定後，
請重新啟動 gateway，然後驗證實際運作中的頻道：

```sh
opensquilla gateway restart
opensquilla channels status <name> --json
```

只有當狀態 payload 回報 `enabled=true`、`configured=true` 且
`connected=true` 時，才能視為頻道已連線。Feishu（飛書）預設使用
websocket 模式，Telegram 預設使用輪詢（polling），Slack 則可以使用
Socket Mode——這些模式都不需要公開 URL。Feishu webhook 模式、Telegram
webhook 模式、Slack webhook 模式，以及 WeCom（企業微信），則需要一個
公開、provider 可連上的 URL。

**公開網路綁定**

若要從另一台機器連上 Web UI，請把 gateway 綁定到所有網路介面，並使用
主機的公開 IP：

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18791
```

公開存取還需要主機防火牆或雲端安全群組，允許該連接埠的傳入 TCP 流量。
請不要在 `[auth] mode = "none"` 的狀態下對外公開 gateway——在綁定到
`0.0.0.0` 之前，請先設定 token 驗證。

**Docker**

預先建置的多架構映像檔（`amd64`／`arm64`）會隨每個發布標籤，發布到
`ghcr.io/opensquilla/opensquilla`。Preview 3 同時以 `v0.5.0rc3` 與會持續
更新的 `latest` 標籤發布——完整的容器指南請見
[`docs/docker.md`](docs/docker.md)（涵蓋家用伺服器與 NAS、透過 token
驗證對外公開至區域網路，以及升級方式）：

```sh
OPENSQUILLA_GATEWAY_IMAGE=ghcr.io/opensquilla/opensquilla:latest docker compose up -d
```

如果沒有設定 `OPENSQUILLA_GATEWAY_IMAGE`，compose 路徑會執行一個你自己
建置的 `opensquilla:local` 映像檔。請從已經拉取過 Git LFS router 資產的
原始碼 checkout 來建置它（clone 與 `git lfs pull` 的做法請見
[從原始碼安裝](#從原始碼安裝)）：

```sh
docker build -t opensquilla:local .
```

接著 `./start.sh`（Windows 上為 `start.ps1`）會執行 `docker compose up -d`，
並持續追蹤 gateway 的日誌。Docker 省下的是主機端的 Python 工具鏈——並不會
省下本地端映像檔建置這個步驟。

</details>

Provider 層級、sandbox 調校、影像生成，以及並行設定，都在
`opensquilla.toml.example` 裡。

---

## 0.5.0 Preview 3 更新內容

OpenSquilla 0.5.0 Preview 3 是一次涵蓋遷移、路由、桌面版、runtime 與部署層面
的大範圍預覽更新：

- **舊主目錄遷移** — 偵測並以交易方式匯入較舊版的 CLI、桌面版、可攜式、
  已搬遷、已還原，以及 Docker volume 主目錄。
- **Provider 與路由** — 支援範圍擴增至 TokenRhythm、騰訊 TokenHub 與
  Token Plan，以及 IQS，並提供即時模型探索、探測與 context 診斷、已驗證的
  coding 預設、更豐富的 ensemble 設定，以及可選擇啟用的 router 自我學習
  迴圈。
- **桌面版、終端機與 Control UI** — 改善更新程式行為、首次設定流程、
  終端機互動、診斷、佈景主題、附件，以及聊天導覽與桌面平台整合。
- **Runtime 與安全性強化** — 強化持久化、MCP、工作階段、工具、sandbox、
  機密遮蔽（secret-redaction）、同源政策（same-origin）與 provider 重試等
  各項規範。
- **容器映像檔** — 預先建置的 `linux/amd64` 與 `linux/arm64` gateway 映像檔，
  已以 `v0.5.0rc3` 與 `latest` 標籤發布至 GHCR。
- **精簡化的發布資產** — 0.5 系列的預覽版會發布 Electron 安裝程式、更新
  程式的中繼資料、附版本號的 Python wheel，以及檢查碼；Windows 可攜式
  封裝檔仍維持停用狀態。

完整說明：[`CHANGELOG.md`](CHANGELOG.md) ·
[`docs/releases/0.5.0rc3.md`](docs/releases/0.5.0rc3.md)。

## 0.2.1 更新內容

OpenSquilla 0.2.1 是一個維護性發布版本，聚焦於發布套件的啟動流程，以及長時間
執行 Agent 的可靠性：

- **Windows 可攜式版本啟動** — 可攜式啟動器能更好地偵測並啟動內建 ONNX
  router 所需要的 Visual C++ runtime。
- **長時間執行的 Agent 輪次** — 工具密集的 WebUI 工作階段，在遇到過大的
  工具結果、格式錯誤的工具呼叫、artifact 交付的交接，以及品質下降的最終
  回應時，都能更乾淨地復原。
- **更乾淨的 WebUI 輸出** — 產生的 artifact 標記，不會出現在一般的聊天
  重播內容中，而已送達的檔案仍會維持可見。
- **記憶回想評分** — 本地端與相容 OpenAI 的 embedding 向量，會先正規化
  再進行語意搜尋；當向量分數偏低時，強關鍵字比對仍然可以使用。

完整說明：[`CHANGELOG.md`](CHANGELOG.md) ·
[發布說明](https://opensquilla.ai/news/)。

## 0.2.0 更新內容

這個版本讓 OpenSquilla 在遷移、CLI 聊天、頻道、排程，以及長時間執行的工具
工作等方面都有所擴展：

- **既有 Agent 主目錄的遷移路徑** — `opensquilla migrate` 能預覽並套用
  來自既有 OpenClaw／Hermes 主目錄的匯入，涵蓋記憶、persona 檔案、skill、
  MCP／頻道設定、衝突處理，以及遷移報告。
- **好用的聊天 CLI** — `opensquilla chat` 具備穩定的終端機介面、串流輸出、
  佇列輸入、斜線模式探索、工具／狀態列，以及更具確定性的即時提示詞行為。
- **跨介面的 cron 自動化** — cron 工作現在涵蓋結構化排程、具時區感知的
  exact／every／cron 執行方式、頻道或 webhook 送達、失敗目的地、手動執行，
  以及 WebUI／CLI／RPC 之間的一致性。
- **更完善的 Feishu 與 Discord 頻道** — 頻道 adapter 提供更清楚的能力
  中繼資料、更安全的 DM／群組處理、原生的檔案與 artifact 路徑，以及更好的
  附件與討論串的行為，同時將特權操作維持在限定範圍內。
- **更穩固的長時間執行輪次** — 失敗的輪次不會被納入 provider 重播，格式
  錯誤的工具呼叫會被更安全地處理，需要核准才能繼續的重試，會等待操作者
  的決策。
- **更聰明的 context 與工具預算控管** — provider 預算壓縮、提示詞快取
  保留、有上限的工具結果，以及具副作用意識的並行處理，讓工具密集的大型
  工作階段更可預期。
- **Web UI 與發布細節打磨** — 時序排序、表格版面、行動裝置控制項、重複
  通知、設定表單、發布 URL，以及安裝路徑，在 0.2.0 中都有收斂與強化。

完整說明：[`CHANGELOG.md`](CHANGELOG.md) ·
[發布說明](https://opensquilla.ai/news/)。

---

## 核心功能

| 能力 | 功能說明 |
| --- | --- |
| **高效運用 Token 的路由** | `SquillaRouter`——`recommended` extra 中內建的本地端 LightGBM + ONNX 分類器——會依長度、語言、程式碼、關鍵字與語意 embedding，對每一輪進行評分，接著在四個層級（C0–C3；舊版 T0–T3 名稱為其別名）之間路由到有能力處理、且最便宜的模型。分類作業在裝置端執行；做這個決策時，你的提示詞完全不會離開這台機器。 |
| **自適應推理與提示詞** | OpenSquilla 只會針對 router 評分為複雜的輪次，要求延伸推理；系統提示詞也會隨任務複雜度調整——簡單的輪次使用輕量版，複雜的輪次則使用完整指令。 |
| **20 多個 LLM provider** | provider 註冊表涵蓋 20 多個 LLM 後端——TokenRhythm、OpenRouter、OpenAI、Anthropic、Ollama、DeepSeek、Gemini、DashScope/Qwen、Moonshot、Mistral、Groq、Zhipu、SiliconFlow、vLLM、LM Studio 等等，並支援主要＋備援的選擇方式；首次執行的 onboarding 流程，只會顯示已驗證過的子集合。 |
| **依需求載入的 skill 與 MCP** | 15 個內建 skill（coding、GitHub、cron、pptx/docx/xlsx/pdf、摘要、tmux、天氣等等）只會在任務需要時才載入。OpenSquilla 是一個 MCP client，也可以作為 MCP server 執行——`opensquilla mcp-server run` 需要 `mcp` extra（安裝 `opensquilla[recommended,mcp]`）。skill 可以透過 CLI 撰寫、安裝與發布。 |
| **持久化的本地端記憶** | 由一份精選的 `MEMORY.md`，加上按日期記錄的 Markdown 筆記組成，透過 SQLite 全文關鍵字搜尋與 `sqlite-vec` 語意回想來查詢。embedding 預設透過內建的 ONNX 在裝置端執行，也可以換成 OpenAI／Ollama。另外還提供選用的指數衰減，以及選擇加入的「dream」記憶整併機制。 |
| **分層安全 sandbox** | 建立在權限矩陣上的三個政策層級（Standard／Strict／Locked）。Linux 上由 Bubblewrap 隔離程式碼執行；macOS 上則透過 Seatbelt（`sandbox-exec`）搭配產生的 SBPL profile 來執行指令；Windows 在完成設定就緒檢查後，使用原生的 `windows_default` 後端。拒絕紀錄會在多次遭拒後，自動暫停自主執行；被拒絕的輸出會被清除，而 skill 中繼資料與工具結果，都會經過 XML escape 處理，以防範 prompt injection。 |
| **內建工具** | 檔案讀取／寫入／編輯、shell 與背景處理程序、git、網路搜尋（DuckDuckGo、Bocha、Brave、IQS、Tavily 或 Exa）與具備 SSRF 防護的網頁擷取（fetch）、試算表／PPTX／PDF 製作，以及影像生成與文字轉語音。 |
| **統一的 gateway** | 一個執行於 `127.0.0.1:18791` 的 Starlette ASGI 伺服器，具備 WebSocket RPC 與內嵌的控制台（`/control/`）。Web UI、CLI，以及 Terminal、WebSocket、Slack、Telegram、Discord、Feishu（飛書）、DingTalk（釘釘）、WeCom（企業微信）、Matrix 與 QQ 等頻道，全部共用同一個 `TurnRunner`。 |
| **持久化的工作階段、子 Agent 與排程** | 以 SQLite 為後端的工作階段、逐字稿與重播內容儲存，並為每個 Agent 提供專屬工作區。Agent 可以衍生具深度上限的子 Agent；而具備內建 cron 剖析器的 `SchedulerEngine`，則會透過 `opensquilla cron` 執行週期性工作。 |
| **操作者控制項** | 人工審核（human-in-the-loop）機制，可以在敏感工具呼叫前暫停以等待決策；CLI 與 Web UI 都提供以每輪、每個工作階段為單位的 Token 與成本彙總（`opensquilla cost`），以及診斷資訊。 |

MetaSkill 延伸閱讀：[`docs/features/meta-skills.md`](docs/features/meta-skills.md)、
[`docs/features/meta-skill-user-guide.md`](docs/features/meta-skill-user-guide.md)，
以及 [`docs/authoring/meta-skills.md`](docs/authoring/meta-skills.md)。

---

## 基準測試結果

PinchBench 1.2.1 在 25 項任務上的平均結果：

| Agent | 基礎模型 | 平均分數 | 輸入 Token 總數 | 輸出 Token 總數 | 總成本 |
| --- | ---: | ---: | ---: | ---: | ---: |
| OpenSquilla | Model router（Opus4.7、GLM5.1、DS4 Flash） | 0.9251 | 1,721,328 | 61,475 | $0.688 |
| OpenClaw | Claude Opus 4.7 | 0.9255 | 3,066,243 | 50,890 | $6.233 |

分數是這 25 項任務的平均值；Token 數量與成本，則是整趟執行的總計。

---

## 疑難排解

<details>
<summary>macOS 桌面應用程式的 Dock 圖示持續跳動，或回報 AppTranslocation</summary>

如果 macOS 是從暫時性的 AppTranslocation 路徑啟動 OpenSquilla，請先關閉
OpenSquilla；如果你正在安裝它，就把應用程式拖曳到 Applications 資料夾，
退出 DMG，然後重新開啟 OpenSquilla。如果舊的 OpenSquilla 圖示仍在持續
跳動，請先強制結束舊的處理程序，再重新開啟 OpenSquilla。

</details>

<details>
<summary>macOS: <code>Library not loaded: @rpath/libomp.dylib</code></summary>

如果啟動時，從 `lightgbm/lib/lib_lightgbm.dylib` 記錄了
`Library not loaded: @rpath/libomp.dylib` 錯誤，OpenSquilla 會以直連
單一模型的路由方式繼續運作，但內建的 `SquillaRouter` runtime，會保持
未啟用狀態，直到裝好 macOS 的 OpenMP runtime 為止。

桌面應用程式已經內建了它所需要的原生 runtime。如果你是使用終端機快速安裝，
或是從 shell 執行原始碼安裝，請透過 Homebrew 安裝 `libomp`，然後重新啟動
gateway：

```sh
brew install libomp
opensquilla gateway restart
```

</details>

<details>
<summary>Windows: <code>DLL load failed</code> / Visual C++ runtime</summary>

如果啟動時記錄了 `DLL load failed while importing
onnxruntime_pybind11_state` 錯誤，OpenSquilla 會以直連單一模型的路由
方式繼續運作，但內建的 `SquillaRouter` runtime，會保持未啟用狀態，直到
裝好 Visual Studio 2015–2022（x64）適用的 Visual C++ Redistributable
為止。

從原始碼安裝用的 PowerShell 安裝程式，會嘗試透過 `winget` 安裝這個
redistributable。如果你是使用終端機快速安裝，或是 `winget` 無法使用，
請手動安裝，然後重新啟動 PowerShell：
<https://aka.ms/vs/17/release/vc_redist.x64.exe>。接著還原建議的 router：

```powershell
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY --router recommended
opensquilla gateway restart
```

</details>

---

## 致謝

OpenSquilla 的靈感來自 [OpenClaw](https://github.com/openclaw/openclaw)。
內建的第三方內容出處，記載於
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

社群貢獻者名單記載於 [`CONTRIBUTORS.md`](CONTRIBUTORS.md)，其中也包含
針對 squash-merge 或 replay 處理過的工作，所附上的特定發布版本歸屬說明。

---

## 貢獻者

感謝所有為 OpenSquilla 做出貢獻的人。

<p align="center">
  <a href="https://github.com/opensquilla/opensquilla/graphs/contributors">
    <img src="https://contrib.rocks/image?repo=opensquilla/opensquilla&max=100&columns=10" alt="OpenSquilla contributors" />
  </a>
</p>

---

## 參與貢獻

歡迎各種形式的貢獻——錯誤回報、功能構想、說明資料、新的 provider 或
channel adapter、skill，以及核心 runtime 相關工作。請見
[`CONTRIBUTING.md`](CONTRIBUTING.md)，然後到
[GitHub](https://github.com/opensquilla/opensquilla) 開議題（issue）或
提交 pull request。

[行為準則](CODE_OF_CONDUCT.md) · [安全性](SECURITY.md) ·
[隱私權](PRIVACY.md) · [程式碼簽署政策](docs/code-signing-policy.md) ·
[第三方聲明](THIRD_PARTY_NOTICES.md) · [支援](SUPPORT.md) ·
[授權條款](LICENSE) (Apache-2.0)
