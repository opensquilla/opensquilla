<!-- 譯自 ../approvals-and-permissions.md @ 8e84dc04；過期檢查：git log 8e84dc04..HEAD -- docs/approvals-and-permissions.md -->

# 核准與權限

> 本文件譯自 [`approvals-and-permissions.md`](../approvals-and-permissions.md)，內容以英文版為準。

核准與權限控制 OpenSquilla 工具被允許執行的動作方式。當 agent 可以寫入檔案、
執行 shell 命令、發布 artifact、發文到頻道，或呼叫外部服務時，這些機制格外重要。

在執行無人值守的自動化作業，或授予頻道串接的 agent 廣泛工具存取權限之前，
請先閱讀本頁。

## 權限設定檔

單次執行的自動化作業，可以接受明確指定的權限設定檔：

```sh
opensquilla agent --permissions restricted -m "Inspect this repo"
opensquilla agent --permissions on -m "Run with host execution and approvals"
opensquilla agent --permissions bypass -m "Trusted local automation"
opensquilla agent --permissions full -m "Fully trusted local automation"
```

實際意義：

| 設定檔 | 適用情境 |
| --- | --- |
| `restricted` / `off` | 任務應保持保守，避免使用提升權限的執行方式。 |
| `on` | 允許主機端執行，但核准檢查仍然有效。 |
| `bypass` | 你信任這項任務，足以自動授予核准，但仍保留敏感路徑檢查。 |
| `full` | 你完全信任這項任務與環境。請謹慎使用。 |

在自動化情境中，請優先選用範圍最小、仍可完成任務的設定檔。

## 工作區限制

為檔案與 shell 相關工作設定一個工作區：

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-strict \
  -m "Summarize this repo"
```

將寫入動作限制在工作區或暫存目錄內：

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-lockdown \
  --scratch-dir /path/to/project/.scratch \
  -m "Investigate and prepare a minimal patch"
```

當無人值守的執行作業，不允許在專案之外發生任何意外寫入時，請使用
`--workspace-lockdown`。

## 互動式核准

互動式聊天介面可以在需要人工決策時，暫停敏感的工具呼叫。由 gateway 驅動的
終端機聊天支援：

```text
/approvals
/approvals reset
/permissions status
/permissions on
/permissions off
/permissions bypass
/permissions full
/forget
```

當你需要在聊天過程中檢視或重設已快取的核准決定時，可使用這些指令。

Web UI 也提供了核准介面，讓你可以在訊息捲動紀錄之外，檢視待處理的動作。

## Sandbox 狀態

檢視 sandbox 狀態：

```sh
opensquilla sandbox status
opensquilla sandbox status --json
```

設定狀態：

```sh
opensquilla sandbox on
opensquilla sandbox bypass
opensquilla sandbox full
opensquilla sandbox reset
```

變更全域 sandbox 狀態後，請重新啟動 gateway：

```sh
opensquilla gateway restart
```

## 建議預設值

| 情境 | 建議做法 |
| --- | --- |
| 第一次在某個儲存庫中執行 | `--workspace` 搭配 `--workspace-strict` |
| 唯讀調查 | `--permissions restricted` |
| 搭配測試的本地修補 | `--workspace-lockdown` 搭配一個暫存目錄 |
| 會寫入資料的 Web UI 任務 | 保持核准畫面可見，並審查敏感動作 |
| 頻道串接的 agent | 保守的權限設定，加上明確的頻道設定 |
| 無人值守的自動化作業 | 限制逾時／疊代次數，並選用範圍最窄、仍可運作的權限 |

## 疑難排解

如果工具遭拒：

```sh
opensquilla sandbox status
opensquilla doctor
```

接著檢查：

- 該介面是否支援即時核准；
- 工作區路徑是否正確；
- 是否需要重設已快取的核准；
- 這項任務是否應該用不同的權限設定檔來執行。

延伸閱讀：

- [`tools-and-sandbox.md`](./tools-and-sandbox.md)
- [`web-ui.md`](./web-ui.md)
- [`channels.md`](./channels.md)

---

[文件索引](./README.md) · [產品指南](../../README.product.zh-Hant.md) · [改善本頁](../contributing-docs.md) · [回報文件問題](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
