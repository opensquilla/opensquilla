"""OpenSquilla self-migration: import a legacy OpenSquilla home into this install.

Unlike the foreign-runtime migrators (OpenClaw, Hermes) this source is
shape-identical to the target: a legacy CLI home, an orphaned Windows
portable data dir, and the desktop Electron home all share the OpenSquilla
home layout. The import is therefore a guarded whole-home copy — pre-flight
checks, a transactional staged copy, and a small set of transforms (config
path unpinning, inline-secret relocation, scheduler pause) — rather than a
per-item semantic mapping.

The report dict returned by :meth:`OpenSquillaHomeMigrator.migrate` is a
pinned wire contract: see ``docs/self-migration-report-contract.md`` and
``tests/test_contracts/test_migration_report_wire.py``.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import structlog
import tomli_w
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.config_migration import migrate_config_payload
from opensquilla.migration.env_file import merge_env_lines, write_secret_env_file
from opensquilla.migration.openclaw import ItemResult
from opensquilla.paths import default_opensquilla_home

log = structlog.get_logger(__name__)

OPENSQUILLA_SOURCE_KINDS: tuple[str, ...] = ("cli-home", "windows-portable", "desktop-home")

#: Free-space headroom demanded on top of the source home size.
_DISK_MARGIN_BYTES = 64 * 1024 * 1024
#: Completion marker written (best-effort) into the source home after apply.
IMPORT_MARKER_FILENAME = ".opensquilla-imported.json"
#: Journal listing the planned staging -> target renames; an interrupted
#: commit leaves it behind for diagnosis.
_COMMIT_JOURNAL = "import-commit.json"
#: Top-level source dirs never copied (profile homes nest whole other homes).
_EXCLUDED_TOP_LEVEL_DIRS = frozenset({"profiles"})
#: Runtime lock files under ``state/`` never copied.
_EXCLUDED_STATE_FILES = ("gateway.pid", "gateway.pid.lock")
#: SQLite stores whose ``-wal``/``-shm`` sidecars must travel with them.
_SQLITE_STORES = (
    Path("state/sessions.db"),
    Path("state/scheduler.db"),
    Path("state/approval_queue.sqlite"),
    Path("state/sandbox_user_grants.sqlite"),
)
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm")
_LEGACY_DEFAULT_PORT = 18790
_CURRENT_DEFAULT_PORT = 18791
_FALLBACK_LLM_ENV_KEY = "OPENSQUILLA_LLM_API_KEY"
_ELEVENLABS_ENV_KEY = "ELEVENLABS_API_KEY"


def _ext(path: Path) -> str:
    """Return an extended-length path string on Windows, a plain string elsewhere.

    Deep portable workspace trees routinely exceed the 260-character default
    Windows path limit; the ``\\\\?\\`` prefix lifts it for copy operations.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows-only path
        return "\\\\?\\" + str(path.resolve())
    return str(path)


def _as_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser()


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return first == second


def _path_pin_is_absolute(value: str) -> bool:
    """Recognize native, POSIX, and Windows drive/UNC absolute config pins."""
    stripped = value.strip()
    if not stripped:
        return False
    return (
        Path(stripped).expanduser().is_absolute()
        or PurePosixPath(stripped).is_absolute()
        or PureWindowsPath(stripped).is_absolute()
    )


def _paths_overlap(first: Path, second: Path) -> bool:
    """Return whether either resolved path contains the other."""
    try:
        resolved_first = first.resolve(strict=False)
        resolved_second = second.resolve(strict=False)
    except OSError:
        resolved_first, resolved_second = first, second
    return resolved_first.is_relative_to(resolved_second) or resolved_second.is_relative_to(
        resolved_first
    )


def is_valid_opensquilla_home(path: Path) -> bool:
    """Return True when ``path`` plausibly holds an OpenSquilla home."""
    if not path.is_dir():
        return False
    return (
        (path / "config.toml").is_file()
        or (path / "state").is_dir()
        or (path / "workspace").is_dir()
    )


def detect_legacy_cli_home(target: Path) -> Path | None:
    """Return ``~/.opensquilla`` when it is a legacy home distinct from ``target``.

    A plain CLI user whose active home IS ``~/.opensquilla`` must never see
    their own live home offered as a migration source; only installs whose
    target resolves elsewhere (desktop spawns, relocated state dirs) get the
    CLI home auto-detected.
    """
    legacy = Path.home() / ".opensquilla"
    if not is_valid_opensquilla_home(legacy):
        return None
    if _same_path(legacy, target):
        return None
    if _source_marker_matches_target(legacy, target):
        return None
    return legacy


def _source_marker_matches_target(source: Path, target: Path) -> bool:
    marker = source / IMPORT_MARKER_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    marked_target = payload.get("target")
    if not isinstance(marked_target, str) or not _same_path(Path(marked_target), target):
        return False
    transaction_id = payload.get("transaction_id")
    if not isinstance(transaction_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", transaction_id
    ):
        return False
    report_path = target / "migration" / "opensquilla" / transaction_id / "report.json"
    try:
        receipt = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _valid_import_receipt(receipt, source=source, target=target, report_path=report_path)


def _valid_import_receipt(
    receipt: object,
    *,
    source: Path,
    target: Path,
    report_path: Path,
) -> bool:
    if not isinstance(receipt, dict):
        return False
    receipt_source = receipt.get("source")
    receipt_target = receipt.get("target")
    output_dir = receipt.get("output_dir")
    if (
        not isinstance(receipt_source, str)
        or not _same_path(Path(receipt_source), source)
        or not isinstance(receipt_target, str)
        or not _same_path(Path(receipt_target), target)
        or receipt.get("apply") is not True
        or not isinstance(output_dir, str)
        or not _same_path(Path(output_dir), report_path.parent)
        or receipt.get("source_kind") not in OPENSQUILLA_SOURCE_KINDS
    ):
        return False
    items = receipt.get("items")
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("kind"), str)
            or item.get("status") not in {"migrated", "planned", "skipped"}
            or not isinstance(item.get("reason"), str)
            or (item.get("source") is not None and not isinstance(item.get("source"), str))
            or (
                item.get("destination") is not None
                and not isinstance(item.get("destination"), str)
            )
            or not isinstance(item.get("details"), dict)
        ):
            return False
    return True


def _commit_journal_path(target: Path) -> Path:
    return target.parent / f".{target.name}.{_COMMIT_JOURNAL}"


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(_ext(temporary), _ext(path))
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@dataclass
class PortableCandidate:
    """One enumerated Windows-portable data dir, newest-first sortable."""

    path: Path
    last_used: float
    size_bytes: int
    era_hint: str


def enumerate_portable_homes(bases: list[Path] | None = None) -> list[PortableCandidate]:
    """Enumerate ``<base>/OpenSquilla/portable/*`` homes, newest-first.

    Default bases come from the ``LOCALAPPDATA`` and ``TEMP`` environment
    variables (unset ones are skipped), matching where every portable
    launcher ever placed its data dir.
    """
    if bases is None:
        bases = []
        for env_name in ("LOCALAPPDATA", "TEMP"):
            raw = os.environ.get(env_name, "").strip()
            if raw:
                bases.append(Path(raw))
    candidates: list[PortableCandidate] = []
    for base in bases:
        portable_root = base / "OpenSquilla" / "portable"
        if not portable_root.is_dir():
            continue
        try:
            entries = sorted(portable_root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or not is_valid_opensquilla_home(entry):
                continue
            candidates.append(
                PortableCandidate(
                    path=entry,
                    last_used=_home_last_used(entry),
                    size_bytes=_tree_size_bytes(entry),
                    era_hint=_era_hint(entry),
                )
            )
    candidates.sort(key=lambda candidate: candidate.last_used, reverse=True)
    return candidates


def detect_desktop_home() -> Path | None:
    """Return the platform Electron userData home for OpenSquilla, if distinct."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "OpenSquilla"
    elif sys.platform == "win32":  # pragma: no cover - Windows-only path
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            base = Path(appdata) / "OpenSquilla"
        else:
            base = Path.home() / "AppData" / "Roaming" / "OpenSquilla"
    else:
        base = Path.home() / ".config" / "OpenSquilla"
    candidate = base / "opensquilla"
    if not is_valid_opensquilla_home(candidate):
        return None
    if _same_path(candidate, default_opensquilla_home()):
        return None
    return candidate


def _home_last_used(home: Path) -> float:
    """Prefer ``config.toml`` mtime over the directory mtime (which misleads)."""
    for probe in (home / "config.toml", home):
        try:
            return probe.stat().st_mtime
        except OSError:
            continue
    return 0.0


def _tree_size_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _era_hint(home: Path) -> str:
    receipt = home / "install-receipt.json"
    if receipt.is_file():
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            version = data.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
    if (home / "state" / "update_check.json").is_file():
        return "0.5.0rc2+"
    return ""


# ---------------------------------------------------------------------------
# Gateway liveness (mirrors the gateway pidlock semantics without importing
# its private helpers: JSON pid payload + signal-0 style liveness probe).
# ---------------------------------------------------------------------------


def _read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        try:
            return int(payload["pid"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(payload, int) and not isinstance(payload, bool):
        return payload
    try:
        return int(raw.decode("utf-8", errors="replace").strip())
    except ValueError:
        return None


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - Windows-only path
        return _pid_is_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not owned by us
    except OSError:
        return False
    return True


def _pid_is_alive_windows(pid: int) -> bool:  # pragma: no cover - Windows-only path
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return int(exit_code.value) == still_active
        finally:
            try:
                kernel32.CloseHandle(handle)
            except OSError:
                pass
    except Exception:  # noqa: BLE001 - liveness probe must never raise
        return False


def _gateway_running(home: Path) -> bool:
    pid = _read_pid_file(home / "state" / "gateway.pid")
    return pid is not None and _pid_is_alive(pid)


# ---------------------------------------------------------------------------
# Schema-ahead pre-flight (read-only ledger inspection; never runs migrations)
# ---------------------------------------------------------------------------


def _migration_dir_candidates() -> list[Path]:
    """Mirror gateway boot's migrations-dir resolution order."""
    candidates: list[Path] = []
    env_dir = os.environ.get("OPENSQUILLA_MIGRATIONS_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    try:
        from importlib import resources as importlib_resources

        package_dir = importlib_resources.files("opensquilla").joinpath("_migrations")
        if package_dir.is_dir():
            candidates.append(Path(str(package_dir)))
    except Exception:  # noqa: BLE001 - packaged resources are best-effort here
        pass
    candidates.append(Path(__file__).resolve().parents[3] / "migrations")
    return candidates


def _known_migration_ids() -> set[str]:
    """Return the migration ids shipped with this binary (yoyo id == file stem)."""
    for candidate in _migration_dir_candidates():
        try:
            ids = {entry.stem for entry in candidate.glob("V*.py")}
        except OSError:
            continue
        if ids:
            return ids
    return set()


def _read_applied_migration_ids(db_path: Path) -> set[str] | None:
    """Read the yoyo ledger read-only; ``None`` when the db cannot be inspected."""
    try:
        with tempfile.TemporaryDirectory(prefix="opensquilla-sqlite-inspect-") as temporary:
            copied_db = _copy_sqlite_bundle(db_path, Path(temporary))
            connection = sqlite3.connect(
                f"{copied_db.resolve().as_uri()}?mode=ro",
                uri=True,
            )
            try:
                table_rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE '%yoyo_migration'"
                ).fetchall()
                table = next(
                    (
                        name
                        for (name,) in table_rows
                        if isinstance(name, str) and name.endswith("yoyo_migration")
                    ),
                    None,
                )
                if table is None:
                    return set()
                rows = connection.execute(f'SELECT migration_id FROM "{table}"').fetchall()
            finally:
                connection.close()
    except (OSError, sqlite3.Error):
        return None
    return {str(migration_id) for (migration_id,) in rows if migration_id}


def _copy_sqlite_bundle(source_db: Path, destination_dir: Path) -> Path:
    """Copy a SQLite database and present sidecars for mutation-free inspection."""
    destination_db = destination_dir / source_db.name
    for suffix in ("", *_SQLITE_SIDECAR_SUFFIXES):
        source_file = source_db.with_name(source_db.name + suffix)
        if not source_file.is_file():
            continue
        destination_file = destination_db.with_name(destination_db.name + suffix)
        shutil.copyfile(_ext(source_file), _ext(destination_file))
    return destination_db


# ---------------------------------------------------------------------------
# Secret env-key naming
# ---------------------------------------------------------------------------


def _provider_env_key(provider_id: str) -> str:
    """Return the provider's conventional key env var, or "" when unknown."""
    normalized = provider_id.strip().lower()
    if not normalized:
        return ""
    try:
        registry = importlib.import_module("opensquilla.provider.registry")
        spec = registry.get_provider_spec(normalized)
    except Exception:  # noqa: BLE001 - unknown providers fall back to a generic key
        return ""
    env_key = str(getattr(spec, "env_key", "") or "")
    if not env_key or env_key == "OAuth":
        return ""
    return env_key


def _fallback_profile_env_key(profile_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", profile_id).strip("_").upper() or "UNKNOWN"
    return f"OPENSQUILLA_PROFILE_{slug}_API_KEY"


@dataclass(frozen=True)
class OpenSquillaMigrationOptions:
    """Options for the OpenSquilla-to-OpenSquilla home import."""

    source: Path | str | None = None
    kind: str = "cli-home"
    config_path: Path | None = None
    apply: bool = False
    overwrite: bool = False
    #: Test override for the target home; defaults to the active home.
    target: Path | str | None = None


class OpenSquillaHomeMigrator:
    """Import a legacy OpenSquilla home into the current home.

    Protocol: validate -> pre-flight -> (dry-run stop) -> staged copy ->
    transforms on the staged copy -> journaled commit renames -> report.
    User errors are recorded as ``error`` items in the report; they never
    raise.
    """

    def __init__(self, options: OpenSquillaMigrationOptions) -> None:
        self.options = options
        self.kind = options.kind
        self.source: Path | None = _as_path(options.source)
        self.target = _as_path(options.target) or default_opensquilla_home()
        self.timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        self.output_dir = self.target / "migration" / "opensquilla" / self.timestamp
        self.items: list[ItemResult] = []
        self.candidates: list[PortableCandidate] = []
        self.config_transforms: list[str] = []
        self.secret_relocations: list[dict[str, Any]] = []
        self.paused_jobs: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.preflight: dict[str, Any] = {
            "source_gateway_running": False,
            "target_gateway_running": False,
            "schema_ahead": False,
            "disk_required_bytes": 0,
            "disk_free_bytes": 0,
        }
        self._env_additions: dict[str, str] = {}
        self._config_payload: dict[str, Any] | None = None
        self._raw_config_payload: dict[str, Any] | None = None
        self._data_roots: dict[str, list[Path]] = {
            "state": [],
            "workspace": [],
            "media": [],
        }
        self._sqlite_stores_cache: dict[Path, Path] | None = None
        self._blocked = False
        self._wrote_output_dir = False
        self._committed = False

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def migrate(self) -> dict[str, Any]:
        if self.kind not in OPENSQUILLA_SOURCE_KINDS:
            self._record(
                "options",
                None,
                None,
                "error",
                f"Unknown source kind: {self.kind} "
                f"(known: {', '.join(OPENSQUILLA_SOURCE_KINDS)})",
            )
            return self._report()
        if self.options.config_path is not None:
            self._record(
                "options",
                self.options.config_path,
                None,
                "error",
                "config_path is not supported for OpenSquilla self-migration; "
                "select the target home through the active OpenSquilla environment",
            )
            self._blocked = True
            return self._report()
        self._resolve_source()
        if self.source is None:
            return self._report()
        if not self._recover_interrupted_commit():
            return self._report()
        if not self._validate_paths():
            return self._report()
        source = self.source
        assert source is not None
        self._sandbox_config_pass(source)
        self._plan_data_roots()
        self._run_preflight()
        if self._blocked:
            return self._report()

        entries = self._collect_entries()
        self._plan_config_transforms()

        if not self.options.apply:
            for entry in entries:
                details: dict[str, Any] = {}
                if entry.name == "state":
                    details["excluded"] = [f"state/{name}" for name in _EXCLUDED_STATE_FILES]
                self._record(
                    "home-entry", entry, self.target / entry.name, "planned", details=details
                )
            planned_data_entries = {entry.name for entry in entries}
            for name, roots in self._data_roots.items():
                for root in roots:
                    if name not in planned_data_entries or root != source / name:
                        self._record(
                            "data-root", root, self.target / name, "planned"
                        )
            for root in self._data_roots.get("state", []):
                jobs = self._read_scheduler_jobs(root / "scheduler.db")
                if jobs is not None:
                    self.paused_jobs = jobs
                    break
            return self._report()

        self._apply(entries)
        if self._committed and not self._has_error():
            self._write_source_marker()
        return self._report()

    def _recover_interrupted_commit(self) -> bool:
        journal = _commit_journal_path(self.target)
        if not journal.is_file():
            return True
        if not self.options.apply:
            self._record(
                "preflight/recovery",
                journal,
                self.target,
                "error",
                "an interrupted import transaction needs recovery; rerun with --apply",
            )
            self._blocked = True
            return False
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("journal root is not an object")
            recorded_target = Path(str(payload.get("target", "")))
            staging = Path(str(payload.get("staging", "")))
            backup = Path(str(payload.get("backup", "")))
            phase = str(payload.get("phase", ""))
            if not _same_path(recorded_target, self.target):
                raise ValueError("journal target does not match the active target")
            if staging.parent != self.target.parent or not staging.name.startswith(
                ".opensquilla-import-"
            ):
                raise ValueError("journal staging path is outside the target parent")
            if backup.parent != self.target.parent or not backup.name.startswith(
                f"{self.target.name}.backup."
            ):
                raise ValueError("journal backup path is outside the target parent")
            if phase not in {"prepared", "target-backed-up", "published"}:
                raise ValueError(f"unknown journal phase: {phase}")

            if not self.target.exists() and backup.exists():
                os.replace(_ext(backup), _ext(self.target))
                recovery_reason = "restored the complete target backup"
            elif self.target.exists():
                recovery_reason = "target was already present; cleaned the interrupted transaction"
            elif phase == "prepared" and staging.exists():
                recovery_reason = "discarded an unpublished staging tree"
            else:
                raise OSError("neither the target nor its rollback backup exists")

            if staging.exists() or staging.is_symlink():
                self._remove_path(staging)
            journal.unlink(missing_ok=True)
            _fsync_directory(journal.parent)
            self._record(
                "recovery",
                journal,
                self.target,
                "migrated",
                recovery_reason,
            )
            return True
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._record(
                "preflight/recovery",
                journal,
                self.target,
                "error",
                f"could not safely recover the interrupted import: {exc}",
            )
            self._blocked = True
            return False

    # ------------------------------------------------------------------
    # Source resolution and validation
    # ------------------------------------------------------------------

    def _resolve_source(self) -> None:
        if self.kind == "windows-portable":
            self.candidates = enumerate_portable_homes()
        if self.source is not None:
            return
        if self.kind == "cli-home":
            self.source = Path.home() / ".opensquilla"
            return
        if self.kind == "desktop-home":
            detected = detect_desktop_home()
            if detected is None:
                self._record(
                    "source",
                    None,
                    None,
                    "error",
                    "No desktop OpenSquilla home was found on this machine",
                )
                return
            self.source = detected
            return
        # windows-portable with no explicit source
        if len(self.candidates) == 1:
            self.source = self.candidates[0].path
            return
        if not self.candidates:
            self._record(
                "source",
                None,
                None,
                "error",
                "No portable OpenSquilla homes were found; pass --source <path>",
            )
            return
        listing = "; ".join(str(candidate.path) for candidate in self.candidates)
        self._record(
            "source",
            None,
            None,
            "error",
            "Multiple portable OpenSquilla homes were found; pass --home to select "
            f"one of: {listing}",
        )

    def _validate_paths(self) -> bool:
        source = self.source
        assert source is not None
        if not source.is_dir():
            self._record("source", source, None, "error", "source home does not exist")
            return False
        if not is_valid_opensquilla_home(source):
            self._record(
                "source",
                source,
                None,
                "error",
                "source is not an OpenSquilla home (no config.toml, state/, or workspace/)",
            )
            return False
        try:
            resolved_source = source.resolve(strict=False)
            resolved_target = self.target.resolve(strict=False)
        except OSError:
            resolved_source, resolved_target = source, self.target
        if resolved_source == resolved_target:
            self._record(
                "source",
                source,
                self.target,
                "error",
                "source and target are the same OpenSquilla home",
            )
            return False
        if resolved_source.is_relative_to(resolved_target) or resolved_target.is_relative_to(
            resolved_source
        ):
            self._record(
                "source",
                source,
                self.target,
                "error",
                "source and target homes are nested within each other",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    def _run_preflight(self) -> None:
        source = self.source
        assert source is not None

        source_state_roots = self._data_roots.get("state") or [source / "state"]
        source_running = any(
            _read_pid_file(root / "gateway.pid") is not None
            and (
                (pid := _read_pid_file(root / "gateway.pid")) is not None
                and _pid_is_alive(pid)
            )
            for root in source_state_roots
        )
        target_running = _gateway_running(self.target)
        self.preflight["source_gateway_running"] = source_running
        self.preflight["target_gateway_running"] = target_running
        if source_running:
            self._record(
                "preflight/gateway",
                source,
                None,
                "error",
                "a gateway is running on the source home; stop it and re-run",
            )
            self._blocked = True
        if target_running:
            self._record(
                "preflight/gateway",
                self.target,
                None,
                "error",
                "a gateway is running on the target home; stop it and re-run",
            )
            self._blocked = True
        if not source_running and not target_running:
            self._record(
                "preflight/gateway",
                source,
                self.target,
                "skipped",
                "no gateway is running on the source or target home",
            )

        schema_ahead = self._check_schema_ahead(source)
        self.preflight["schema_ahead"] = schema_ahead
        if schema_ahead:
            self._blocked = True
        if self._check_sqlite_integrity():
            self._blocked = True

        # The preview must discover split-root conflicts before the user
        # approves an apply. This walk is read-only and also re-runs during
        # staging to catch a source that changed after preview.
        for name, roots in self._data_roots.items():
            if len(roots) < 2:
                continue
            try:
                self._validate_data_root_conflicts(name, roots)
            except OSError:
                self._blocked = True

        required = self._required_disk_bytes()
        free = self._target_free_bytes()
        self.preflight["disk_required_bytes"] = required
        self.preflight["disk_free_bytes"] = free
        if free < required:
            self._record(
                "preflight/disk",
                source,
                self.target,
                "error",
                f"not enough free disk space on the target volume: {required} bytes "
                f"required (source size plus margin), {free} bytes free",
            )
            self._blocked = True
        else:
            self._record("preflight/disk", source, self.target, "skipped", "ok")

        collisions = self._target_collisions()
        if collisions:
            if not self.options.overwrite:
                self._record(
                    "preflight/target",
                    None,
                    self.target,
                    "error",
                    "target home contains entries that the import would replace "
                    f"({', '.join(collisions)}); pass --overwrite to replace them "
                    "after taking a complete timestamped home backup",
                )
                self._blocked = True
            else:
                self._record(
                    "preflight/target",
                    None,
                    self.target,
                    "skipped",
                    "target collisions will be replaced after a complete home backup",
                )
        else:
            self._record("preflight/target", None, self.target, "skipped", "ok")

    def _target_free_bytes(self) -> int:
        probe = self.target.parent
        while not probe.exists():
            parent = probe.parent
            if parent == probe:
                break
            probe = parent
        try:
            return int(shutil.disk_usage(probe).free)
        except OSError:
            return 0

    def _required_disk_bytes(self) -> int:
        """Return source + external roots + target staging headroom without double-counting."""
        source = self.source
        assert source is not None
        total = _tree_size_bytes(source)
        resolved_source = source.resolve(strict=False)
        seen: set[Path] = set()
        for roots in self._data_roots.values():
            for root in roots:
                resolved = root.resolve(strict=False)
                if resolved in seen or resolved == resolved_source:
                    continue
                seen.add(resolved)
                if resolved.is_relative_to(resolved_source):
                    continue
                total += _tree_size_bytes(root)
        if self.target.exists():
            total += _tree_size_bytes(self.target)
        return total + _DISK_MARGIN_BYTES

    def _target_collisions(self) -> list[str]:
        source = self.source
        assert source is not None
        planned_names = {
            entry.name
            for entry in source.iterdir()
            if entry.name not in {IMPORT_MARKER_FILENAME, "profiles"}
        }
        planned_names.update(name for name, roots in self._data_roots.items() if roots)
        return sorted(name for name in planned_names if (self.target / name).exists())

    def _check_schema_ahead(self, source: Path) -> bool:
        db_paths = [root / "sessions.db" for root in self._data_roots.get("state", [])]
        db_paths = [path for path in db_paths if path.is_file()]
        if not db_paths:
            db_path = source / "state" / "sessions.db"
            self._record("preflight/schema", db_path, None, "skipped", "no sessions.db in source")
            return False
        known = _known_migration_ids()
        if not known:
            self._note("no migration set was found for this binary")
            self._record(
                "preflight/schema",
                db_paths[0],
                None,
                "error",
                "no migration set found for this binary; refusing an unverifiable import",
            )
            return True
        for db_path in db_paths:
            applied = _read_applied_migration_ids(db_path)
            if applied is None:
                self._record(
                    "preflight/schema",
                    db_path,
                    None,
                    "error",
                    "source sessions.db could not be inspected read-only; "
                    "refusing an unverifiable import",
                )
                return True
            unknown = sorted(applied - known)
            if unknown:
                self._record(
                    "preflight/schema",
                    db_path,
                    None,
                    "error",
                    "source home was written by a newer OpenSquilla "
                    f"(unknown migrations: {', '.join(unknown)}); update OpenSquilla first",
                )
                return True
            self._record("preflight/schema", db_path, None, "skipped", "ok")
        return False

    def _source_sqlite_stores(self) -> dict[Path, Path]:
        if self._sqlite_stores_cache is not None:
            return dict(self._sqlite_stores_cache)
        candidates: dict[Path, list[Path]] = {}
        for state_root in self._data_roots.get("state", []):
            store_rels = [rel.relative_to("state") for rel in _SQLITE_STORES]
            agents_dir = state_root / "agents"
            if agents_dir.is_dir():
                store_rels.extend(
                    memory_db.relative_to(state_root)
                    for memory_db in sorted(agents_dir.glob("*/memory.db"))
                )
            for relative in store_rels:
                source_db = state_root / relative
                if source_db.is_file():
                    candidates.setdefault(relative, []).append(source_db)
        stores = {
            relative: self._select_sqlite_bundle(relative, paths)
            for relative, paths in candidates.items()
        }
        self._sqlite_stores_cache = stores
        return dict(stores)

    def _select_sqlite_bundle(self, relative: Path, candidates: list[Path]) -> Path:
        if len(candidates) == 1:
            return candidates[0]
        try:
            fingerprints = {
                candidate: self._sqlite_logical_fingerprint(candidate)
                for candidate in candidates
            }
        except (OSError, sqlite3.Error) as exc:
            self._record(
                "preflight/sqlite",
                candidates[-1],
                self.target / "state" / relative,
                "error",
                f"could not compare duplicate SQLite bundles for state/{relative}: {exc}",
            )
            self._blocked = True
            return candidates[-1]

        wal_candidates = [
            candidate
            for candidate in candidates
            if self._sqlite_wal_has_frames(candidate)
        ]
        if len(set(fingerprints.values())) == 1:
            return wal_candidates[-1] if wal_candidates else candidates[-1]

        first = candidates[0]
        main_files_match = all(self._files_equal(first, candidate) for candidate in candidates[1:])
        if main_files_match and len(wal_candidates) == 1:
            # The roots hold the same checkpointed database, but one bundle has
            # additional committed WAL frames. That bundle is the complete store.
            return wal_candidates[0]

        rendered = ", ".join(str(candidate) for candidate in candidates)
        self._record(
            "preflight/data-root",
            candidates[-1],
            self.target / "state" / relative,
            "error",
            f"conflicting logical SQLite stores exist in multiple state roots: {rendered}",
        )
        self._blocked = True
        return candidates[-1]

    @staticmethod
    def _sqlite_wal_has_frames(source_db: Path) -> bool:
        wal = source_db.with_name(source_db.name + "-wal")
        try:
            return wal.stat().st_size > 32
        except OSError:
            return False

    @staticmethod
    def _sqlite_logical_fingerprint(source_db: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="opensquilla-sqlite-compare-") as temporary:
            copied_db = _copy_sqlite_bundle(source_db, Path(temporary))
            connection = sqlite3.connect(
                f"{copied_db.resolve().as_uri()}?mode=ro",
                uri=True,
            )
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if result != ("ok",):
                    raise sqlite3.DatabaseError(f"quick_check returned {result!r}")
                digest = hashlib.sha256()
                for statement in connection.iterdump():
                    digest.update(statement.encode("utf-8", errors="surrogatepass"))
                    digest.update(b"\n")
                return digest.hexdigest()
            finally:
                connection.close()

    def _check_sqlite_integrity(self) -> bool:
        failed = False
        for relative, source_db in sorted(self._source_sqlite_stores().items()):
            try:
                with tempfile.TemporaryDirectory(
                    prefix="opensquilla-sqlite-inspect-"
                ) as temporary:
                    copied_db = _copy_sqlite_bundle(source_db, Path(temporary))
                    connection = sqlite3.connect(
                        f"{copied_db.resolve().as_uri()}?mode=ro",
                        uri=True,
                    )
                    try:
                        result = connection.execute("PRAGMA quick_check").fetchone()
                    finally:
                        connection.close()
                if result != ("ok",):
                    raise sqlite3.DatabaseError(f"quick_check returned {result!r}")
            except (OSError, sqlite3.Error) as exc:
                failed = True
                self._record(
                    "preflight/sqlite",
                    source_db,
                    self.target / "state" / relative,
                    "error",
                    f"source SQLite store state/{relative} failed integrity check: {exc}",
                )
        return failed

    def _sandbox_config_pass(self, source: Path) -> None:
        config_path = source / "config.toml"
        if not config_path.is_file():
            self._record("preflight/config", config_path, None, "skipped", "no config.toml")
            return
        try:
            payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            self._record(
                "preflight/config",
                config_path,
                None,
                "error",
                f"source config.toml could not be parsed ({exc}); import blocked",
            )
            self._blocked = True
            return
        self._raw_config_payload = payload
        candidate = migrate_config_payload(payload, emit_diagnostics=False).payload
        errors = self._validate_config_payload(candidate)
        quarantined: list[str] = []
        if errors is not None:
            extra_locs = [
                error.get("loc", ())
                for error in errors
                if error.get("type") == "extra_forbidden"
            ]
            for loc in extra_locs:
                dotted = self._delete_payload_path(candidate, loc)
                if dotted:
                    quarantined.append(dotted)
            if quarantined:
                errors = self._validate_config_payload(candidate)
        status = "migrated" if self.options.apply else "planned"
        for dotted in quarantined:
            self.config_transforms.append(f"quarantined unknown config key: {dotted}")
            self._record(
                "config-quarantine",
                config_path,
                None,
                status,
                f"unknown config key {dotted} removed so the imported config validates",
            )
        if errors is None:
            self._config_payload = candidate
            self._record("preflight/config", config_path, None, "skipped", "ok")
            return
        summary = "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', ()))}: {error.get('msg', '')}"
            for error in errors[:3]
        )
        self._record(
            "preflight/config",
            config_path,
            None,
            "error",
            "source config.toml does not validate against the current schema "
            f"({summary}); import blocked",
        )
        self._blocked = True

    def _plan_data_roots(self) -> None:
        """Discover canonical and configured data roots before path pins are dropped."""
        source = self.source
        assert source is not None
        payload = self._raw_config_payload or {}
        configured: dict[str, Path | None] = {
            "state": self._configured_path(payload.get("state_dir")),
            "workspace": self._configured_path(payload.get("workspace_dir")),
            "media": None,
        }
        attachments = payload.get("attachments")
        if isinstance(attachments, dict):
            configured["media"] = self._configured_path(attachments.get("media_root"))

        for name in ("state", "workspace", "media"):
            roots: list[Path] = []
            canonical = source / name
            if canonical.is_dir():
                roots.append(canonical)
            explicit = configured[name]
            if explicit is not None and explicit.is_dir():
                roots.append(explicit)
            if name == "media" and explicit is None:
                state_root = configured["state"]
                if state_root is not None:
                    for candidate in (state_root.parent / "media", state_root / "media"):
                        if candidate.is_dir():
                            roots.append(candidate)
            unique: list[Path] = []
            seen: set[Path] = set()
            for root in roots:
                resolved = root.resolve(strict=False)
                if resolved in seen:
                    continue
                seen.add(resolved)
                if _paths_overlap(root, self.target):
                    self._record(
                        "preflight/data-root",
                        root,
                        self.target / name,
                        "error",
                        f"configured {name} root overlaps the target home; "
                        "refusing a recursive import",
                    )
                    self._blocked = True
                    continue
                unique.append(root)
            self._data_roots[name] = unique

        for name in ("state", "workspace", "media"):
            explicit = configured[name]
            if explicit is None or explicit.is_dir() or self._data_roots[name]:
                continue
            reason = (
                f"configured {name} directory does not exist"
                if not explicit.exists()
                else f"configured {name} path is not a directory"
            )
            self._record(
                "preflight/data-root",
                explicit,
                self.target / name,
                "error",
                f"{reason}; refusing to drop its config pin",
            )
            self._blocked = True

    def _configured_path(self, value: object) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        path = Path(value).expanduser()
        if _path_pin_is_absolute(value):
            return path
        source = self.source
        assert source is not None
        return source / path

    def _validate_config_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Return ``None`` when the payload validates, else pydantic error dicts."""
        try:
            GatewayConfig(**payload)
        except ValidationError as exc:
            return [dict(error) for error in exc.errors()]
        except Exception as exc:  # noqa: BLE001 - sandbox validation is advisory
            return [{"type": "unexpected", "loc": (), "msg": str(exc)}]
        return None

    def _delete_payload_path(self, payload: dict[str, Any], loc: tuple[Any, ...]) -> str:
        """Delete the key addressed by ``loc``; return its dotted path or ""."""
        if not loc or not all(isinstance(part, str) for part in loc):
            return ""
        current: Any = payload
        for part in loc[:-1]:
            if not isinstance(current, dict) or part not in current:
                return ""
            current = current[part]
        if not isinstance(current, dict) or loc[-1] not in current:
            return ""
        current.pop(loc[-1])
        return ".".join(str(part) for part in loc)

    # ------------------------------------------------------------------
    # Planning: entries, config transforms, secret relocation
    # ------------------------------------------------------------------

    def _collect_entries(self) -> list[Path]:
        source = self.source
        assert source is not None
        entries: list[Path] = []
        for entry in sorted(source.iterdir()):
            if entry.name == IMPORT_MARKER_FILENAME:
                self._record(
                    "home-entry", entry, None, "skipped", "previous import marker is not copied"
                )
                continue
            if entry.name in _EXCLUDED_TOP_LEVEL_DIRS and entry.is_dir():
                self._record(
                    "home-entry",
                    entry,
                    None,
                    "skipped",
                    "profile homes are not imported; import one explicitly with --source",
                )
                continue
            entries.append(entry)
        return entries

    def _plan_config_transforms(self) -> None:
        payload = self._config_payload
        if payload is None:
            return
        for key in ("state_dir", "workspace_dir"):
            value = payload.get(key)
            if isinstance(value, str) and _path_pin_is_absolute(value):
                payload.pop(key)
                self.config_transforms.append(
                    f"dropped {key} (absolute path pinned to the old home; "
                    "the default re-derives under the new home)"
                )
        attachments = payload.get("attachments")
        if isinstance(attachments, dict):
            media_root = attachments.get("media_root")
            if (
                isinstance(media_root, str)
                and _path_pin_is_absolute(media_root)
            ):
                attachments.pop("media_root")
                self.config_transforms.append(
                    "dropped attachments.media_root (absolute path pinned to the old home; "
                    "the default re-derives under the new home)"
                )
        if payload.get("port") == _LEGACY_DEFAULT_PORT:
            payload["port"] = _CURRENT_DEFAULT_PORT
            self.config_transforms.append(
                f"port: {_LEGACY_DEFAULT_PORT} -> {_CURRENT_DEFAULT_PORT} "
                "(legacy default gateway port)"
            )
        self._plan_secret_relocations(payload)

    def _plan_secret_relocations(self, payload: dict[str, Any]) -> None:
        llm = payload.get("llm")
        if isinstance(llm, dict):
            provider = llm.get("provider")
            env_key = (
                _provider_env_key(provider) if isinstance(provider, str) else ""
            ) or _FALLBACK_LLM_ENV_KEY
            self._relocate_secret(llm, "api_key", "llm.api_key", env_key)
        profiles = payload.get("llm_profiles")
        if isinstance(profiles, dict):
            for profile_id, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                profile_env = _provider_env_key(str(profile_id)) or _fallback_profile_env_key(
                    str(profile_id)
                )
                self._relocate_secret(
                    profile, "api_key", f"llm_profiles.{profile_id}.api_key", profile_env
                )
        audio = payload.get("audio")
        providers = audio.get("providers") if isinstance(audio, dict) else None
        elevenlabs = providers.get("elevenlabs") if isinstance(providers, dict) else None
        if isinstance(elevenlabs, dict):
            self._relocate_secret(
                elevenlabs,
                "api_key",
                "audio.providers.elevenlabs.api_key",
                _ELEVENLABS_ENV_KEY,
            )

    def _relocate_secret(
        self, section: dict[str, Any], key: str, config_path: str, env_key: str
    ) -> None:
        value = section.get(key)
        if not isinstance(value, str) or not value.strip():
            return
        self._env_additions[env_key] = value.strip()
        section["api_key_env"] = env_key
        section.pop(key, None)
        # Never the value: the report shape is a pinned, redaction-guaranteed
        # contract (docs/self-migration-report-contract.md).
        self.secret_relocations.append(
            {"config_path": config_path, "env_key": env_key, "moved": True}
        )
        self.config_transforms.append(f"moved {config_path} to .env as {env_key}")

    # ------------------------------------------------------------------
    # Apply: staged copy, transforms, journaled commit
    # ------------------------------------------------------------------

    def _apply(self, entries: list[Path]) -> None:
        staging = self.target.parent / f".opensquilla-import-{self.timestamp}"
        try:
            staging.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            self._record(
                "apply", self.source, self.target, "error", f"could not create staging dir: {exc}"
            )
            return
        try:
            if self.target.exists():
                shutil.copytree(_ext(self.target), _ext(staging), dirs_exist_ok=True)
            self._copy_entries(entries, staging)
            self._copy_data_roots(staging)
            self._snapshot_sqlite_stores(staging)
            self._transform_staged_config(staging)
            self._write_staged_env(staging)
            staged_scheduler = staging / "state" / "scheduler.db"
            if staged_scheduler.is_file():
                self._pause_scheduler_jobs(staged_scheduler, staging)
            if self._has_error():
                raise OSError("one or more staged migration transforms failed")
            self._commit(staging)
        except OSError as exc:
            log.error(
                "opensquilla_home_migration.apply_failed",
                source=str(self.source),
                target=str(self.target),
                error=str(exc),
            )
            self._record(
                "apply",
                self.source,
                self.target,
                "error",
                f"import failed before completion: {exc}; the transaction was not "
                "completed and the staging directory was left for diagnosis",
            )
            if not self._committed:
                self._wrote_output_dir = False

    def _copy_entries(self, entries: list[Path], staging: Path) -> None:
        source = self.source
        assert source is not None
        for entry in entries:
            if entry.name in self._data_roots:
                continue
            destination = staging / entry.name
            if destination.exists() or destination.is_symlink():
                if entry.name == "migration" and entry.is_dir() and destination.is_dir():
                    shutil.copytree(
                        _ext(entry),
                        _ext(destination),
                        dirs_exist_ok=True,
                    )
                    self._record(
                        "home-entry",
                        entry,
                        self.target / entry.name,
                        "migrated",
                        "merged migration reports in staging",
                    )
                    continue
                self._remove_path(destination)
            if entry.is_dir():
                shutil.copytree(_ext(entry), _ext(destination))
            else:
                shutil.copy2(_ext(entry), _ext(destination))
            self._record("home-entry", entry, self.target / entry.name, "migrated")

    def _copy_data_roots(self, staging: Path) -> None:
        for name, roots in self._data_roots.items():
            if not roots:
                continue
            self._validate_data_root_conflicts(name, roots)
            destination = staging / name
            self._remove_path(destination)
            destination.mkdir(parents=True, exist_ok=True)
            for root in roots:
                ignore = (
                    shutil.ignore_patterns(*_EXCLUDED_STATE_FILES)
                    if name == "state"
                    else None
                )
                shutil.copytree(
                    _ext(root),
                    _ext(destination),
                    dirs_exist_ok=True,
                    ignore=ignore,
                )
                self._record("data-root", root, self.target / name, "migrated")
            for dirpath, _dirnames, _filenames in os.walk(destination):
                directory = Path(dirpath)
                try:
                    os.chmod(directory, directory.stat().st_mode | 0o700)
                except OSError as exc:
                    raise OSError(f"could not make imported {name} writable: {directory}") from exc

    def _validate_data_root_conflicts(self, name: str, roots: list[Path]) -> None:
        seen: dict[Path, Path] = {}
        sqlite_bundle_members: set[Path] = set()
        if name == "state":
            for relative in self._source_sqlite_stores():
                sqlite_bundle_members.update(
                    relative.with_name(relative.name + suffix)
                    for suffix in ("", *_SQLITE_SIDECAR_SUFFIXES)
                )
        for root in roots:
            for dirpath, _dirnames, filenames in os.walk(root):
                directory = Path(dirpath)
                for filename in filenames:
                    if name == "state" and filename in _EXCLUDED_STATE_FILES:
                        continue
                    source_file = directory / filename
                    relative = source_file.relative_to(root)
                    if relative in sqlite_bundle_members:
                        continue
                    previous = seen.get(relative)
                    if previous is None:
                        seen[relative] = source_file
                        continue
                    if not self._files_equal(previous, source_file):
                        self._record(
                            "preflight/data-root",
                            source_file,
                            self.target / name / relative,
                            "error",
                            f"conflicting {name} files exist in multiple source roots: "
                            f"{previous} and {source_file}",
                        )
                        raise OSError(f"conflicting {name} source roots")

    @staticmethod
    def _files_equal(first: Path, second: Path) -> bool:
        try:
            if first.stat().st_size != second.stat().st_size:
                return False
            with first.open("rb") as first_handle, second.open("rb") as second_handle:
                while True:
                    first_chunk = first_handle.read(1024 * 1024)
                    second_chunk = second_handle.read(1024 * 1024)
                    if first_chunk != second_chunk:
                        return False
                    if not first_chunk:
                        return True
        except OSError:
            return False

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(_ext(path))
        else:
            path.unlink(missing_ok=True)

    def _snapshot_sqlite_stores(self, staging: Path) -> None:
        """Create consistent WAL-aware SQLite snapshots and validate every store."""
        snapshot_root = self._staged_output_dir(staging) / "db-snapshots"
        for relative, source_db in sorted(self._source_sqlite_stores().items()):
            destination = staging / "state" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.snapshot-{self.timestamp}.tmp"
            )
            temporary.unlink(missing_ok=True)
            try:
                with tempfile.TemporaryDirectory(
                    prefix="opensquilla-sqlite-snapshot-"
                ) as inspection_dir:
                    copied_db = _copy_sqlite_bundle(source_db, Path(inspection_dir))
                    source_connection = sqlite3.connect(
                        f"{copied_db.resolve().as_uri()}?mode=ro",
                        uri=True,
                    )
                    try:
                        target_connection = sqlite3.connect(temporary)
                        try:
                            source_connection.backup(target_connection)
                            result = target_connection.execute("PRAGMA quick_check").fetchone()
                            if result != ("ok",):
                                raise sqlite3.DatabaseError(
                                    f"quick_check failed for {relative}: {result!r}"
                                )
                        finally:
                            target_connection.close()
                    finally:
                        source_connection.close()
            except (OSError, sqlite3.Error) as exc:
                temporary.unlink(missing_ok=True)
                self._record(
                    "sqlite",
                    source_db,
                    self.target / "state" / relative,
                    "error",
                    f"could not create a consistent snapshot for state/{relative}: {exc}",
                )
                raise OSError(f"sqlite snapshot failed for state/{relative}") from exc

            destination.unlink(missing_ok=True)
            for suffix in _SQLITE_SIDECAR_SUFFIXES:
                destination.with_name(destination.name + suffix).unlink(missing_ok=True)
            os.replace(_ext(temporary), _ext(destination))
            try:
                os.chmod(destination, (source_db.stat().st_mode & 0o777) | 0o600)
            except OSError:
                pass
            snapshot = snapshot_root / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_ext(destination), _ext(snapshot))
            self._record(
                "sqlite",
                source_db,
                self.target / "state" / relative,
                "migrated",
                "consistent snapshot verified",
            )

    def _transform_staged_config(self, staging: Path) -> None:
        staged_config = staging / "config.toml"
        if not staged_config.is_file():
            return
        payload = self._config_payload
        if payload is None:
            raise OSError("validated source config is unavailable")
        try:
            staged_config.write_text(tomli_w.dumps(payload), encoding="utf-8")
            os.chmod(staged_config, 0o600)
        except (OSError, TypeError, ValueError) as exc:
            self._record(
                "config",
                staged_config,
                self.target / "config.toml",
                "error",
                f"could not write the transformed config ({exc}); import blocked",
            )
            raise OSError("could not serialize transformed config") from exc
        source = self.source
        assert source is not None
        self._record(
            "config",
            source / "config.toml",
            self.target / "config.toml",
            "migrated",
            details={"transforms": list(self.config_transforms)},
        )

    def _write_staged_env(self, staging: Path) -> None:
        env_path = staging / ".env"
        if not self._env_additions:
            if env_path.is_file():
                os.chmod(env_path, 0o600)
            return
        existing_lines = (
            env_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if env_path.exists()
            else []
        )
        lines = merge_env_lines(existing_lines, self._env_additions)
        write_secret_env_file(env_path, lines)
        self._record(
            "env",
            env_path,
            self.target / ".env",
            "migrated",
            details={"env_keys": sorted(self._env_additions)},
        )

    def _pause_scheduler_jobs(self, staged_db: Path, staging: Path) -> None:
        # Snapshot the pristine copy before mutating it, so a bad pause can
        # always be diagnosed/recovered from the migration report dir.
        snapshot_dir = self._staged_output_dir(staging) / "db-snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._wrote_output_dir = True
        shutil.copy2(_ext(staged_db), _ext(snapshot_dir / staged_db.name))
        for suffix in _SQLITE_SIDECAR_SUFFIXES:
            sidecar = staged_db.with_name(staged_db.name + suffix)
            if sidecar.is_file():
                shutil.copy2(_ext(sidecar), _ext(snapshot_dir / sidecar.name))
        try:
            connection = sqlite3.connect(staged_db)
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(scheduler_jobs)")
                }
                if not columns:
                    self._record(
                        "scheduler", staged_db, None, "skipped", "no scheduler_jobs table"
                    )
                    return
                if "enabled" in columns:
                    connection.execute("UPDATE scheduler_jobs SET enabled = 0")
                else:
                    # Pre-seeding the column at 0 wins over JobStore's later
                    # conditional add (which defaults to 1), so every imported
                    # job arrives paused.
                    connection.execute(
                        "ALTER TABLE scheduler_jobs "
                        "ADD COLUMN enabled INTEGER NOT NULL DEFAULT 0"
                    )
                rows = connection.execute(
                    "SELECT id, name, cron_expr FROM scheduler_jobs"
                ).fetchall()
                connection.commit()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            self._record(
                "scheduler", staged_db, None, "error", f"could not pause scheduler jobs: {exc}"
            )
            raise OSError("could not pause imported scheduler jobs") from exc
        self.paused_jobs = [
            {"id": row[0], "name": row[1], "cron_expr": row[2]} for row in rows
        ]
        self._record(
            "scheduler",
            staged_db,
            self.target / "state" / "scheduler.db",
            "migrated",
            f"paused {len(self.paused_jobs)} imported scheduler job(s)",
        )

    def _read_scheduler_jobs(self, db_path: Path) -> list[dict[str, Any]] | None:
        """Read the (id, name, cron_expr) job rows read-only for the dry-run preview."""
        if not db_path.is_file():
            return None
        try:
            with tempfile.TemporaryDirectory(prefix="opensquilla-sqlite-inspect-") as temporary:
                copied_db = _copy_sqlite_bundle(db_path, Path(temporary))
                connection = sqlite3.connect(
                    f"{copied_db.resolve().as_uri()}?mode=ro",
                    uri=True,
                )
                try:
                    columns = {
                        row[1]
                        for row in connection.execute("PRAGMA table_info(scheduler_jobs)")
                    }
                    if not columns:
                        return None
                    rows = connection.execute(
                        "SELECT id, name, cron_expr FROM scheduler_jobs"
                    ).fetchall()
                finally:
                    connection.close()
        except (OSError, sqlite3.Error):
            return None
        return [{"id": row[0], "name": row[1], "cron_expr": row[2]} for row in rows]

    def _commit(self, staging: Path) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        backup = self.target.with_name(f"{self.target.name}.backup.{self.timestamp}")
        journal = _commit_journal_path(self.target)
        target_existed = self.target.exists()
        journal_payload: dict[str, Any] = {
            "target": str(self.target),
            "staging": str(staging),
            "backup": str(backup),
            "phase": "prepared",
            "target_existed": target_existed,
        }
        backup_item: ItemResult | None = None
        if target_existed:
            self._record(
                "backup",
                self.target,
                backup,
                "migrated",
                "complete previous target home backup retained for rollback",
            )
            backup_item = self.items[-1]

        target_backed_up = False
        published = False
        try:
            self._write_report_files(staging)
            _atomic_write_json(journal, journal_payload)
            if target_existed:
                os.replace(_ext(self.target), _ext(backup))
                target_backed_up = True
                _fsync_directory(self.target.parent)
                journal_payload["phase"] = "target-backed-up"
                _atomic_write_json(journal, journal_payload)
            os.replace(_ext(staging), _ext(self.target))
            published = True
            _fsync_directory(self.target.parent)
            journal_payload["phase"] = "published"
            _atomic_write_json(journal, journal_payload)
        except OSError as exc:
            rollback_error: OSError | None = None
            try:
                if published and (self.target.exists() or self.target.is_symlink()):
                    if staging.exists() or staging.is_symlink():
                        raise OSError("staging path unexpectedly exists during rollback")
                    os.replace(_ext(self.target), _ext(staging))
                if target_backed_up:
                    if not (backup.exists() or backup.is_symlink()):
                        raise OSError("complete target backup is missing during rollback")
                    os.replace(_ext(backup), _ext(self.target))
                _fsync_directory(self.target.parent)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
            if rollback_error is None:
                try:
                    journal.unlink(missing_ok=True)
                    _fsync_directory(journal.parent)
                except OSError as cleanup_exc:
                    rollback_error = cleanup_exc
            if backup_item is not None:
                self.items.remove(backup_item)
            if rollback_error is not None:
                raise OSError(f"{exc}; rollback failed: {rollback_error}") from exc
            raise

        self._committed = True
        try:
            journal.unlink(missing_ok=True)
            _fsync_directory(journal.parent)
        except OSError:
            self._note(
                f"committed import journal could not be removed: {journal}; "
                "a later apply can clean it safely"
            )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _record(
        self,
        kind: str,
        source: Path | str | None,
        destination: Path | str | None,
        status: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.items.append(
            ItemResult(
                kind=kind,
                source=str(source) if source is not None else None,
                destination=str(destination) if destination is not None else None,
                status=status,
                reason=reason,
                details=dict(details or {}),
            )
        )

    def _note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)

    def _has_error(self) -> bool:
        return any(item.status == "error" for item in self.items)

    def _report(self) -> dict[str, Any]:
        return {
            "source": str(self.source) if self.source is not None else "",
            "source_kind": self.kind,
            "target": str(self.target),
            "output_dir": str(self.output_dir) if self._wrote_output_dir else "",
            "apply": self.options.apply,
            "items": [asdict(item) for item in self.items],
            "candidates": [
                {
                    "path": str(candidate.path),
                    "last_used_iso": datetime.fromtimestamp(candidate.last_used).isoformat(),
                    "size_bytes": candidate.size_bytes,
                    "era_hint": candidate.era_hint,
                }
                for candidate in self.candidates
            ],
            "config_transforms": list(self.config_transforms),
            "secret_relocations": [dict(entry) for entry in self.secret_relocations],
            "paused_jobs": [dict(job) for job in self.paused_jobs],
            "preflight": dict(self.preflight),
            "notes": list(self.notes),
        }

    def _staged_output_dir(self, staging: Path) -> Path:
        return staging / "migration" / "opensquilla" / self.timestamp

    def _write_report_files(self, staging: Path) -> None:
        output_dir = self._staged_output_dir(staging)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._note("could not create the migration report directory")
            raise OSError("could not create migration report directory") from exc
        self._wrote_output_dir = True
        report = self._report()
        (output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        lines = [
            "# OpenSquilla Home Import Summary",
            "",
            f"- Source: `{self.source}` ({self.kind})",
            f"- Target home: `{self.target}`",
            f"- Apply: `{self.options.apply}`",
            f"- Paused scheduler jobs: {len(self.paused_jobs)}",
            "",
            "## Counts",
            "",
        ]
        for status, count in sorted(counts.items()):
            lines.append(f"- {status}: {count}")
        lines.append("")
        (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_source_marker(self) -> None:
        source = self.source
        if source is None:
            return
        payload = {
            "imported_at": datetime.now(UTC).isoformat(),
            "target": str(self.target),
            "transaction_id": self.timestamp,
        }
        try:
            _atomic_write_json(source / IMPORT_MARKER_FILENAME, payload)
        except OSError:
            self._note("could not write the completion marker into the source home")
