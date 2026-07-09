# OpenSquilla Preview Knowledge Retrieval Capability Discovery Design

## 背景

`opensquilla-knowledge-preview` 已经具备 `baai/bge-m3` 向量索引和 hybrid 检索能力，preview 服务端 `/v1/status` 能看到：

- `vectorChunksIndexed`
- `vectorCoveragePct`
- `embeddingModel`
- `embeddingDimensions`

同时 `/v1/search` 已支持：

- `sqlite_fts5_default`
- `vector_bge_m3_1024`
- `hybrid_rrf_bge_m3_fts5`

OpenSquilla 当前通过 `KnowledgeBackend -> HttpKnowledgeBackend -> opensquilla-knowledge HTTP API` 调用知识服务，接口层已经基本能透传 `retrievalProfile`。但 OpenSquilla 的 RAG 页面和 agent 工具还停留在 FTS 时代：

- UI 只暴露 `SQLite FTS5`
- `retrievalProfile` 与 `indexProfiles` 共用一个状态变量
- UI 不展示 vector/hybrid 的状态和分数字段
- agent 工具只能通过 `filters` 隐式传入 `retrievalProfile`
- preview `[knowledge].timeout_seconds = 30.0`，对慢 vector/hybrid 查询不够

本设计优化 preview 对新检索能力的承载体验，并增加一个轻量能力发现契约：`opensquilla-knowledge` 在 `/v1/status` 中声明当前数据库可用的检索模式，OpenSquilla 动态消费该声明。设计不改 U1-U4 的 shared knowledge 链路，不新增 vector build job API。

## 目标

让 OpenSquilla preview 能正确使用并展示 `opensquilla-knowledge-preview` 的 vector/hybrid 检索能力，同时保持 U1-U4 不受影响。

具体目标：

1. `opensquilla-knowledge-preview` 在 `/v1/status` 中返回 `retrievalProfiles`，根据当前数据库状态声明 `FTS / Vector / Hybrid` 是否可用。
2. RAG 页面从 `knowledge.status` 动态读取可用检索模式，而不是在前端写死 profile 列表。
3. 拆分入库索引配置和查询检索配置，避免把 hybrid 查询策略误传为 ingest index profile。
4. RAG 页面展示向量索引状态和 hybrid/vector 结果分数字段。
5. `knowledge_search` agent 工具显式支持 `retrieval_profile` 和 `collection_id`，并提示可通过 `knowledge_status` 发现可用 profile。
6. preview gateway 的 knowledge HTTP timeout 调整为 90 秒，缓解当前 query embedding 慢导致的 30 秒超时。

## 非目标

本轮不做：

- 不新增独立 `/v1/capabilities`，本轮复用 `/v1/status`
- 不新增 vector index build HTTP job API
- 不改 `opensquilla-knowledge` shared service `18765`
- 不改 U1-U4 的 endpoint 或 timeout
- 不重构整个 RAG 页面
- 不改 embedding 模型或重新跑向量索引

## 方案选择

采用方案 A+：OpenSquilla 侧承载能力 + `opensquilla-knowledge-preview` 的轻量 status 能力发现。

理由：

- 现有 HTTP backend 已能透传 `filters`，无需重写后端适配层。
- preview 已隔离到 `18766`，可以独立验证 hybrid/vector。
- OpenSquilla RAG 页面启动时已经调用 `knowledge.status`，复用该响应比新增 `/v1/capabilities` 更小。
- 检索模式由 knowledge 服务根据数据库状态声明，避免前端和服务端能力再次耦合。
- 改动范围集中在 status contract、UI、RPC 参数透传、agent 工具 schema、preview runtime 配置。
- 避免把本轮扩大成 `opensquilla-knowledge` 服务端任务系统。

## 架构

保持当前调用链：

```text
KnowledgeView.vue
  -> gateway RPC: knowledge.search/status/get
  -> HttpKnowledgeBackend
  -> opensquilla-knowledge-preview: /v1/search /v1/status
```

这轮不让 OpenSquilla 直接读取 `knowledge.db`，不把 embedding 逻辑放进 OpenSquilla gateway。

新增或调整的数据边界：

```text
indexProfile = "sqlite_fts5_default"

retrievalProfiles = status.retrievalProfiles ?? [sqlite_fts5_default fallback]
retrievalProfile = 当前选中的 retrievalProfiles[].id
```

`knowledge.ingest` 只使用 `indexProfile`：

```json
{
  "indexProfiles": ["sqlite_fts5_default"]
}
```

`knowledge.search` 使用 `retrievalProfile`：

```json
{
  "query": "用户问题",
  "topK": 8,
  "collectionId": "datasets",
  "retrievalProfile": "hybrid_rrf_bge_m3_fts5"
}
```

## opensquilla-knowledge 能力发现设计

文件：

- `src/opensquilla_knowledge/manager.py`
- `src/opensquilla_knowledge/api.py`

`/v1/status` 继续由 `KnowledgeManager.status()` 返回 dict。本轮在该 dict 中增加：

```ts
interface RetrievalProfileStatus {
  id: string
  label: string
  kind: 'lexical' | 'vector' | 'hybrid'
  available: boolean
  reason: string | null
  model?: string
  dimensions?: number
}
```

响应示例：

```json
{
  "retrievalProfiles": [
    {
      "id": "sqlite_fts5_default",
      "label": "SQLite FTS5",
      "kind": "lexical",
      "available": true,
      "reason": null
    },
    {
      "id": "vector_bge_m3_1024",
      "label": "Vector bge-m3",
      "kind": "vector",
      "available": true,
      "reason": null,
      "model": "baai/bge-m3",
      "dimensions": 1024
    },
    {
      "id": "hybrid_rrf_bge_m3_fts5",
      "label": "Hybrid RRF",
      "kind": "hybrid",
      "available": true,
      "reason": null,
      "model": "baai/bge-m3",
      "dimensions": 1024
    }
  ],
  "defaultRetrievalProfile": "sqlite_fts5_default"
}
```

可用性计算：

- `sqlite_fts5_default`：`ftsChunksIndexed > 0` 时可用，否则 `available=false`，`reason="fts_index_empty"`。
- `vector_bge_m3_1024`：`vectorChunksIndexed > 0` 且存在 `embeddingModel/embeddingDimensions` 时可用，否则 `available=false`，`reason="vector_index_empty"`。
- `hybrid_rrf_bge_m3_fts5`：FTS 与 vector 都可用时可用；否则禁用，`reason="fts_or_vector_index_empty"`。

默认值：

- `defaultRetrievalProfile` 固定为 `sqlite_fts5_default`。
- 即使 hybrid 可用，前端也不默认选择 hybrid，避免慢 query embedding 给用户造成意外卡顿。

兼容性：

- 旧 shared service 没有 `retrievalProfiles` 字段时，OpenSquilla 前端 fallback 到单一 `sqlite_fts5_default`。
- 不新增 HTTP route，不改变现有 `/v1/search` payload。

## 前端设计

文件：

- `opensquilla-webui/src/views/KnowledgeView.vue`

### 类型扩展

`KnowledgeStatus` 增加可选字段：

```ts
vectorChunksIndexed?: number
vectorCoveragePct?: number
embeddingModel?: string
embeddingDimensions?: number
embeddingWarnings?: string[]
retrievalWarnings?: string[]
retrievalProfiles?: RetrievalProfileStatus[]
defaultRetrievalProfile?: string
```

新增类型：

```ts
interface RetrievalProfileStatus {
  id: string
  label: string
  kind: 'lexical' | 'vector' | 'hybrid'
  available: boolean
  reason: string | null
  model?: string
  dimensions?: number
}
```

`KnowledgeResult` 增加可选字段：

```ts
vectorRank?: number | null
vectorScore?: number | null
fusionScore?: number | null
```

字段全部可选，保证 U1-U4 shared service 没有这些字段时 UI 不崩。

### 状态变量

把当前单一 `retrievalProfile` 拆成：

```ts
const indexProfile = ref('sqlite_fts5_default')
const retrievalProfile = ref('sqlite_fts5_default')
```

`prepareSample()` 使用 `indexProfile`：

```ts
indexProfiles: [indexProfile.value]
```

`runSearch()` 使用 `retrievalProfile`：

```ts
retrievalProfile: retrievalProfile.value
```

### 检索模式控件

现有 `Retrieval` 下拉框改为动态渲染：

- 如果 `status.retrievalProfiles` 存在，使用服务端返回的 profile 列表。
- 如果不存在，fallback 到只包含 `SQLite FTS5 / sqlite_fts5_default` 的列表。
- `available=false` 的 profile 显示但禁用，并展示 `reason`。
- 默认选中 `status.defaultRetrievalProfile`；如果该字段不存在或不可用，则选中第一个可用 profile；如果没有任何可用 profile，则保留 `sqlite_fts5_default` 并让后端返回错误。

fallback 常量只作为旧服务兼容兜底，不作为新能力的来源。

控件仍位于现有 RAG 页面，不新增页面。

### 状态指标

当前状态卡片保留：

- RAG
- Files
- Chunks
- Questions
- Tools
- Index

新增或替换为更有价值的指标时，应保持 6 个以内，避免页面密度失控。建议把 `Index` 指标改为更能反映新能力的组合：

- `Vector`：`vectorCoveragePct`，无字段时显示 `-`
- `Embedding`：`baai/bge-m3 · 1024d`，无字段时显示 `not indexed`

如果实现中保持原 6 卡限制更方便，可以把 `Vector` 与 `Embedding` 放在 source summary 或 index hint 中，原则是 preview 页面能直接看到向量覆盖率和 embedding 模型。

### 结果展示

结果卡片不再固定写 `lexical {{ fixed(result.score) }}`。新增一个格式化 helper，根据结果字段决定展示：

- FTS：
  - 主分数：`lexical ${fixed(score)}`
  - meta：`BM25 ${fixed(bm25Rank)}`
- Vector：
  - 主分数：`vector ${fixed(vectorScore)}`
  - meta：`Vector #${vectorRank}`
- Hybrid：
  - 主分数：`fusion ${fixed(fusionScore || score)}`
  - meta：`BM25 ${fixed(bm25Rank)}`、`Vector #${vectorRank}`、`Vector score ${fixed(vectorScore)}`

### 慢查询提示

`searching` 状态保留。显示文案按 profile 区分：

- FTS：`Searching`
- Vector/Hybrid：`Embedding retrieval`

这轮不实现取消、轮询或请求进度条。

## Gateway RPC 设计

文件：

- `src/opensquilla/gateway/rpc_knowledge.py`

`knowledge.status` 不需要新增 RPC 方法；OpenSquilla 继续通过现有 `knowledge.status` 获取 status dict，并把新增字段原样返回给 UI。

`knowledge.search` 保持现有行为，并增加顶层参数透传：

- `embeddingModel`
- `embeddingDimensions`
- `model`
- `dimensions`

合并规则：

- `filters` 仍可传任意服务端支持字段。
- 顶层字段优先覆盖 `filters` 中的同名字段。
- `collectionId` 和 `retrievalProfile` 的现有行为不变。

这让 UI 和后续调用方可以显式设置 embedding 参数，而不需要直接构造 filters。

## Agent 工具设计

文件：

- `src/opensquilla/tools/builtin/knowledge_tools.py`

`knowledge_status` 描述更新为：可用于查看知识库状态和可用 retrieval profile。

`knowledge_search` 新增参数：

```text
collection_id?: string
retrieval_profile?: string
```

保留 `collection` 参数兼容旧调用。合并规则：

1. 从 `filters` 复制出新 dict，避免原地修改调用方对象。
2. 如果 `collection_id` 存在，写入 `filters.collectionId`。
3. 如果只有 `collection` 存在，也写入 `filters.collectionId`。
4. 如果 `retrieval_profile` 存在，写入 `filters.retrievalProfile`。
5. 调用 `resolved_manager.search(clean_query, top_k=top_k, filters=merged_filters)`。

工具描述中列出支持的 profile：

- 推荐先调用 `knowledge_status` 查看 `retrievalProfiles`。
- 常见 profile 包括 `sqlite_fts5_default`、`vector_bge_m3_1024`、`hybrid_rrf_bge_m3_fts5`，但最终以 `knowledge_status` 返回为准。

## Preview 配置设计

只改 preview runtime：

- `/srv/opensquilla-demo/instances/preview/runtime-gateway.toml`

调整：

```toml
[knowledge]
timeout_seconds = 90.0
```

不改：

- `/srv/opensquilla-demo/instances/u1/runtime-gateway.toml`
- `/srv/opensquilla-demo/instances/u2/runtime-gateway.toml`
- `/srv/opensquilla-demo/instances/u3/runtime-gateway.toml`
- `/srv/opensquilla-demo/instances/u4/runtime-gateway.toml`
- `/etc/systemd/system/opensquilla-demo@.service`

修改后只重启：

```bash
systemctl restart opensquilla-demo@preview
```

## 错误处理

1. UI 复用现有 `error` 区域展示 RPC/HTTP 错误。
2. Vector/Hybrid 查询失败时，用户看到现有错误提示，不新增复杂错误面板。
3. U1-U4 服务无 vector 字段时，前端使用 fallback 展示，不报错。
4. 本轮不处理服务端 warning 展示；如果服务端返回 `warnings`，后续可以在结果区增加提示条。
5. 慢查询通过 preview timeout 临时缓解，不在本轮实现取消/轮询。

## 测试设计

### Python 测试

文件：

- `opensquilla-knowledge-preview/tests/...`
- `tests/test_knowledge/test_rpc_knowledge.py`
- `tests/test_knowledge/test_tools.py`
- `tests/test_knowledge/test_http_backend.py`

测试点：

1. `opensquilla-knowledge-preview` 的 `status()` 在无向量索引时返回 FTS fallback profile，并把 vector/hybrid 标记为不可用。
2. `opensquilla-knowledge-preview` 的 `status()` 在存在向量索引时返回 vector/hybrid 可用 profile，包含 model/dimensions。
3. OpenSquilla `knowledge.search` 会把 `retrievalProfile`、`embeddingModel`、`embeddingDimensions` 合并进 filters。
4. 顶层 search 参数优先覆盖 filters 中同名字段。
5. `knowledge_search` 工具会把 `collection_id` / `collection` / `retrieval_profile` 转成 backend filters。
6. `HttpKnowledgeBackend.search()` 继续发送 `{query, topK, filters}`，避免协议回退。

### 前端测试

文件建议：

- `opensquilla-webui/src/views/KnowledgeView.retrieval.test.ts`

如果直接 mount `KnowledgeView.vue` 成本过高，则先抽出轻量 helper：

- `opensquilla-webui/src/views/knowledgeRetrieval.ts`

helper 负责：

- 从 `status.retrievalProfiles` 派生 retrieval profile 选项列表
- status metric fallback
- result score label/meta formatting

测试点：

1. status 返回 `retrievalProfiles` 时，profile 选项完全来自服务端。
2. status 不返回 `retrievalProfiles` 时，profile 选项 fallback 到 FTS。
3. `available=false` 的 profile 被禁用并保留 reason。
4. ingest payload 使用 `indexProfile`，不使用 hybrid/vector retrieval profile。
5. search payload 使用当前 `retrievalProfile`。
6. hybrid 结果格式化包含 `fusionScore`、`bm25Rank`、`vectorRank`。
7. vector 结果格式化包含 `vectorScore`、`vectorRank`。
8. 缺少 vector status 字段时 fallback 不报错。

## 验证命令

Python：

```bash
cd /root/Q3WORK/opensquilla-knowledge-preview
pytest tests -q
```

```bash
cd /root/Q3WORK/opensquilla-knowledge-rag-phase01
pytest tests/test_knowledge/test_rpc_knowledge.py tests/test_knowledge/test_tools.py tests/test_knowledge/test_http_backend.py -q
```

前端：

```bash
cd /root/Q3WORK/opensquilla-knowledge-rag-phase01/opensquilla-webui
npm run test:unit -- KnowledgeView
npm run typecheck
```

preview 配置：

```bash
grep -nA8 -B2 '^\[knowledge\]' /srv/opensquilla-demo/instances/preview/runtime-gateway.toml
grep -nA8 -B2 '^\[knowledge\]' /srv/opensquilla-demo/instances/u1/runtime-gateway.toml
systemctl restart opensquilla-demo@preview
systemctl is-active opensquilla-demo@preview opensquilla-demo@u1 opensquilla-demo@u2 opensquilla-demo@u3 opensquilla-demo@u4
```

服务探针：

```bash
curl -fsS http://127.0.0.1:18766/v1/status | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:18766/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"苹果公司收入","topK":2,"filters":{"collectionId":"datasets","retrievalProfile":"sqlite_fts5_default"}}' \
  | python3 -m json.tool
```

Hybrid/vector direct probe 可能仍受 OpenRouter 延迟影响，本轮不把其稳定低延迟作为完成条件；完成条件是 OpenSquilla 能正确表达参数、展示字段、preview timeout 已放宽。

## 发布和回滚

发布：

1. 在 `opensquilla-knowledge-rag-phase01` 分支完成代码改动并提交。
2. 构建前端静态资源。
3. 更新 preview 当前工作目录。
4. 调整 preview runtime timeout。
5. 重启 `opensquilla-demo@preview`。

回滚：

1. 回退 OpenSquilla 代码提交。
2. 恢复 preview `timeout_seconds = 30.0`。
3. 重启 `opensquilla-demo@preview`。

U1-U4 未改 endpoint、服务模板或 runtime，因此不需要客户侧回滚动作。

## 成功标准

1. preview RAG 页面能选择 FTS、Vector、Hybrid。
2. 检索模式来自 `/v1/status.retrievalProfiles`；旧服务没有该字段时自动 fallback 到 FTS。
3. 不可用 profile 能显示但禁用，并展示原因。
4. 点击构建知识库时，只发送 `indexProfiles: ["sqlite_fts5_default"]`。
5. 点击搜索时，发送当前 `retrievalProfile`。
6. preview 页面能展示 vector coverage 和 embedding model。
7. hybrid/vector 返回结果时，页面能展示对应分数和 rank 字段。
8. agent 工具 schema 明确暴露 `collection_id` 和 `retrieval_profile`，并提示用 `knowledge_status` 发现可用 profile。
9. preview timeout 为 90 秒，U1-U4 timeout 和 endpoint 不变。
10. 相关 Python 测试、前端单测、前端 typecheck 通过。
