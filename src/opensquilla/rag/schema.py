"""SQLite schema for local document RAG."""

from __future__ import annotations

RAG_SCHEMA_VERSION = 1


DDL = f"""
CREATE TABLE IF NOT EXISTS rag_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_collections (
  collection_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_sources (
  source_id TEXT PRIMARY KEY,
  collection_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  root_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  include_json TEXT NOT NULL DEFAULT '[]',
  exclude_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  sync_policy TEXT NOT NULL DEFAULT 'manual',
  scale_hint TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'stale',
  stale_reason TEXT,
  last_error TEXT,
  last_scan_started_at REAL,
  last_scan_finished_at REAL,
  last_successful_scan_at REAL,
  last_indexed_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(collection_id) REFERENCES rag_collections(collection_id)
);

CREATE TABLE IF NOT EXISTS rag_documents (
  document_id TEXT PRIMARY KEY,
  collection_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  absolute_path_snapshot TEXT NOT NULL,
  title TEXT,
  extension TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  mtime_ns INTEGER NOT NULL DEFAULT 0,
  content_hash TEXT,
  parser TEXT,
  status TEXT NOT NULL,
  last_seen_scan_id TEXT,
  indexed_at REAL,
  removed_at REAL,
  last_error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(source_id, relative_path),
  FOREIGN KEY(source_id) REFERENCES rag_sources(source_id),
  FOREIGN KEY(collection_id) REFERENCES rag_collections(collection_id)
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  chunk_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  collection_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  title TEXT,
  section TEXT,
  line_start INTEGER,
  line_end INTEGER,
  page INTEGER,
  token_count INTEGER,
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(document_id, chunk_index),
  FOREIGN KEY(document_id) REFERENCES rag_documents(document_id)
);

CREATE TABLE IF NOT EXISTS rag_embeddings (
  chunk_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  base_url TEXT,
  dimensions INTEGER NOT NULL,
  fingerprint TEXT NOT NULL,
  embedding_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(chunk_id, fingerprint),
  FOREIGN KEY(chunk_id) REFERENCES rag_chunks(chunk_id)
);

CREATE TABLE IF NOT EXISTS rag_index_jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  collection_id TEXT,
  source_id TEXT,
  status TEXT NOT NULL,
  scan_id TEXT,
  started_at REAL NOT NULL,
  finished_at REAL,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_indexed INTEGER NOT NULL DEFAULT 0,
  files_skipped INTEGER NOT NULL DEFAULT 0,
  files_failed INTEGER NOT NULL DEFAULT 0,
  chunks_written INTEGER NOT NULL DEFAULT 0,
  embeddings_written INTEGER NOT NULL DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS rag_errors (
  error_id TEXT PRIMARY KEY,
  job_id TEXT,
  collection_id TEXT,
  source_id TEXT,
  document_id TEXT,
  relative_path TEXT,
  phase TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{{}}',
  created_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
  content,
  title,
  relative_path,
  chunk_id UNINDEXED,
  document_id UNINDEXED,
  collection_id UNINDEXED,
  source_id UNINDEXED,
  tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_rag_sources_collection
  ON rag_sources(collection_id);
CREATE INDEX IF NOT EXISTS idx_rag_documents_source_status
  ON rag_documents(source_id, status);
CREATE INDEX IF NOT EXISTS idx_rag_documents_collection_status
  ON rag_documents(collection_id, status);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
  ON rag_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source
  ON rag_chunks(source_id, status);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_path
  ON rag_chunks(source_id, relative_path);
CREATE INDEX IF NOT EXISTS idx_rag_embeddings_fingerprint
  ON rag_embeddings(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_source_started
  ON rag_index_jobs(source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_errors_job
  ON rag_errors(job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_errors_source
  ON rag_errors(source_id, created_at DESC);

INSERT INTO rag_meta(key, value, updated_at)
VALUES ('schema_version', '{RAG_SCHEMA_VERSION}', strftime('%s','now'))
ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;
"""


def vector_table_ddl(dimensions: int) -> str:
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_vec USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding FLOAT[{int(dimensions)}]
);
"""
