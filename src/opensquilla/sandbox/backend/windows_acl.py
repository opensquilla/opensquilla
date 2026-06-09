from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from opensquilla.sandbox.types import SandboxBackendError

_MODE_TO_RIGHTS = {"rw": "M", "ro": "RX"}
_APPCONTAINER_SID_PREFIX = "S-1-15-2-"


def build_icacls_grant_argv(
    path: Path,
    appcontainer_sid: str,
    *,
    mode: str,
) -> tuple[str, ...]:
    rights = _MODE_TO_RIGHTS.get(mode)
    if rights is None:
        raise ValueError(f"unsupported ACL mode: {mode!r}")
    if not appcontainer_sid.startswith(_APPCONTAINER_SID_PREFIX):
        raise ValueError("appcontainer SID must start with S-1-15-2-")
    if path.exists() and not path.is_dir():
        return (
            "icacls",
            str(path),
            "/grant",
            f"*{appcontainer_sid}:{rights}",
            "/C",
        )

    return (
        "icacls",
        str(path),
        "/grant",
        f"*{appcontainer_sid}:(OI)(CI){rights}",
        "/T",
        "/C",
    )


def build_icacls_traverse_argv(path: Path, appcontainer_sid: str) -> tuple[str, ...]:
    if not appcontainer_sid.startswith(_APPCONTAINER_SID_PREFIX):
        raise ValueError("appcontainer SID must start with S-1-15-2-")
    return (
        "icacls",
        str(path),
        "/grant",
        f"*{appcontainer_sid}:RX",
        "/C",
    )


async def grant_path_to_appcontainer(
    path: Path,
    appcontainer_sid: str,
    *,
    mode: str,
) -> None:
    if sys.platform != "win32":
        raise SandboxBackendError("Windows ACL grants require native Windows")

    if path.exists() and not path.is_dir():
        await _run_icacls(build_icacls_traverse_argv(path.parent, appcontainer_sid), path.parent)
    argv = build_icacls_grant_argv(path, appcontainer_sid, mode=mode)
    await _run_icacls(argv, path)


async def _run_icacls(argv: tuple[str, ...], path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise SandboxBackendError(f"icacls grant failed for {path}: {detail}")
