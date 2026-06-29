"""Execution: carry out an :class:`UninstallPlan` behind safety guards.

The planner already decided *what*; this module does it, re-checking every
deletion against :mod:`~opensquilla.uninstall.safety` (defense in depth — a plan
bug must still not delete outside a resolved, non-protected root). Order matters:
the gateway is quiesced first, and if a live gateway cannot be stopped, execution
**aborts before any file deletion** so files are never removed out from under a
running process.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opensquilla.uninstall import safety
from opensquilla.uninstall.inventory import Inventory
from opensquilla.uninstall.plan import Action, UninstallPlan


@dataclass
class ActionResult:
    kind: str
    summary: str
    ok: bool
    detail: str = ""
    paths: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "summary": self.summary,
            "ok": self.ok,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.paths:
            payload["paths"] = self.paths
        return payload


@dataclass
class ExecutionResult:
    results: list[ActionResult] = field(default_factory=list)
    ok: bool = True
    aborted: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "aborted": self.aborted,
            "results": [r.to_payload() for r in self.results],
        }


def execute(plan: UninstallPlan, inventory: Inventory) -> ExecutionResult:
    """Execute ``plan``. Returns an :class:`ExecutionResult` (never raises for
    expected failures; collects per-action outcomes)."""
    result = ExecutionResult()
    home = inventory.home
    # Explicit allowlist of roots a `remove-tree` may target: the home itself and
    # each portable program tree. A tree-root removal must resolve to exactly one
    # of these — never to an arbitrary path.parent — so a plan/receipt bug can't
    # widen the blast radius (the protected-root check is then a second gate).
    trusted_roots = {safety.resolve_real(home)}
    for program in inventory.program_paths:
        trusted_roots.add(safety.resolve_real(program))

    for action in plan.actions:
        if action.kind == "stop-gateway":
            r = _quiesce_gateway(inventory)
            result.results.append(r)
            if not r.ok:
                # A live gateway we could not stop — do NOT delete files under a
                # running process. Abort before anything destructive.
                result.ok = False
                result.aborted = True
                return result
            continue

        if action.kind == "unregister-service":
            result.results.append(_unregister_service(action))
            continue

        if action.kind == "run-package-uninstall":
            r = _run_commands(action)
            result.results.append(r)
            result.ok = result.ok and r.ok
            continue

        if action.kind in ("remove-path", "remove-tree"):
            is_root = action.kind == "remove-tree"
            r = _remove_paths(
                action, home=home, trusted_roots=trusted_roots, is_root_removal=is_root
            )
            result.results.append(r)
            result.ok = result.ok and r.ok
            continue

        # Unknown action kinds are recorded but not acted on.
        result.results.append(ActionResult(action.kind, action.summary, ok=True, detail="no-op"))

    return result


def _quiesce_gateway(inventory: Inventory) -> ActionResult:
    """Stop the gateway before any deletion. Fail CLOSED: when liveness cannot be
    determined, refuse (ok=False) so files are never deleted under a live process.

    Only a genuinely absent lifecycle module (ImportError) is treated as "nothing
    to stop"; every other error blocks the uninstall.
    """
    try:
        from opensquilla.cli.gateway_lifecycle import GatewayLifecycleManager
    except ImportError:
        return ActionResult(
            "stop-gateway", "Gateway runtime not present", ok=True, detail="no lifecycle module"
        )

    try:
        # Resolve host/port from the actual config so the probe targets the real
        # gateway (a configured non-default port would otherwise be missed).
        host = "127.0.0.1"
        port = 18791
        try:
            from opensquilla.gateway.config import GatewayConfig

            cfg = GatewayConfig.load(str(inventory.config_path) if inventory.config_path else None)
            host = cfg.host or "127.0.0.1"
            port = cfg.port
        except Exception:  # noqa: BLE001 — fall back to defaults if config won't load
            pass

        mgr = GatewayLifecycleManager(
            host=host,
            port=port,
            config_path=str(inventory.config_path) if inventory.config_path else None,
        )
        status = mgr.status()
        if status.state in ("not_started", "stale"):
            return ActionResult("stop-gateway", "Gateway not running", ok=True, detail=status.state)
        if status.state in ("unmanaged", "target_mismatch"):
            return ActionResult(
                "stop-gateway",
                "A gateway is running that this command cannot stop",
                ok=False,
                detail=(
                    f"state={status.state}; stop it manually (opensquilla gateway stop) and re-run."
                ),
            )
        stop = mgr.stop()
        if stop.exit_code == 0:
            return ActionResult("stop-gateway", "Gateway stopped", ok=True, detail=stop.state)
        return ActionResult(
            "stop-gateway",
            "Could not stop the running gateway",
            ok=False,
            detail=stop.message or stop.state,
        )
    except Exception as exc:  # noqa: BLE001 — destructive op: unknown state must block
        return ActionResult(
            "stop-gateway",
            "Could not determine gateway state; refusing to delete",
            ok=False,
            detail=f"{exc}; stop the gateway manually (opensquilla gateway stop) and re-run.",
        )


def _unregister_service(action: Action) -> ActionResult:
    """Run a service's unregister commands, then remove its unit file (best-effort)."""
    detail_parts: list[str] = []
    for command in action.commands:
        code = _run_one(command)
        detail_parts.append(f"{command[0]}={code}")
    removed: list[str] = []
    for raw in action.paths:
        path = Path(raw)
        if path.exists() and safety.is_within(path, safety.home_dir()):
            try:
                path.unlink()
                removed.append(str(path))
            except OSError as exc:
                detail_parts.append(f"rm-failed:{exc}")
    # Service teardown is best-effort: a missing/already-disabled unit is fine.
    return ActionResult(
        "unregister-service",
        action.summary,
        ok=True,
        detail="; ".join(detail_parts),
        paths=removed,
    )


def _run_commands(action: Action) -> ActionResult:
    ok = True
    details: list[str] = []
    for command in action.commands:
        code = _run_one(command)
        details.append(f"{' '.join(command)} -> exit {code}")
        ok = ok and code == 0
    return ActionResult(action.kind, action.summary, ok=ok, detail="; ".join(details))


def _run_one(command: list[str]) -> int:
    try:
        completed = subprocess.run(  # noqa: S603 - argv built internally, shell=False
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return completed.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        return _COMMAND_ERROR if isinstance(exc, OSError) else _COMMAND_TIMEOUT


_COMMAND_ERROR = 127
_COMMAND_TIMEOUT = 124


def _remove_paths(
    action: Action, *, home: Path, trusted_roots: set[Path], is_root_removal: bool
) -> ActionResult:
    removed: list[str] = []
    failures: list[str] = []
    for raw in action.paths:
        path = Path(raw)
        ok, detail = _safe_remove(
            path, home=home, trusted_roots=trusted_roots, is_root_removal=is_root_removal
        )
        if ok:
            if detail != "absent":
                removed.append(str(path))
        else:
            failures.append(f"{path}: {detail}")
    return ActionResult(
        action.kind,
        action.summary,
        ok=not failures,
        detail="; ".join(failures),
        paths=removed,
    )


def _safe_remove(
    path: Path, *, home: Path, trusted_roots: set[Path], is_root_removal: bool
) -> tuple[bool, str]:
    """Delete ``path`` only if it passes containment + protected-root checks."""
    if is_root_removal:
        # A whole-tree removal must (1) not be a protected/dangerous root and
        # (2) resolve to an explicitly trusted root (the home or a known program
        # tree) — not merely live under its own parent.
        if safety.is_protected_root(path):
            return False, f"refused: protected root ({safety.protected_root_reason(path)})"
        if safety.resolve_real(path) not in trusted_roots:
            return False, "refused: not a trusted removal root"
        is_symlink = path.is_symlink()
    else:
        # A bucket/file removal must live within the OpenSquilla home. For a
        # symlink, validate where the link *lives* (its parent), not where it
        # points — we delete the link itself, never follow it.
        is_symlink = path.is_symlink()
        containment_target = path.parent if is_symlink else path
        if not safety.is_within(containment_target, home):
            return False, "refused: outside the OpenSquilla home"
    try:
        if is_symlink:
            # Remove the link itself, never follow it into its target tree.
            path.unlink()
            return True, "removed-symlink"
        if path.is_dir():
            shutil.rmtree(path)
            return True, "removed-tree"
        if path.exists():
            path.unlink()
            return True, "removed-file"
        return True, "absent"
    except OSError as exc:
        return False, f"error: {exc}"
