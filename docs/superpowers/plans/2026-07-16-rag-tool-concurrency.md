# RAG Tool Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make independent same-turn `knowledge_search` and `knowledge_get` calls execute concurrently end to end with bounded operation limits and one Faiss cold build per cache key.

**Architecture:** OpenSquilla assigns explicit concurrent policies to the two RAG tools while preserving the existing global same-turn semaphore and result ordering. OpenSquilla-Knowledge offloads synchronous Search/Get work from the Starlette event loop into a bounded threadpool path, and the Faiss backend uses a per-key double-checked lock for cold cache construction.

**Tech Stack:** Python 3.12, asyncio, Starlette/AnyIO threadpool, httpx, SQLite WAL, Faiss HNSW, pytest/pytest-asyncio, Git worktrees, systemd.

## Global Constraints

- Work only through `ssh aliyun-ecs`.
- Base Open changes on `8eb7bf45a06edddccee7ae52af72e5e8e8150ba3`.
- Base Knowledge changes on `ba5ee203e87c66e134da8ec625766d4c20ddc4f3`.
- Do not modify the active Preview candidates in place.
- Do not change Protocol 1.0/1.1 schemas, Model Projections, Source Sidecars, result ordering, or non-RAG tool policies.
- `knowledge_search` maximum same-turn in-flight count is 2.
- `knowledge_get` maximum same-turn in-flight count is 4.
- Provider shared RAG operation capacity is 4; Provider Search capacity is 2; Provider Get capacity is 4.
- Do not parallelize lexical and vector branches inside one hybrid Search.
- Do not force a model provider to emit parallel tool calls.
- Use RED-GREEN TDD for every production change.
- Run only focused tests, changed-file Ruff, contract smoke, and focused post-deploy checks; do not run full regression suites.
- Deploy Knowledge before Open, preserving existing backups and rollback candidates.

---

### Task 1: OpenSquilla bounded Knowledge tool policies

**Files:**
- Modify: `src/opensquilla/engine/runtime.py`
- Modify: `tests/test_engine/test_tool_concurrency.py`

**Interfaces:**
- Consumes: `_ToolConcurrencyPolicy`, `_get_tool_concurrency_policy()`, and the Agent concurrent batch scheduler.
- Produces: exact policies for `knowledge_search` and `knowledge_get`.

- [ ] **Step 1: Add failing policy tests**

Add tests equivalent to:

```python
def test_knowledge_search_has_bounded_concurrent_policy() -> None:
    policy = _get_tool_concurrency_policy("knowledge_search", {"query": "alpha"})
    assert policy.mode == "concurrent"
    assert policy.max_inflight == 2
    assert policy.limit_key == ("knowledge", "search")


def test_knowledge_get_has_bounded_concurrent_policy() -> None:
    policy = _get_tool_concurrency_policy("knowledge_get", {"evidence_id": "ev-a"})
    assert policy.mode == "concurrent"
    assert policy.max_inflight == 4
    assert policy.limit_key == ("knowledge", "get")
```

- [ ] **Step 2: Add failing execution tests**

Use the existing fixed-tool-call providers and interval helpers to add:

```python
@pytest.mark.asyncio
async def test_same_turn_knowledge_search_and_get_overlap() -> None:
    # Handler sleeps for _TOOL_SLEEP_S and records start/end.
    # Assert total elapsed is below 1.5 * _TOOL_SLEEP_S and intervals overlap.


@pytest.mark.asyncio
async def test_knowledge_search_concurrency_is_capped_at_two() -> None:
    # Emit four knowledge_search calls and count in-flight handlers.
    # Assert max_in_flight == 2 and elapsed requires two waves.


@pytest.mark.asyncio
async def test_knowledge_get_concurrency_is_capped_at_four() -> None:
    # Emit six knowledge_get calls and count in-flight handlers.
    # Assert max_in_flight == 4 and elapsed requires two waves.
```

The tests must use distinct tool-use IDs; repeated tool names are allowed in the fixed provider.

- [ ] **Step 3: Run RED tests**

Run:

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m pytest -q \
  tests/test_engine/test_tool_concurrency.py \
  -k "knowledge_search or knowledge_get or same_turn_knowledge"
```

Expected: the policy tests report `mutex`; the timing/cap tests fail because calls do not overlap.

- [ ] **Step 4: Implement minimal policies**

Add:

```python
_KNOWLEDGE_SEARCH_TOOL_POLICY = _ToolConcurrencyPolicy(
    mode="concurrent",
    max_inflight=2,
    limit_key=("knowledge", "search"),
)
_KNOWLEDGE_GET_TOOL_POLICY = _ToolConcurrencyPolicy(
    mode="concurrent",
    max_inflight=4,
    limit_key=("knowledge", "get"),
)
```

In `_get_tool_concurrency_policy()` return the exact policy for each tool before the default mutex return. Do not add the names to `_SAFE_TOOL_NAMES`.

- [ ] **Step 5: Run GREEN tests and existing concurrency controls**

Run:

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m pytest -q tests/test_engine/test_tool_concurrency.py
```

Expected: all tests pass, including Web concurrency and mutex ordering controls.

- [ ] **Step 6: Ruff, diff check, commit**

```bash
/root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m ruff check src/opensquilla/engine/runtime.py tests/test_engine/test_tool_concurrency.py
git diff --check
git add src/opensquilla/engine/runtime.py tests/test_engine/test_tool_concurrency.py
git commit -m "feat(rag): run knowledge tools concurrently"
```

---

### Task 2: Knowledge Provider thread offload and operation limits

**Files:**
- Modify: `src/opensquilla_knowledge/api.py`
- Modify: `tests/test_rag_provider_api.py`

**Interfaces:**
- Consumes: synchronous `RagProviderService.search(raw)` and `.get(raw)`.
- Produces: async route execution through bounded threadpool calls.

- [ ] **Step 1: Add a blocking test manager**

Extend the API test helpers with a manager whose `search()`:

```python
def search(self, query: str, *, top_k: int, filters: dict | None = None) -> dict:
    with self._lock:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
    try:
        time.sleep(self.delay)
        return {
            "query": query,
            "totalMatched": 0,
            "results": [],
            "retrievalProfile": "sqlite_fts5_default",
        }
    finally:
        with self._lock:
            self.in_flight -= 1
```

Use `threading.Lock`, not an asyncio-only counter, because the desired implementation runs in worker threads.

- [ ] **Step 2: Add failing ASGI overlap and capacity tests**

Using `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`, add:

```python
@pytest.mark.asyncio
async def test_rag_search_requests_overlap_without_blocking_event_loop() -> None:
    # Send two valid lexical search bodies concurrently.
    # Assert manager.max_in_flight == 2 and total wall time is below
    # 1.5 * the two-call serial duration.


@pytest.mark.asyncio
async def test_rag_search_capacity_is_two() -> None:
    # Send four searches concurrently.
    # Assert manager.max_in_flight == 2.


@pytest.mark.asyncio
async def test_health_remains_responsive_while_search_runs() -> None:
    # Start a delayed Search, wait until manager.started is set, then call
    # /healthz. Assert health returns before Search finishes.
```

- [ ] **Step 3: Add failing concurrent Get/cursor test**

Use the existing real temporary Knowledge database and evidence fixture:

```python
@pytest.mark.asyncio
async def test_concurrent_rag_get_requests_create_valid_independent_cursors() -> None:
    # Create one evidence record whose document requires pagination.
    # Send two Get requests concurrently for that evidence.
    # Assert both return 200, contentChars is correct, and every returned
    # cursor can be consumed by a follow-up Get.
```

This test must fail before thread offload by observing `max_in_flight == 1` through an instrumented reader or by the same timing pattern.

- [ ] **Step 4: Run RED tests**

Run only the new test names:

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-preview/.venv-preview/bin/python \
  -m pytest -q tests/test_rag_provider_api.py \
  -k "overlap_without_blocking or capacity_is_two or health_remains_responsive or concurrent_rag_get"
```

Expected: Search requests are serialized, health waits behind Search, and the Get overlap assertion fails.

- [ ] **Step 5: Implement bounded thread offload**

Import:

```python
import asyncio
from collections.abc import Callable
from typing import TypeVar
from starlette.concurrency import run_in_threadpool
```

Inside application construction create:

```python
rag_operation_slots = asyncio.Semaphore(4)
rag_search_slots = asyncio.Semaphore(2)
rag_get_slots = asyncio.Semaphore(4)
```

Add a local helper:

```python
T = TypeVar("T")

async def run_rag_operation(
    operation_slots: asyncio.Semaphore,
    function: Callable[..., T],
    *args: object,
) -> T:
    async with rag_operation_slots:
        async with operation_slots:
            return await run_in_threadpool(function, *args)
```

Change only Search/Get service invocation:

```python
body = await rag_body(request)
result = await run_rag_operation(rag_search_slots, get_rag_provider().search, body)
return JSONResponse(result)
```

and the equivalent Get path with `rag_get_slots`. Capabilities remains direct and fast.

- [ ] **Step 6: Run GREEN and API contract tests**

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-preview/.venv-preview/bin/python \
  -m pytest -q \
  tests/test_rag_provider_api.py \
  tests/test_rag_provider_service.py \
  tests/test_rag_provider_protocol.py
```

Expected: concurrency tests and all existing API/service/protocol tests pass.

- [ ] **Step 7: Ruff, diff check, commit**

```bash
/root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m ruff check src/opensquilla_knowledge/api.py tests/test_rag_provider_api.py
git diff --check
git add src/opensquilla_knowledge/api.py tests/test_rag_provider_api.py
git commit -m "feat(rag-provider): serve rag operations concurrently"
```

---

### Task 3: Faiss cold-cache single-flight

**Files:**
- Modify: `src/opensquilla_knowledge/retrieval/vector_faiss.py`
- Modify: `tests/test_vector_search.py`

**Interfaces:**
- Consumes: `_cache_entry()` and the existing `FaissCacheEntry` cache.
- Produces: one cache build per cache key under concurrent misses.

- [ ] **Step 1: Add failing concurrent cold-build test**

Create a backend with a small real test index. Wrap `_load_matrix` with a thread-safe counter and a short sleep, then run two identical searches:

```python
def test_faiss_same_key_concurrent_cold_search_builds_once(index, monkeypatch) -> None:
    backend = FaissHnswVectorSearchBackend()
    original = backend._load_matrix
    calls = 0
    lock = threading.Lock()

    def delayed_load(*args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(backend, "_load_matrix", delayed_load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_search(backend, index), range(2)))

    assert calls == 1
    assert backend.cache_builds == 1
    assert results[0] == results[1]
```

Use the existing test helpers for inserting current embeddings and invoking `search()`.

- [ ] **Step 2: Add different-key concurrency control**

Run two cold searches with different filters or models and use a barrier in `_load_matrix`. Assert both builds can enter concurrently, proving the implementation is per-key rather than global.

- [ ] **Step 3: Run RED tests**

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-preview/.venv-preview/bin/python \
  -m pytest -q tests/test_vector_search.py \
  -k "concurrent_cold_search or different_keys"
```

Expected: same-key build counter is 2 before locking.

- [ ] **Step 4: Implement per-key double-checked locking**

Import `threading`. In `__init__` add:

```python
self._cache_locks: dict[
    tuple[str, int, VectorFilter],
    threading.Lock,
] = {}
```

Refactor `_cache_entry()`:

```python
current_state = vector_state(...)
cached = self._cache.get(key)
if cached is not None and cached.state == current_state:
    return cached

lock = self._cache_locks.setdefault(key, threading.Lock())
with lock:
    current_state = vector_state(...)
    cached = self._cache.get(key)
    if cached is not None and cached.state == current_state:
        return cached
    entry = self._build_cache_entry(...)
    self._cache[key] = entry
    self.cache_builds += 1
    return entry
```

Extract `_build_cache_entry()` only if needed to keep `_cache_entry()` readable; do not change search ranking or cache-key semantics.

- [ ] **Step 5: Run GREEN and vector tests**

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-preview/.venv-preview/bin/python \
  -m pytest -q \
  tests/test_vector_search.py \
  tests/test_retrieval_resolver.py \
  tests/test_retrieval_capabilities.py
```

- [ ] **Step 6: Ruff, diff check, commit**

```bash
/root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m ruff check \
  src/opensquilla_knowledge/retrieval/vector_faiss.py \
  tests/test_vector_search.py
git diff --check
git add src/opensquilla_knowledge/retrieval/vector_faiss.py tests/test_vector_search.py
git commit -m "fix(retrieval): single-flight faiss cache builds"
```

---

### Task 4: Cross-repository focused validation

**Files:**
- No production changes expected.
- Write temporary smoke scripts only under `/var/tmp/rag-concurrency-*` and remove them.

**Interfaces:**
- Consumes: completed Open and Knowledge branches.
- Produces: focused verification evidence before deployment.

- [ ] **Step 1: Run Open focused tests**

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-rag-v0.5.0rc3/.venv/bin/python \
  -m pytest -q \
  tests/test_engine/test_tool_concurrency.py \
  tests/test_tools/test_dispatch_equivalence.py \
  tests/test_tools/test_result_projectors.py \
  tests/test_engine/test_tool_result_source_delivery.py \
  tests/test_engine/test_tool_result_persistence.py \
  tests/test_tools/test_web_search_tool.py \
  tests/test_tools/test_web_fetch.py
```

- [ ] **Step 2: Run Knowledge focused tests**

```bash
PYTHONPATH="$PWD/src" \
  /root/Q3WORK/opensquilla-knowledge-preview/.venv-preview/bin/python \
  -m pytest -q \
  tests/test_rag_provider_api.py \
  tests/test_rag_provider_service.py \
  tests/test_rag_provider_evidence.py \
  tests/test_rag_provider_reader.py \
  tests/test_vector_search.py \
  tests/test_retrieval_capabilities.py \
  tests/test_retrieval_resolver.py
```

- [ ] **Step 3: Run changed-file Ruff and diff checks**

Run Ruff on every Python file changed from the two release bases and run `git diff --check` in both worktrees.

- [ ] **Step 4: Run transient real concurrency smoke**

Start the Knowledge branch as a transient unit on port 18776 with production-equivalent Faiss environment and guaranteed cleanup. Through the Open branch:

1. issue two lexical Search calls concurrently;
2. assert both payloads pass Protocol 1.1 validation;
3. compare concurrent wall time with a sequential control and require real overlap;
4. issue four Get calls concurrently and validate every content/cursor response;
5. issue two concurrent cold hybrid calls for the same cache key only if the transient process has sufficient memory and assert the service remains healthy;
6. stop the unit and verify port 18776 has no listener.

- [ ] **Step 5: Review full diffs**

Confirm:

- Open changes only tool concurrency policy/tests plus committed design/plan.
- Knowledge changes only API concurrency, Faiss lock, and focused tests.
- No protocol, projection, WebUI, model routing, or deployment configuration drift.

---

### Task 5: Integration, deployment, and post-deploy acceptance

**Files:**
- No new production files.
- Update the existing personal project log after completion.

**Interfaces:**
- Consumes: validated Open and Knowledge commits.
- Produces: new immutable release refs/candidates and deployed Preview services.

- [ ] **Step 1: Fast-forward feature branches safely**

Verify the deployed user feature branches have not advanced unexpectedly. Merge each concurrency branch with `--ff-only` or merge the validated commits into a new integration branch, then re-run affected focused tests.

- [ ] **Step 2: Freeze new release refs and candidates**

Record new Open and Knowledge SHAs, update a concurrency-specific immutable release ref, and create detached clean candidates. Preserve the current `candidate-8eb7bf45` and `candidate-ba5ee203` as rollback targets.

- [ ] **Step 3: Preserve backup and deploy Knowledge**

Reuse the existing verified SQLite backup unless the live database changed materially during development; otherwise create a fresh online backup and run `PRAGMA integrity_check`. Atomically switch Knowledge, restart, verify health/capabilities, then run sequential and concurrent Search/Get smoke. Roll back on failure.

- [ ] **Step 4: Deploy Open**

Atomically switch Open, restart, verify `/readyz`, runtime status, and a real same-turn pair of Knowledge calls. Confirm tool start intervals overlap and results remain ordered. Roll back on failure.

- [ ] **Step 5: Post-deploy non-RAG checks**

Verify ordinary no-tool Chat, WebSearch/WebFetch availability and one Web spot, RAG Workbench, Chat Sources refresh, service PID/cwd/symlinks, rollback links, journal errors, and no transient port/unit residue.

- [ ] **Step 6: Write final note**

Append or create a project log containing final SHAs, concurrency timings, limits, tests, deployment targets, rollback paths, backup decision, and remaining non-blocking findings. Commit and push only the intended note.
