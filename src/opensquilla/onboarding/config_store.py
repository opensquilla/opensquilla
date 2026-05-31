"""Config persistence: load/validate/atomic write with backup + 0600 mode."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.config_migration import (
    backup_and_write_migrated_config,
    make_config_backup,
    migrate_config_payload,
)
from opensquilla.paths import default_opensquilla_home

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersistResult:
    path: Path
    backup_path: Path | None
    restart_required: bool
    warnings: list[str] = field(default_factory=list)


def resolve_config_path(path: str | Path | None = None) -> tuple[Path, str]:
    """Return (resolved_path, source) using gateway-equivalent precedence.

    source is one of: "explicit", "env", "cwd", "home".
    Mirrors GatewayConfig.load (see gateway/config.py) so the CLI never
    silently writes to a different file than the gateway will read.
    """
    if path is not None:
        return Path(path).expanduser(), "explicit"
    explicit = os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH")
    if explicit:
        return Path(explicit).expanduser(), "env"
    cwd_candidate = Path.cwd() / "opensquilla.toml"
    if cwd_candidate.is_file():
        return cwd_candidate, "cwd"
    return default_opensquilla_home() / "config.toml", "home"


def default_config_path() -> Path:
    return resolve_config_path(None)[0]


def _resolve_path(path: str | Path | None) -> Path:
    return resolve_config_path(path)[0]


def load_config(path: str | Path | None = None) -> GatewayConfig:
    target = _resolve_path(path)
    if not target.exists():
        cfg = GatewayConfig()
        if cfg.llm.api_key:
            cfg.mark_runtime_secret("llm.api_key")
        cfg.config_path = str(target)
        return cfg
    with target.open("rb") as fh:
        data = tomllib.load(fh)
    migration = migrate_config_payload(data)
    cfg = GatewayConfig.model_validate(migration.payload)
    if migration.changed:
        backup_and_write_migrated_config(target, migration.payload, migration)
    llm_payload = data.get("llm") if isinstance(data, dict) else None
    if (
        (not isinstance(llm_payload, dict) or "api_key" not in llm_payload)
        and cfg.llm.api_key
    ):
        cfg.mark_runtime_secret("llm.api_key")
    cfg.config_path = str(target)
    return cfg


def validate_config_payload(payload: dict[str, Any]) -> GatewayConfig:
    return GatewayConfig.model_validate(payload)


def _toml_safe(value: Any) -> Any:
    """Recursively coerce model-dump output into TOML-safe primitives."""
    if isinstance(value, dict):
        return {k: _toml_safe(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_toml_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _toml_safe(value.model_dump(mode="python"))
    return str(value)


def _config_to_toml_dict(cfg: GatewayConfig) -> dict[str, Any]:
    raw = cfg.to_toml_dict() if hasattr(cfg, "to_toml_dict") else cfg.model_dump(
        mode="python", exclude_none=True
    )
    coerced = _toml_safe(raw)
    assert isinstance(coerced, dict)
    return coerced


def persist_config(
    config: GatewayConfig,
    *,
    path: str | Path | None = None,
    backup: bool = True,
    restart_required: bool = False,
) -> PersistResult:
    payload = _config_to_toml_dict(config)
    # Re-validate to catch any invariant breakage that survived model_dump.
    GatewayConfig.model_validate(payload)

    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if backup and target.exists():
        backup_path = make_config_backup(target)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
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

    log.debug(
        "onboarding.config_persisted path=%s backup=%s restart_required=%s",
        str(target),
        str(backup_path) if backup_path else None,
        restart_required,
    )

    return PersistResult(
        path=target,
        backup_path=backup_path,
        restart_required=restart_required,
        warnings=[],
    )
