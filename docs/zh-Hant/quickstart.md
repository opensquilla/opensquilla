<!-- 譯自 docs/quickstart.md @ 8e84dc04；過期檢查：git log 8e84dc04..HEAD -- docs/quickstart.md -->

# 快速入門

> 本文件譯自 [`quickstart.md`](../quickstart.md)，內容以英文版為準。

本指南協助你在本地端完成 OpenSquilla 的安裝、設定與執行。內容假設你想要標準的產品
體驗：終端機指令、本地端 Web UI、SquillaRouter、記憶／搜尋支援，以及安全的本地端
預設值。

## 需求

- 終端機安裝需要 Python 3.12 以上版本。
- 建議的終端機安裝方式需要 `uv`。
- 只有從原始碼安裝時才需要 Git 與 Git LFS。
- 除非你使用像 Ollama 這樣的本地端 provider，否則需要 provider 的 API key。

## 建議安裝方式

使用建議的 extras 安裝目前發布版本的 wheel：

```sh
uv tool install --python 3.12 "opensquilla[recommended] @ https://github.com/opensquilla/opensquilla/releases/download/v0.5.0rc3/opensquilla-0.5.0rc3-py3-none-any.whl"
```

`recommended` extra 包含 SquillaRouter 的依賴套件，以及預設產品體驗所使用的
記憶／搜尋支援。

如果安裝後找不到 `opensquilla`，請開啟新的 shell，或執行：

```sh
uv tool update-shell
```

## 首次執行設定

互動式設定：

```sh
opensquilla onboard
```

適合腳本使用的設定方式：

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

其他實用的變化用法：

```sh
opensquilla onboard --if-needed
opensquilla onboard --minimal
opensquilla onboard --provider openai --api-key-env OPENAI_API_KEY
opensquilla onboard --provider ollama --model llama3.1
```

`--if-needed` 對安裝腳本來說是安全的，因為它不會覆寫已經就緒的設定。`--minimal`
只會設定 provider 路徑，並略過選用的頻道／搜尋／影像生成區塊。

檢查 onboarding 狀態：

```sh
opensquilla onboard status
```

## 執行 Gateway

前景執行 gateway：

```sh
opensquilla gateway run
```

背景執行 gateway 並等待就緒：

```sh
opensquilla gateway start --json
opensquilla gateway status
```

預設位址：

```text
http://127.0.0.1:18791/control/
```

為了安全，gateway 預設綁定在 loopback。若要綁定到其他位址，需要主動選用：

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18791
```

只有在具備適當的驗證與網路控管措施時，才能對外開放非 loopback 的 gateway。

## 第一次實際使用

開啟 Web UI：

```text
http://127.0.0.1:18791/control/
```

啟動終端機聊天：

```sh
opensquilla chat
```

執行一次自動化回合：

```sh
opensquilla agent -m "Inspect this workspace and suggest a test plan"
```

在指定的工作區中執行一次性任務：

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-strict \
  -m "Review the current diff and list the highest-risk changes"
```

使用 Web UI 進行以瀏覽器為基礎的聊天、核准、設定、頻道、使用量與日誌操作。想要
終端機對話時，請使用 `opensquilla chat`。一次性自動化任務則使用
`opensquilla agent`。

## 繼續先前的工作

繼續先前的終端機聊天工作階段：

```sh
opensquilla chat --session <session-key>
```

檢視工作階段：

```sh
opensquilla sessions list
opensquilla sessions show <session-key>
opensquilla sessions export <session-key>
```

當偵錯或交接需要精確的歷史紀錄時，請匯出工作階段。

## 檢查就緒狀態

完成設定後執行以下指令：

```sh
opensquilla doctor
opensquilla providers list
opensquilla search list
opensquilla channels types --json
```

如果 gateway 正在執行中，請檢視 runtime 狀態：

```sh
opensquilla gateway status
opensquilla providers status
opensquilla channels status
opensquilla memory status
```

關於 provider／模型選擇的詳細說明，請見
[`providers-and-models.md`](./providers-and-models.md)。關於搜尋設定，請見
[`search.md`](../search.md)。

關於 gateway 生命週期、host／port 與對外開放的指引，請見
[`gateway.md`](./gateway.md)。

## 停止或重新啟動

前景執行的 gateway：

```text
Ctrl+C
```

受管理的背景 gateway：

```sh
opensquilla gateway stop
opensquilla gateway restart
```

## 下一步

完成第一次執行後：

1. 如果想要進行網路研究，請設定搜尋功能：[`search.md`](../search.md)。
2. 如果想要使用 Slack、Telegram、Feishu／Lark 或其他訊息平台，請啟用頻道：
   [`channels.md`](./channels.md)。
3. 如果想要持久化回想能力，請檢視記憶行為：
   [`features/memory.md`](../features/memory.md)。
4. 在進行無人值守的自動化之前，請先檢視工具權限：
   [`tools-and-sandbox.md`](./tools-and-sandbox.md)。
5. 如果想要具備成本意識的模型路由，請瞭解 SquillaRouter：
   [`features/squilla-router.md`](../features/squilla-router.md)。
6. 如果對產品術語不熟悉，請參考詞彙表：[`glossary.md`](./glossary.md)。

## 從原始碼安裝

想要以 checkout 為基礎進行安裝時，請使用原始碼安裝：

```sh
git lfs install
git clone https://github.com/opensquilla/opensquilla.git
cd opensquilla
git lfs pull --include="src/opensquilla/squilla_router/models/**"
bash scripts/install_source.sh
```

若要進行開發，請使用 repository 的虛擬環境：

```sh
uv sync --extra recommended --extra dev
uv run opensquilla --help
uv run opensquilla gateway run
```

從原始碼開發時，請在指令前加上 `uv run`，讓指令使用你正在編輯的 checkout。

---

[說明索引](./README.md) · [產品指南](../../README.product.zh-Hant.md) ·
[改善這個頁面](../contributing-docs.md) ·
[回報文件問題](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
