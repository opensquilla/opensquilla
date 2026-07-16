# RAG Tool Concurrency Design

## Context

OpenSquilla already batches same-turn tools whose concurrency policy is not
`mutex`, with a global `max_safe_tool_concurrency` default of 6. The external
RAG tools were added without a concurrency policy, so `knowledge_search` and
`knowledge_get` inherit the fail-closed mutex default.

The deployed Knowledge Provider also defines `async` Starlette handlers that
call synchronous Provider service methods directly. A real two-request lexical
probe showed the first request completing in 0.436 seconds and the second in
0.882 seconds, with 0.883 seconds total, proving that the Provider event loop
serializes the requests. A same-turn Agent probe likewise showed
`knowledge_search` plus `knowledge_get` taking 0.575 seconds without overlap,
while the Web control pair completed in 0.252 seconds with full overlap.

The Provider is not purely read-only: Search upserts stable evidence records,
Get creates cursor records, and the shared Faiss backend lazily builds a large
in-memory cache. Concurrency therefore must be bounded and the cold cache build
must be single-flight.

## Goal

Execute independent same-turn `knowledge_search` and `knowledge_get` calls
concurrently end to end, with explicit operation limits, without duplicating a
cold Faiss build or weakening existing protocol, projection, persistence, and
non-RAG behavior.

## Non-Goals

- Do not force the model to emit multiple tool calls. This change accelerates
  multiple calls when the model already emits them.
- Do not change the RAG Provider Protocol or the Search/Get payload schemas.
- Do not parallelize the lexical and vector branches inside one hybrid Search
  in this iteration. Their benefit should be benchmarked separately.
- Do not change result ordering: ToolResult events and model replay remain in
  the original tool-call order after the concurrent batch completes.
- Do not increase cross-turn task concurrency or modify non-RAG tool policies.

## Design

### 1. OpenSquilla tool policies

Add explicit policies in `src/opensquilla/engine/runtime.py` rather than putting
the RAG tools in the unrestricted safe-name set:

- `knowledge_search`: `mode="concurrent"`, `max_inflight=2`,
  `limit_key=("knowledge", "search")`.
- `knowledge_get`: `mode="concurrent"`, `max_inflight=4`,
  `limit_key=("knowledge", "get")`.

The existing Agent batch scheduler and global semaphore remain unchanged.
Consecutive Knowledge calls can overlap, but a mutex tool still acts as an
ordering barrier. Search and Get have separate operation limits while the
existing global same-turn cap of 6 bounds their combined fan-out.

### 2. Knowledge Provider thread offload and limits

Keep `RagProviderService.search()` and `.get()` synchronous. In
`src/opensquilla_knowledge/api.py`, execute them through Starlette's threadpool
instead of blocking the event loop.

Use application-local async semaphores:

- shared RAG operation limit: 4;
- Search limit: 2;
- Get limit: 4.

Every operation acquires the shared limiter and its operation limiter before
entering the threadpool. Existing authorization, JSON parsing, exception
mapping, response schemas, and HTTP status behavior remain unchanged.

This allows health/capabilities and independent RAG requests to make progress
while a Search is running, while preventing the Provider from using the
threadpool without bounds.

### 3. Faiss cold-cache single-flight

Protect each `(model, dimensions, vector_filter)` cache key in
`FaissHnswVectorSearchBackend` with a `threading.Lock`.

The cache lookup remains lock-free on a valid warm hit. On a miss or stale
entry:

1. obtain the per-key lock;
2. recompute vector state and recheck the cache;
3. build and publish the cache entry only if it is still missing/stale.

Concurrent cold requests therefore build one HNSW index and reuse it. Searches
for unrelated cache keys do not share a global build lock.

### 4. SQLite behavior

Retain per-operation SQLite connections. The deployed database already uses
WAL and a 5000 ms busy timeout. Evidence upserts and cursor inserts remain
transactional and may serialize at SQLite's single-writer boundary, but they do
not serialize the complete Search/Get operation.

Concurrency tests must exercise the real evidence/cursor write paths to catch
`database is locked`, duplicate identity, or cursor corruption regressions.

## Error and Cancellation Semantics

- Existing Provider error mapping remains unchanged.
- A cancelled HTTP client does not forcibly terminate a synchronous worker
  already running; the bounded semaphores limit such orphaned work.
- One failed concurrent tool does not cancel independent siblings; each call
  produces its own existing ToolResult error shape.
- Timeout and result emission behavior in the Agent remains unchanged.

## Testing

### OpenSquilla

- Policy tests assert the exact Search/Get modes, keys, and limits.
- Same-turn timing tests prove two Knowledge calls overlap.
- Search cap tests prove at most two Search handlers are in flight.
- Get cap tests prove at most four Get handlers are in flight.
- Mixed mutex ordering tests prove existing barriers remain intact.
- Existing Web, generic no-op, result projection, delivery, and persistence
  tests remain green.

### OpenSquilla-Knowledge

- ASGI tests issue simultaneous Search requests against a blocking fake manager
  and prove overlap plus the Search cap.
- Get concurrency tests use real evidence and cursor storage and prove valid
  independent results without SQLite lock errors.
- A health request remains responsive while Search work is in the threadpool.
- Faiss tests start concurrent cold searches for the same key and assert one
  matrix/index build and identical results.
- Existing Provider protocol, service, API, evidence, reader, retrieval, and
  collection-scope tests remain green.

### Contract smoke

After focused tests, run a transient production-equivalent Provider and issue
two concurrent lexical Search requests and two concurrent Get requests. Verify
wall-clock overlap, payload contracts, cursor validity, bounded in-flight work,
and cleanup.

## Deployment

Deploy Knowledge first so the Provider can accept concurrency before Open starts
issuing concurrent requests. Preserve the existing SQLite backup and rollback
