#!/usr/bin/env python3
"""Seed and verify synthetic Desktop profile data around installer operations."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LABEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,80}")
_TAG_PATTERN = re.compile(r"v\d+\.\d+\.\d+(?:rc\d+)?")
_PROVIDER_BASE_URL = "http://127.0.0.1:18993/v1"


def _validated_label(value: str) -> str:
    if _LABEL_PATTERN.fullmatch(value) is None:
        raise ValueError("label must contain only ASCII letters, digits, dot, underscore, or dash")
    return value


def _workspace_files(label: str) -> dict[str, str]:
    return {
        "IDENTITY.md": f"# Synthetic {label} identity sentinel\n",
        "USER.md": f"# Synthetic {label} user\n",
        "SOUL.md": f"# Synthetic {label} soul\n",
        "MEMORY.md": f"# Synthetic {label} memory\n",
    }


def _config_text(home: Path, label: str) -> str:
    return (
        f"# Synthetic {label} release-preservation profile\n"
        f"state_dir = {json.dumps(str(home / 'state'))}\n"
        'search_provider = "duckduckgo"\n'
        "\n"
        "[llm]\n"
        'provider = "minimax_openai"\n'
        'model = "synthetic-release-model"\n'
        f"base_url = {json.dumps(_PROVIDER_BASE_URL)}\n"
        "\n"
        "[squilla_router]\n"
        "enabled = false\n"
        "\n"
        "[naming]\n"
        "enabled = false\n"
        "\n"
        "[control_ui]\n"
        "enabled = true\n"
        'base_path = "/control"\n'
    )


def _workspace(home: Path, layout: str) -> Path:
    return home / "state" / "workspace" if layout == "pre-rc3" else home / "workspace"


def _create_released_session_schema(
    connection: sqlite3.Connection,
    *,
    include_derived_title: bool,
) -> None:
    derived_title = "    derived_title TEXT,\n" if include_derived_title else ""
    connection.executescript(
        f"""
        CREATE TABLE sessions (
            session_key TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            started_at INTEGER,
            ended_at INTEGER,
            runtime_ms INTEGER,
            last_channel TEXT,
            last_to TEXT,
            last_account_id TEXT,
            last_thread_id TEXT,
            delivery_context TEXT,
            model TEXT,
            model_provider TEXT,
            provider_override TEXT,
            model_override TEXT,
            auth_profile_override TEXT,
            auth_profile_override_source TEXT,
            context_tokens INTEGER,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens_fresh INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
            total_cost_usd REAL NOT NULL DEFAULT 0.0,
            billed_cost_usd REAL NOT NULL DEFAULT 0.0,
            estimated_cost_component_usd REAL NOT NULL DEFAULT 0.0,
            cost_source TEXT NOT NULL DEFAULT 'none',
            missing_cost_entries INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_write INTEGER NOT NULL DEFAULT 0,
            compaction_count INTEGER NOT NULL DEFAULT 0,
            session_file TEXT,
            spawned_by TEXT,
            parent_session_key TEXT,
            forked_from_parent INTEGER NOT NULL DEFAULT 0,
            spawn_depth INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running',
            chat_type TEXT NOT NULL DEFAULT 'unknown',
            thinking_level TEXT,
            fast_mode INTEGER NOT NULL DEFAULT 0,
            verbose_level TEXT,
            reasoning_level TEXT,
            send_policy TEXT NOT NULL DEFAULT 'allow',
            queue_mode TEXT NOT NULL DEFAULT 'steer',
            label TEXT,
            display_name TEXT,
{derived_title}            channel TEXT,
            group_id TEXT,
            subject TEXT,
            origin TEXT,
            agent_id TEXT NOT NULL DEFAULT 'main',
            schema_version INTEGER NOT NULL DEFAULT 1,
            epoch INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_sessions_updated_at ON sessions(updated_at);
        CREATE TABLE transcript_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            message_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            reasoning_content TEXT,
            turn_usage TEXT,
            created_at INTEGER NOT NULL,
            token_count INTEGER,
            provenance_kind TEXT,
            provenance_origin_session_id TEXT,
            provenance_source_session_key TEXT,
            provenance_source_channel TEXT,
            provenance_source_tool TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX idx_transcript_session_id ON transcript_entries(session_id);
        CREATE INDEX idx_transcript_session_key ON transcript_entries(session_key);
        CREATE TABLE release_preservation_chat (
            id TEXT PRIMARY KEY,
            body TEXT NOT NULL
        );
        """
    )


def _content_matches_marker(content: object, marker: str) -> bool:
    if not isinstance(content, str):
        return False
    candidate = content
    if candidate.lstrip().startswith("{"):
        try:
            envelope = json.loads(candidate)
        except json.JSONDecodeError:
            envelope = None
        if isinstance(envelope, dict) and isinstance(envelope.get("text"), str):
            candidate = envelope["text"]
    if candidate == marker:
        return True
    prefix, separator, remainder = candidate.partition("\n")
    return bool(
        separator
        and prefix.rstrip("\r").startswith("[")
        and prefix.rstrip("\r").endswith("]")
        and remainder == marker
    )


def _marker_evidence(
    connection: sqlite3.Connection,
    marker: str,
) -> tuple[int, list[str]]:
    matches = [
        str(session_key)
        for session_key, content in connection.execute(
            """
            SELECT session_key, content FROM transcript_entries
            WHERE role = 'user'
            ORDER BY id
            """
        )
        if _content_matches_marker(content, marker)
    ]
    return len(matches), sorted(set(matches))


def seed_profile(
    home: Path,
    label: str,
    layout: str,
    source_tag: str,
    *,
    profile_only: bool = False,
) -> None:
    """Create a synthetic, release-shaped profile without replacing any file."""

    home = home.resolve()
    workspace = _workspace(home, layout)
    state = home / "state"
    protected = [home / "config.toml", state / "sessions.db"] + [
        workspace / name for name in _workspace_files(label)
    ]
    existing = [path for path in protected if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite preservation fixture: {existing[0]}")

    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    for name, expected in _workspace_files(label).items():
        (workspace / name).write_text(expected, encoding="utf-8")
    (home / "config.toml").write_text(_config_text(home, label), encoding="utf-8")
    if profile_only:
        return

    session_key = f"agent:main:webchat:{label}-retained"
    session_id = f"{label}-retained-session"
    retained_chat = f"synthetic retained chat ({label})"
    now_ms = int(time.time() * 1000)
    with sqlite3.connect(state / "sessions.db") as connection:
        _create_released_session_schema(
            connection,
            include_derived_title=source_tag != "v0.3.1",
        )
        connection.execute(
            "INSERT INTO release_preservation_chat (id, body) VALUES (?, ?)",
            (f"{label}-session", retained_chat),
        )
        connection.execute(
            """
            INSERT INTO sessions (
                session_key, session_id, created_at, updated_at, last_channel,
                last_to, status, chat_type, display_name, channel, agent_id,
                schema_version
            ) VALUES (?, ?, ?, ?, 'webchat', 'control-ui', 'done', 'direct',
                      ?, 'webchat', 'main', 1)
            """,
            (
                session_key,
                session_id,
                now_ms,
                now_ms,
                f"Historical {label} chat",
            ),
        )
        connection.execute(
            """
            INSERT INTO transcript_entries (
                session_id, session_key, message_id, role, content, created_at,
                schema_version
            ) VALUES (?, ?, ?, 'user', ?, ?, 1)
            """,
            (
                session_id,
                session_key,
                f"{label}-retained-message",
                retained_chat,
                now_ms,
            ),
        )
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise RuntimeError(f"seeded sessions.db failed PRAGMA quick_check: {result!r}")


@contextmanager
def _readonly_database(database: Path) -> Iterator[sqlite3.Connection]:
    """Open SQLite without mutating the profile, including a cleanly closed WAL database."""

    uri = f"{database.as_uri()}?mode=ro"
    wal = database.with_name(f"{database.name}-wal")
    shm = database.with_name(f"{database.name}-shm")
    wal_exists = wal.exists()
    shm_exists = shm.exists()
    if wal_exists != shm_exists:
        raise sqlite3.OperationalError("sessions.db has an incomplete WAL sidecar pair")

    # SQLite database header bytes 18 and 19 are the file read/write versions;
    # value 2 means WAL. A clean close may retain those bytes while deleting
    # both sidecars. Opening mode=ro can still create fresh `-wal`/`-shm` files
    # on some SQLite builds, so select immutable mode before SQLite touches it.
    with database.open("rb") as stream:
        header = stream.read(20)
    cleanly_closed_wal = (
        not wal_exists
        and not shm_exists
        and len(header) >= 20
        and header[:16] == b"SQLite format 3\x00"
        and header[18:20] == b"\x02\x02"
    )
    connection = sqlite3.connect(
        f"{uri}&immutable=1" if cleanly_closed_wal else uri,
        uri=True,
    )
    try:
        yield connection
    finally:
        connection.close()


def verify_profile(
    home: Path,
    label: str,
    *,
    verify_config: bool = True,
    retained_marker: str | None = None,
) -> None:
    """Verify exact fixture bytes and a read-only SQLite integrity probe."""

    home = home.resolve()
    canonical_workspace = home / "workspace"
    legacy_workspace = home / "state" / "workspace"
    state = home / "state"
    for name, expected in _workspace_files(label).items():
        candidates = [
            path
            for path in (canonical_workspace / name, legacy_workspace / name)
            if path.is_file()
        ]
        if not candidates:
            raise AssertionError(f"{name} disappeared while installing or upgrading Desktop")
        if any(path.read_text(encoding="utf-8") != expected for path in candidates):
            raise AssertionError(f"{name} changed while installing or uninstalling Desktop")

    if verify_config:
        actual_config = (home / "config.toml").read_text(encoding="utf-8")
        if actual_config != _config_text(home, label):
            raise AssertionError("config.toml changed while installing or uninstalling Desktop")

    database = state / "sessions.db"
    with _readonly_database(database) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            raise AssertionError(f"sessions.db failed PRAGMA quick_check: {quick_check!r}")
        if retained_marker is not None:
            marker_count, marker_session_keys = _marker_evidence(
                connection,
                retained_marker,
            )
            if marker_count != 1 or len(marker_session_keys) != 1:
                raise AssertionError(
                    "sessions.db must contain exactly one retained release-runtime "
                    f"session for {retained_marker!r}; "
                    f"got count={marker_count}, keys={marker_session_keys!r}"
                )
            session_exists = connection.execute(
                "SELECT 1 FROM sessions WHERE session_key = ?",
                (marker_session_keys[0],),
            ).fetchone()
            if session_exists is None:
                raise AssertionError("retained release-runtime transcript lost its session row")
            return
        row = connection.execute("SELECT id, body FROM release_preservation_chat").fetchone()
        session = connection.execute(
            "SELECT session_id, display_name FROM sessions WHERE session_key = ?",
            (f"agent:main:webchat:{label}-retained",),
        ).fetchone()
        transcript = connection.execute(
            """
            SELECT role, content FROM transcript_entries
            WHERE session_id = ? ORDER BY id LIMIT 1
            """,
            (f"{label}-retained-session",),
        ).fetchone()
    expected_row = (f"{label}-session", f"synthetic retained chat ({label})")
    if row != expected_row:
        raise AssertionError(f"sessions.db retained-chat row changed: {row!r}")
    expected_session = (f"{label}-retained-session", f"Historical {label} chat")
    if session != expected_session:
        raise AssertionError(f"sessions.db canonical retained session changed: {session!r}")
    expected_transcript = ("user", f"synthetic retained chat ({label})")
    if transcript != expected_transcript:
        raise AssertionError(f"sessions.db canonical retained transcript changed: {transcript!r}")


def snapshot_profile(
    home: Path,
    label: str,
    new_marker: str | None,
    *,
    verify_retained: bool,
    verify_config: bool,
) -> dict[str, object]:
    """Return content-level session evidence used around a packaged relaunch."""

    if verify_retained:
        verify_profile(home, label, verify_config=verify_config)
    database = home.resolve() / "state" / "sessions.db"
    with _readonly_database(database) as connection:
        sessions = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        transcripts = int(
            connection.execute("SELECT COUNT(*) FROM transcript_entries").fetchone()[0]
        )
        marker_count = 0
        marker_session_keys: list[str] = []
        if new_marker:
            marker_count, marker_session_keys = _marker_evidence(connection, new_marker)
    return {
        "schema_version": 1,
        "database": str(database),
        "retained_session_key": f"agent:main:webchat:{label}-retained",
        "sessions": sessions,
        "transcripts": transcripts,
        "new_marker": new_marker,
        "new_marker_count": marker_count,
        "new_marker_session_keys": marker_session_keys,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify", "snapshot"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--label", type=_validated_label, required=True)
    parser.add_argument("--layout", choices=("pre-rc3", "modern"), default="modern")
    parser.add_argument("--source-tag", type=str, default="v0.5.0")
    parser.add_argument("--new-marker")
    parser.add_argument("--retained-marker")
    parser.add_argument("--profile-only", action="store_true")
    parser.add_argument("--skip-retained-verification", action="store_true")
    parser.add_argument("--allow-config-change", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if _TAG_PATTERN.fullmatch(args.source_tag) is None:
            raise ValueError("source tag must be a released vX.Y.Z or vX.Y.ZrcN tag")
        if args.operation == "seed":
            seed_profile(
                args.home,
                args.label,
                args.layout,
                args.source_tag,
                profile_only=args.profile_only,
            )
            print(f"profile preservation fixture seeded: {args.home}")
        elif args.operation == "verify":
            verify_profile(
                args.home,
                args.label,
                verify_config=not args.allow_config_change,
                retained_marker=args.retained_marker,
            )
            print(f"profile preservation verified: {args.home}")
        else:
            print(
                json.dumps(
                    snapshot_profile(
                        args.home,
                        args.label,
                        args.new_marker,
                        verify_retained=not args.skip_retained_verification,
                        verify_config=not args.allow_config_change,
                    ),
                    sort_keys=True,
                )
            )
    except (
        AssertionError,
        FileExistsError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
