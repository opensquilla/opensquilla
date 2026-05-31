"""Pre-validation migration for user-owned gateway config files."""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import tempfile
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from opensquilla.paths import default_opensquilla_home

DEPRECATED_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "memory.profile",
        "memory.cost.embedding_cache",
        "memory.cost.rerank_cache",
        "memory.cost.llm_judge_cache",
        "memory.facts_enabled",
        "memory.facts_top_k",
        "memory.facts_max_chars",
        "memory.multi_hop_enabled",
        "memory.multi_hop_max_depth",
        "memory.multi_hop_score_threshold",
        "memory.recall_frequency",
        "memory.recall_top_k_default",
        "memory.auto_recall_enabled",
        "memory.prefetch_enabled",
        "memory.prefetch_max_results",
        "memory.prefetch_min_score",
        "memory.prefetch_total_max_chars",
        "memory.semantic_chunking_enabled",
        "memory.eviction_policy",
        "memory.summary_model",
        "memory.summary_max_tokens",
    }
)

DEPRECATED_COST_LEAVES: frozenset[str] = frozenset(
    k.removeprefix("memory.cost.")
    for k in DEPRECATED_MEMORY_FIELDS
    if k.startswith("memory.cost.")
)
DEPRECATED_MEMORY_LEAVES: frozenset[str] = frozenset(
    k.removeprefix("memory.")
    for k in DEPRECATED_MEMORY_FIELDS
    if k.startswith("memory.") and not k.startswith("memory.cost.")
)

DEPRECATED_AGENT_TOKEN_SAVING_FIELDS: frozenset[str] = frozenset(
    {
        "agent_token_saving.tool_result_compression_enabled",
        "agent_token_saving.tool_result_compression_mode",
        "agent_token_saving.tool_result_compression_max_share",
        "agent_token_saving.tool_result_compression_summary_model",
        "agent_token_saving.tool_result_compression_summary_max_tokens",
        "agent_token_saving.tool_result_compression_summary_timeout_seconds",
        "agent_token_saving.tool_result_compression_summary_input_max_chars",
    }
)
DEPRECATED_AGENT_TOKEN_SAVING_LEAVES: frozenset[str] = frozenset(
    k.removeprefix("agent_token_saving.")
    for k in DEPRECATED_AGENT_TOKEN_SAVING_FIELDS
)

_LEGACY_MEMORY_FIELDS_WARN_LOCK = threading.Lock()
_LEGACY_MEMORY_FIELDS_WARNED = False
_LEGACY_MEMORY_FIELDS_SEEN: set[str] = set()
_LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARN_LOCK = threading.Lock()
_LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED = False
_LEGACY_AGENT_TOKEN_SAVING_FIELDS_SEEN: set[str] = set()


@dataclass(frozen=True)
class ConfigMigrationResult:
    payload: dict[str, Any]
    changes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    removed_fields: tuple[str, ...] = ()
    changed: bool = False


@dataclass
class _MigrationBuilder:
    payload: dict[str, Any]
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    removed_fields: list[str] = field(default_factory=list)

    def result(self) -> ConfigMigrationResult:
        changed = bool(self.changes or self.removed_fields)
        return ConfigMigrationResult(
            payload=self.payload,
            changes=tuple(self.changes),
            warnings=tuple(self.warnings),
            removed_fields=tuple(self.removed_fields),
            changed=changed,
        )


def handle_deprecated_memory_fields(
    found: dict[str, object],
    source: str,
) -> None:
    """Record and warn once for deprecated memory fields removed from config data."""
    global _LEGACY_MEMORY_FIELDS_WARNED

    if not found:
        return

    with _LEGACY_MEMORY_FIELDS_WARN_LOCK:
        _LEGACY_MEMORY_FIELDS_SEEN.update(found.keys())
        should_warn = not _LEGACY_MEMORY_FIELDS_WARNED
        if should_warn:
            _LEGACY_MEMORY_FIELDS_WARNED = True
            warning_fields = sorted(_LEGACY_MEMORY_FIELDS_SEEN)
        else:
            warning_fields = []

    _write_legacy_field_log(found, source)

    if should_warn:
        n = len(warning_fields)
        first_three = ", ".join(warning_fields[:3])
        try:
            logs_dir = default_opensquilla_home() / "logs"
            log_ref = str(logs_dir)
        except Exception:
            log_ref = "~/.opensquilla/logs"
        warnings.warn(
            f"OpenSquilla: {n} legacy memory.* config field(s) ignored "
            f"(e.g. {first_three}); see {log_ref} for details. "
            f"These fields will be removed in 0.2.0.",
            DeprecationWarning,
            stacklevel=6,
        )
        logging.getLogger(__name__).warning(
            "OpenSquilla: %d legacy memory.* config field(s) ignored (e.g. %s); "
            "see %s for details. These fields will be removed in 0.2.0.",
            n,
            first_three,
            log_ref,
        )


def handle_deprecated_agent_token_saving_fields(
    found: dict[str, object],
    source: str,
) -> None:
    """Record and warn once for deprecated token-saving fields removed from config data."""
    global _LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED

    if not found:
        return

    with _LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARN_LOCK:
        _LEGACY_AGENT_TOKEN_SAVING_FIELDS_SEEN.update(found.keys())
        should_warn = not _LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED
        if should_warn:
            _LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED = True
            warning_fields = sorted(_LEGACY_AGENT_TOKEN_SAVING_FIELDS_SEEN)
        else:
            warning_fields = []

    _write_legacy_field_log(found, source)

    if should_warn:
        n = len(warning_fields)
        first_three = ", ".join(warning_fields[:3])
        try:
            logs_dir = default_opensquilla_home() / "logs"
            log_ref = str(logs_dir)
        except Exception:
            log_ref = "~/.opensquilla/logs"
        warnings.warn(
            f"OpenSquilla: {n} legacy agent_token_saving.tool_result_compression_* "
            f"config field(s) migrated or ignored (e.g. {first_three}); see "
            f"{log_ref} for details. Tokenjuice projection is now the built-in "
            "tool-result path.",
            DeprecationWarning,
            stacklevel=6,
        )
        logging.getLogger(__name__).warning(
            "OpenSquilla: %d legacy agent_token_saving.tool_result_compression_* "
            "config field(s) migrated or ignored (e.g. %s); see %s for details. "
            "Tokenjuice projection is now the built-in tool-result path.",
            n,
            first_three,
            log_ref,
        )


def _write_legacy_field_log(found: dict[str, object], source: str) -> None:
    try:
        logs_dir = default_opensquilla_home() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        iso_now = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        log_path = logs_dir / f"legacy_config_{iso_now}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            for leaf, value in found.items():
                entry = {
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "field": leaf,
                    "source": source,
                    "value_repr": str(value)[:200],
                }
                fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def migrate_config_payload(data: dict[str, Any]) -> ConfigMigrationResult:
    """Return a config payload upgraded for the current strict schema.

    Call this only at user-owned disk-load boundaries, before GatewayConfig
    validates the payload.
    """
    builder = _MigrationBuilder(payload=copy.deepcopy(data))
    memory = builder.payload.get("memory")
    if isinstance(memory, dict):
        if memory.get("capture_mode") == "archive_turn_pair":
            memory["capture_mode"] = "turn_pair"
            builder.changes.append("memory.capture_mode: archive_turn_pair -> turn_pair")

        if "index_captured_turns" in memory:
            value = memory.pop("index_captured_turns")
            builder.removed_fields.append("memory.index_captured_turns")
            if bool(value):
                builder.warnings.append(
                    "memory.index_captured_turns was removed; captured turns are no "
                    "longer indexed into normal recall"
                )

        deprecated: dict[str, object] = {}
        for leaf in list(memory):
            if leaf in DEPRECATED_MEMORY_LEAVES:
                deprecated[f"memory.{leaf}"] = memory.pop(leaf)

        cost = memory.get("cost")
        if isinstance(cost, dict):
            for leaf in list(cost):
                if leaf in DEPRECATED_COST_LEAVES:
                    deprecated[f"memory.cost.{leaf}"] = cost.pop(leaf)
            if not cost:
                memory.pop("cost", None)

        if deprecated:
            builder.removed_fields.extend(sorted(deprecated))
            handle_deprecated_memory_fields(deprecated, "config_migration")

    token_saving = builder.payload.get("agent_token_saving")
    if isinstance(token_saving, dict):
        summary_input_leaf = "tool_result_compression_summary_input_max_chars"
        projection_leaf = "tool_result_projection_max_inline_chars"
        if summary_input_leaf in token_saving and projection_leaf not in token_saving:
            token_saving[projection_leaf] = token_saving[summary_input_leaf]
            builder.changes.append(
                "agent_token_saving.tool_result_compression_summary_input_max_chars "
                "-> agent_token_saving.tool_result_projection_max_inline_chars"
            )

        deprecated_token_saving: dict[str, object] = {}
        for leaf in list(token_saving):
            if leaf in DEPRECATED_AGENT_TOKEN_SAVING_LEAVES:
                deprecated_token_saving[f"agent_token_saving.{leaf}"] = token_saving.pop(leaf)

        if deprecated_token_saving:
            builder.removed_fields.extend(sorted(deprecated_token_saving))
            handle_deprecated_agent_token_saving_fields(
                deprecated_token_saving,
                "config_migration",
            )
            if (
                deprecated_token_saving.get(
                    "agent_token_saving.tool_result_compression_enabled"
                )
                is False
                or deprecated_token_saving.get(
                    "agent_token_saving.tool_result_compression_mode"
                )
                == "off"
            ):
                builder.warnings.append(
                    "agent_token_saving.tool_result_compression_* was removed; "
                    "tokenjuice projection is now the built-in tool-result path"
                )

    return builder.result()


def backup_and_write_migrated_config(
    path: str | Path,
    payload: dict[str, Any],
    result: ConfigMigrationResult,
) -> Path:
    """Back up and atomically replace a migrated user config file."""
    target = Path(path)
    backup = make_config_backup(target)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            tomli_w.dump(payload, fh)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    os.chmod(target, 0o600)
    logging.getLogger(__name__).warning(
        "OpenSquilla config migrated for 0.2.0 schema",
        extra={
            "path": str(target),
            "backup": str(backup),
            "changes": list(result.changes),
            "removed_fields": list(result.removed_fields),
            "warnings": list(result.warnings),
        },
    )
    return backup


def make_config_backup(target: str | Path) -> Path:
    """Create a collision-safe 0600 backup next to a config file."""
    source = Path(target)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    data = source.read_bytes()

    for attempt in range(1000):
        suffix = "" if attempt == 0 else f".{attempt}"
        backup = source.with_name(f"{source.name}.backup.{stamp}{suffix}")
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            try:
                os.unlink(backup)
            except OSError:
                pass
            raise
        backup.chmod(0o600)
        return backup

    raise FileExistsError(f"Could not create unique backup for {source}")
