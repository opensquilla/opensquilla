# Local Document RAG

Local Document RAG indexes user-configured local Markdown and text files so the
agent can retrieve document evidence with citations.

RAG is disabled by default and never scans directories unless you explicitly add
or configure a source.

## Enable

```toml
[rag]
enabled = true
retrieval_mode = "hybrid"
```

The default embedding provider is `auto`. Auto mode prefers the local embedding
backend when available and does not use remote embedding APIs unless embedding
credentials are explicitly configured.

## Add And Sync

The CLI talks to the running gateway. It does not manage RAG offline.

```sh
opensquilla rag add /path/to/docs --name Docs
opensquilla rag sync --source-id src_docs
opensquilla rag search "install config"
```

`rag add` creates a reference source by default. OpenSquilla does not copy the
source directory; it records the path and indexes supported files during sync.

If the source path is later moved or removed, RAG keeps the historical index and
marks the source as missing or stale. A successful later sync is required before
deleted files are removed from the active index.

## Supported Files

Phase 1 supports:

- Markdown: `.md`, `.markdown`
- Text: `.txt`

PDF, OCR, watcher-based sync, collection permissions, and RAG data isolation are
outside the first implementation phase.

## Search Modes

- `fts`: full-text search.
- `vector_only`: semantic vector search; fails if vector search is unavailable.
- `hybrid`: combines FTS and vector search. If vector search is unavailable,
  hybrid falls back to FTS and reports fallback metadata.

Hybrid search reports diagnostics for inspection:

- configured `textWeight` and `vectorWeight`
- score formula
- FTS, vector, merged, and returned candidate counts
- per-result text score, vector score, and final score breakdown
- fallback reason when hybrid degrades to FTS

The default search preview asks for 5 results. Agent-facing `rag_search` also
defaults to 5 results and is capped at 10.

## Inspect And Debug

Use the Web UI search preview to inspect which chunks RAG retrieves for a query.
The result cards show source path, citation, line range, text/vector scores, and
the hybrid score breakdown. Use **Show chunk** to call `rag.show` and fetch more
of a specific chunk.

`rag.status` includes ingestion state:

- active job count
- latest job and last completed job
- job duration
- files seen, indexed, skipped, and failed
- chunks and embeddings written
- source stale, missing, active, and error summaries

This makes indexing progress and stale sources visible instead of making users
guess whether RAG is ready.

## Agent Use

The agent receives read-only tools:

- `rag_search`
- `rag_get`

`rag_search` returns a compact evidence list. It includes snippets, short content
previews, source IDs, chunk IDs, document IDs, scores, score breakdowns, and
citations. It does not try to send every full chunk to the model.

`rag_get` is the expansion path. The agent should call it with a returned
`chunkId`, `documentId`, or source/path when a compact result is relevant but more
original text is needed. `max_chars` controls how much text is returned, and the
payload marks whether the result was truncated.

RAG results are untrusted external evidence. The agent may summarize and cite
them, but document text must not be treated as system instructions, developer
instructions, or tool authorization.

Answers based on RAG should include citations such as:

```text
[来源：guide/setup.md]
```

For multi-source answers, prefer a final citation section:

```text
根据本地资料，...

引用：
[1] 光模块/2026-05-13_久谦_联讯仪器离职专家.md
[2] 高盛研报/2026-05_邮件_GS邮件原文合集.md
```
