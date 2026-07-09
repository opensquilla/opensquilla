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

import importlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
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
    return legacy


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
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        try:
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE '%yoyo_migration'"
            ).fetchall()
        except sqlite3.Error:
            return None
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
        try:
            rows = connection.execute(f'SELECT migration_id FROM "{table}"').fetchall()
        except sqlite3.Error:
            return None
    finally:
        connection.close()
    return {str(migration_id) for (migration_id,) in rows if migration_id}


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
        self.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
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
        self._resolve_source()
        if self.source is None:
            return self._report()
        if not self._validate_paths():
            return self._report()
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
            source = self.source
            jobs = self._read_scheduler_jobs(source / "state" / "scheduler.db")
            if jobs is not None:
                self.paused_jobs = jobs
            return self._report()

        self._apply(entries)
        if self._committed or self._wrote_output_dir:
            self._write_report_files()
        if self._committed:
            self._write_source_marker()
        return self._report()

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

        source_running = _gateway_running(source)
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

        required = _tree_size_bytes(source) + _DISK_MARGIN_BYTES
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

        self._sandbox_config_pass(source)

        if (self.target / "state" / "sessions.db").exists():
            if not self.options.overwrite:
                self._record(
                    "preflight/target",
                    None,
                    self.target,
                    "error",
                    "target home already contains session data; pass --overwrite to "
                    "replace it (timestamped backups are taken)",
                )
                self._blocked = True
            else:
                self._record(
                    "preflight/target",
                    None,
                    self.target,
                    "skipped",
                    "target home is not empty; colliding entries will be backed up",
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

    def _check_schema_ahead(self, source: Path) -> bool:
        db_path = source / "state" / "sessions.db"
        if not db_path.is_file():
            self._record("preflight/schema", db_path, None, "skipped", "no sessions.db in source")
            return False
        applied = _read_applied_migration_ids(db_path)
        if applied is None:
            self._record(
                "preflight/schema",
                db_path,
                None,
                "skipped",
                "source sessions.db could not be inspected read-only; schema check skipped",
            )
            return False
        known = _known_migration_ids()
        if not known:
            self._note("no migration set was found for this binary; schema check skipped")
            self._record(
                "preflight/schema",
                db_path,
                None,
                "skipped",
                "no migration set found for this binary; schema check skipped",
            )
            return False
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
                f"source config.toml could not be parsed ({exc}); it will be copied "
                "as-is and the target will boot from defaults",
            )
            return
        candidate = migrate_config_payload(payload).payload
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
            f"({summary}); it will be copied as-is and the target will boot from defaults",
        )

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
            if isinstance(value, str) and value.strip() and Path(value).is_absolute():
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
                and media_root.strip()
                and Path(media_root).is_absolute()
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
            self._copy_entries(entries, staging)
            self._verify_sqlite_sidecars(staging)
            self._transform_staged_config(staging)
            self._write_staged_env(staging)
            staged_scheduler = staging / "state" / "scheduler.db"
            if staged_scheduler.is_file():
                self._pause_scheduler_jobs(staged_scheduler)
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
                f"import failed before completion: {exc}; the staging directory "
                f"{staging} was left in place for diagnosis and the target was "
                "not partially overwritten",
            )

    def _copy_entries(self, entries: list[Path], staging: Path) -> None:
        for entry in entries:
            destination = staging / entry.name
            if entry.is_dir():
                if entry.name == "state":
                    # gateway.pid / gateway.pid.lock are per-process runtime
                    # locks; carrying them over would make the imported home
                    # look owned by a dead (or worse, unrelated live) process.
                    ignore = shutil.ignore_patterns(*_EXCLUDED_STATE_FILES)
                    shutil.copytree(_ext(entry), _ext(destination), ignore=ignore)
                else:
                    shutil.copytree(_ext(entry), _ext(destination))
            else:
                shutil.copy2(_ext(entry), _ext(destination))

    def _verify_sqlite_sidecars(self, staging: Path) -> None:
        """Ensure ``-wal``/``-shm`` sidecars travelled with every SQLite store."""
        source = self.source
        assert source is not None
        store_rels = list(_SQLITE_STORES)
        agents_dir = source / "state" / "agents"
        if agents_dir.is_dir():
            for memory_db in sorted(agents_dir.glob("*/memory.db")):
                store_rels.append(memory_db.relative_to(source))
        for rel in store_rels:
            for suffix in ("", *_SQLITE_SIDECAR_SUFFIXES):
                source_file = source / rel.parent / (rel.name + suffix)
                if not source_file.is_file():
                    continue
                staged_file = staging / rel.parent / (rel.name + suffix)
                if staged_file.is_file():
                    continue
                staged_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_ext(source_file), _ext(staged_file))
                self._note(f"copied missing sqlite sidecar {rel}{suffix}")

    def _transform_staged_config(self, staging: Path) -> None:
        staged_config = staging / "config.toml"
        if not staged_config.is_file():
            return
        payload = self._config_payload
        if payload is None:
            # Sandbox validation failed: the config was copied as-is and the
            # error was already recorded during pre-flight.
            return
        try:
            staged_config.write_text(tomli_w.dumps(payload), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            self._record(
                "config",
                staged_config,
                self.target / "config.toml",
                "error",
                f"could not write the transformed config ({exc}); the original was "
                "copied as-is",
            )
            return
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
        if not self._env_additions:
            return
        env_path = staging / ".env"
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

    def _pause_scheduler_jobs(self, staged_db: Path) -> None:
        # Snapshot the pristine copy before mutating it, so a bad pause can
        # always be diagnosed/recovered from the migration report dir.
        snapshot_dir = self.output_dir / "db-snapshots"
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
            return
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
            connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(scheduler_jobs)")
                }
                if not columns:
                    return None
                rows = connection.execute(
                    "SELECT id, name, cron_expr FROM scheduler_jobs"
                ).fetchall()
            except sqlite3.Error:
                return None
        finally:
            connection.close()
        return [{"id": row[0], "name": row[1], "cron_expr": row[2]} for row in rows]

    def _commit(self, staging: Path) -> None:
        source = self.source
        assert source is not None
        self.target.mkdir(parents=True, exist_ok=True)
        entries = sorted(
            entry for entry in staging.iterdir() if entry.name != _COMMIT_JOURNAL
        )
        plan: list[dict[str, Any]] = []
        for entry in entries:
            destination = self.target / entry.name
            backup = (
                str(destination.with_name(f"{destination.name}.backup.{self.timestamp}"))
                if destination.exists()
                else None
            )
            plan.append({"from": str(entry), "to": str(destination), "backup": backup})
        journal = staging / _COMMIT_JOURNAL
        journal.write_text(
            json.dumps({"target": str(self.target), "renames": plan}, indent=2) + "\n",
            encoding="utf-8",
        )
        for entry in entries:
            destination = self.target / entry.name
            if destination.exists():
                if entry.name == "migration" and entry.is_dir() and destination.is_dir():
                    # The target migration/ dir may already hold this run's
                    # own output_dir (db snapshots); merge instead of
                    # clobbering it.
                    self._merge_into_existing_dir(entry, destination)
                    self._record(
                        "home-entry",
                        source / entry.name,
                        destination,
                        "migrated",
                        "merged with existing migration reports",
                    )
                    continue
                backup_path = destination.with_name(
                    f"{destination.name}.backup.{self.timestamp}"
                )
                os.replace(_ext(destination), _ext(backup_path))
                self._record(
                    "backup",
                    destination,
                    backup_path,
                    "migrated",
                    "existing target entry backed up",
                )
            os.replace(_ext(entry), _ext(destination))
            self._record("home-entry", source / entry.name, destination, "migrated")
        journal.unlink(missing_ok=True)
        shutil.rmtree(_ext(staging), ignore_errors=True)
        self._committed = True

    def _merge_into_existing_dir(self, staged_dir: Path, destination_dir: Path) -> None:
        for child in sorted(staged_dir.iterdir()):
            dest_child = destination_dir / child.name
            if dest_child.exists():
                if child.is_dir() and dest_child.is_dir():
                    self._merge_into_existing_dir(child, dest_child)
                    continue
                backup = dest_child.with_name(f"{dest_child.name}.backup.{self.timestamp}")
                os.replace(_ext(dest_child), _ext(backup))
            os.replace(_ext(child), _ext(dest_child))

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

    def _write_report_files(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._note("could not create the migration report directory")
            return
        self._wrote_output_dir = True
        report = self._report()
        (self.output_dir / "report.json").write_text(
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
        (self.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_source_marker(self) -> None:
        source = self.source
        if source is None:
            return
        payload = {
            "imported_at": datetime.now(UTC).isoformat(),
            "target": str(self.target),
        }
        try:
            (source / IMPORT_MARKER_FILENAME).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            self._note("could not write the completion marker into the source home")
