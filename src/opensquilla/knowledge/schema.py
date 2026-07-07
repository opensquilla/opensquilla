from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    source_uri TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_files (
    source_file_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    discovered_at INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(snapshot_id) REFERENCES source_snapshots(snapshot_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_files_collection_path
ON source_files(collection_id, source_path);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content_kind TEXT NOT NULL,
    date TEXT,
    language_bucket TEXT NOT NULL,
    pair_id TEXT,
    content_sha256 TEXT,
    profile_id TEXT,
    plan_id TEXT,
    parser TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_collection_source
ON documents(collection_id, source);

CREATE TABLE IF NOT EXISTS document_profiles (
    profile_id TEXT PRIMARY KEY,
    source_file_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    encoding TEXT,
    language_bucket TEXT NOT NULL,
    text_quality TEXT NOT NULL,
    structure_kind TEXT NOT NULL,
    estimated_chars INTEGER NOT NULL,
    page_count INTEGER,
    has_frontmatter INTEGER NOT NULL DEFAULT 0,
    heading_count INTEGER NOT NULL DEFAULT 0,
    parser_candidates_json TEXT NOT NULL DEFAULT '[]',
    chunker_candidates_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processing_plans (
    plan_id TEXT PRIMARY KEY,
    source_file_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    preprocessor_strategy TEXT NOT NULL,
    chunking_strategy TEXT NOT NULL,
    index_profiles_json TEXT NOT NULL DEFAULT '[]',
    steps_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    document_id TEXT,
    artifact_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    uri TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    artifact_id TEXT,
    plan_id TEXT,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    section TEXT,
    language_bucket TEXT NOT NULL,
    pair_id TEXT,
    chunking_strategy TEXT,
    char_start INTEGER,
    char_end INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE,
    FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_collection_document
ON chunks(collection_id, document_id, ordinal);

CREATE TABLE IF NOT EXISTS metadata_kv (
    metadata_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metadata_owner_key
ON metadata_kv(owner_type, owner_id, key);

CREATE TABLE IF NOT EXISTS chunk_lineage (
    lineage_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    artifact_id TEXT,
    plan_id TEXT NOT NULL,
    step_ordinal INTEGER NOT NULL,
    operation TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    input_ref TEXT,
    output_ref TEXT,
    reversible INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunk_lineage_chunk
ON chunk_lineage(chunk_id, step_ordinal);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    files_seen INTEGER NOT NULL DEFAULT 0,
    files_ready INTEGER NOT NULL DEFAULT 0,
    files_failed INTEGER NOT NULL DEFAULT 0,
    documents_indexed INTEGER NOT NULL DEFAULT 0,
    chunks_indexed INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manifest_entries (
    manifest_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    document_id TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(source_file_id) REFERENCES source_files(source_file_id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    judgment_id TEXT PRIMARY KEY,
    collection_id TEXT,
    question_id TEXT NOT NULL,
    question TEXT NOT NULL,
    rating TEXT NOT NULL,
    evidence TEXT NOT NULL,
    hallucination TEXT NOT NULL,
    notes TEXT NOT NULL,
    selected_chunk_id TEXT,
    results_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS index_builds (
    build_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    index_type TEXT NOT NULL,
    status TEXT NOT NULL,
    documents_indexed INTEGER NOT NULL,
    chunks_indexed INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS index_catalog (
    profile_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    index_type TEXT NOT NULL,
    status TEXT NOT NULL,
    build_id TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY(build_id) REFERENCES index_builds(build_id) ON DELETE SET NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks
USING fts5(
    chunk_id UNINDEXED,
    collection_id UNINDEXED,
    document_id UNINDEXED,
    source_path UNINDEXED,
    search_text
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
