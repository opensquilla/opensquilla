"""Inner-stage filesystem worker execution for the Linux sandbox helper."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from opensquilla.sandbox.backend.linux_payload import HelperPayload


async def run_filesystem_payload(payload: HelperPayload) -> dict[str, Any]:
    if payload.filesystem is None:
        raise ValueError("filesystem payload is required")
    worker_payload_path = Path(payload.filesystem.worker_payload_path)
    worker_payload_path.parent.mkdir(parents=True, exist_ok=True)
    worker_payload_path.write_text(
        json.dumps(payload.filesystem.worker_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "opensquilla.sandbox.filesystem_worker",
        str(worker_payload_path),
        cwd=Path(payload.cwd),
        env={**os.environ, **payload.env},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, stderr_raw = await asyncio.wait_for(
        proc.communicate(),
        timeout=float(payload.policy.get("wallTimeoutS", 60.0)),
    )
    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "filesystem worker failed"
        raise RuntimeError(detail)
    result = json.loads(stdout)
    if not isinstance(result, dict):
        raise RuntimeError("filesystem worker returned invalid payload")
    return result
