<!-- 譯自 ../usage-and-cost.md @ 8e84dc04；過期檢查：git log 8e84dc04..HEAD -- docs/usage-and-cost.md -->

# 用量與成本

> 本文件譯自 [`usage-and-cost.md`](../usage-and-cost.md)，內容以英文版為準。

OpenSquilla 會記錄執行中閘道器回報的 token 用量與預估成本。
在經過路由、大量使用工具、透過頻道，或長上下文的工作結束之後，
可使用成本檢視功能，了解模型花費流向何處。

## 需求

成本檢視功能會使用閘道器：

```sh
opensquilla gateway status
```

如果閘道器尚未執行：

```sh
opensquilla gateway run
```

## 顯示成本

```sh
opensquilla cost
```

預設檢視畫面會列出以工作階段／模型為單位的資料列，內含輸入 token 數、輸出
token 數與預估成本。

## 依模型分組

```sh
opensquilla cost --by-model
```

當你啟用了 SquillaRouter，並想知道近期工作負載主要由哪些模型承擔時，可使用
此選項。

## 使用 JSON 輸出

```sh
opensquilla cost --json
opensquilla cost --by-model --json
```

JSON 輸出適合用於本機儀表板、回歸檢查與自動化報告。

## 優先檢查項目

| 訊號 | 可能代表的意義 |
| --- | --- |
| 出現大量高階模型的資料列 | 路由政策或任務型態，可能比預期更頻繁地升級到高階模型。 |
| 輸入 token 數偏高 | 過長的歷史紀錄、龐大的工具結果，或龐大的提示詞／工具 schema，可能是成本的主要來源。 |
| 輸出 token 數偏高 | 該任務可能需要更精簡的指令，或更小的回應格式。 |
| 成本集中在單一工作階段 | 在變更全域設定之前，先檢查該工作階段。 |

## 安全地降低成本

從路由與診斷開始：

```sh
opensquilla configure router --router recommended
opensquilla diagnostics on
opensquilla cost --by-model
```

如果工具結果過於龐大，請參閱：

- [`features/tool-compression.md`](../features/tool-compression.md)
- [`features/compaction-and-cache.md`](../features/compaction-and-cache.md)

若是簡單的一次性自動化工作，請為執行過程設定上限：

```sh
opensquilla agent --max-iterations 20 --timeout 600 -m "Bounded task"
```

## 注意事項與限制

- 除非供應商本身回報了計費金額，否則成本都是根據記錄下來的執行期用量與設定
  的定價所做的估算。每一列的 `costSource`（`provider_billed` /
  `opensquilla_estimate` / `mixed` / `unavailable`）會標示你看到的是哪一種
  數字；完整的定價與來源模型，請參閱
  [`providers-and-models.md`](./providers-and-models.md#定價與成本估算)。
- 供應商帳單仍是實際費用的權威依據。
- 工具壓縮與路由可以降低模型的上下文成本，但應該同時檢查任務是否成功完成，
  而不是只看 token 總量。
- 診斷功能可以說明某一輪對話為何被路由、被壓縮、被重試，或產生了異常龐大
  的輸出。

接下來可以閱讀：

- [`features/squilla-router.md`](../features/squilla-router.md)
- [`features/tool-compression.md`](../features/tool-compression.md)
- [`diagnostics-and-replay.md`](../diagnostics-and-replay.md)

---

[說明索引](./README.md) · [產品指南](../../README.product.zh-Hant.md) · [協助改善本頁](../contributing-docs.md) · [回報文件問題](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
