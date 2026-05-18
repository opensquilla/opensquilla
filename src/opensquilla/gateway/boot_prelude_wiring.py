"""Gateway boot prelude wiring boundary."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from opensquilla.gateway.config import GatewayConfig
from opensquilla.paths import default_opensquilla_home

log = structlog.get_logger(__name__)

ConfigLoader = Callable[[str | None], GatewayConfig]
FileLoggingSetup = Callable[[GatewayConfig], None]
SkillFilterBanner = Callable[[Any], None]
StatePathFactory = Callable[[GatewayConfig, str], Path]
GatewayPidLockFactory = Callable[[Path], Any]
TokenFactory = Callable[[int], str]


@dataclass
class GatewayBootPrelude:
    """Effective gateway config plus the held PID lock."""

    config: GatewayConfig
    pid_lock: Any


def _default_state_path(config: GatewayConfig, filename: str) -> Path:
    state_root = Path(config.state_dir or default_opensquilla_home() / "state")
    return state_root / filename


def _default_gateway_pid_lock_factory(state_dir: Path) -> Any:
    from opensquilla.gateway.pidlock import GatewayPidLock

    return GatewayPidLock(state_dir)


def _noop_file_logging(_config: GatewayConfig) -> None:
    return None


def _noop_skill_filter_banner(_skills_cfg: Any) -> None:
    return None


def build_gateway_boot_prelude(
    *,
    port: int | None = None,
    config: GatewayConfig | None = None,
    config_loader: ConfigLoader = GatewayConfig.load,
    setup_file_logging: FileLoggingSetup = _noop_file_logging,
    skill_filter_banner: SkillFilterBanner = _noop_skill_filter_banner,
    state_path_factory: StatePathFactory = _default_state_path,
    gateway_pid_lock_factory: GatewayPidLockFactory = _default_gateway_pid_lock_factory,
    token_urlsafe: TokenFactory = secrets.token_urlsafe,
    environ: MutableMapping[str, str] | None = None,
    logger: Any = log,
) -> GatewayBootPrelude:
    """Run gateway pre-service side effects and return retained boot state."""
    env = os.environ if environ is None else environ
    if config is None:
        config = config_loader(env.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))

    if port is not None:
        config = config.model_copy(update={"port": port})

    setup_file_logging(config)
    if config.config_path:
        logger.info("gateway.config_loaded", path=config.config_path)

    env["OPENSQUILLA_GATEWAY_PORT"] = str(config.port)

    if config.auth.mode == "token" and not config.auth.token:
        token = token_urlsafe(32)
        config.auth = config.auth.model_copy(update={"token": token})
        config.mark_runtime_secret("auth.token")
        logger.info("gateway.auth_token_generated")

    if config.control_ui.enabled:
        from opensquilla.gateway.control_ui import _STATIC_DIR, _TEMPLATE_DIR

        if not _TEMPLATE_DIR.is_dir():
            logger.warning("gateway.control_ui.templates_missing", path=str(_TEMPLATE_DIR))
        if not _STATIC_DIR.is_dir():
            logger.warning("gateway.control_ui.static_missing", path=str(_STATIC_DIR))
        logger.info(
            "gateway.control_ui.resolved",
            base_path=config.control_ui.base_path,
            templates=str(_TEMPLATE_DIR),
            static=str(_STATIC_DIR),
        )
    else:
        logger.info("gateway.control_ui.disabled")

    skill_filter_banner(config.skills)

    pid_lock = gateway_pid_lock_factory(state_path_factory(config, ""))
    pid_lock.acquire()
    return GatewayBootPrelude(config=config, pid_lock=pid_lock)
