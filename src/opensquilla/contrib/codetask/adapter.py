"""LocalAdapter: run an OpenSquilla agent as a host subprocess.

Unlike the swebench OpenSquillaAdapter (which crosses a Docker boundary via
``docker exec``), this runs ``opensquilla agent`` directly on the host with
the repo as the working directory. The provider API key is inherited from
the runner's environment — no env-file is needed because there is no
container boundary to cross (codex review #3).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from opensquilla.contrib.codetask.config import (
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_ITERATION_TIMEOUT,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_PROVIDER_RETRIES,
    agent_config_path,
    agent_python,
)
from opensquilla.contrib.codetask.types import AgentOutcome

logger = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT_BUFFER = 120

_JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}")


class LocalAdapter:
    """Drives the host ``opensquilla agent`` CLI and returns a structured result."""

    def __init__(
        self,
        *,
        model: str = "",
        thinking: str = "",
        timeout: int = DEFAULT_AGENT_TIMEOUT,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ):
        self.model = model
        self.thinking = thinking
        self.timeout = timeout
        self.max_iterations = max_iterations

    def run(
        self,
        prompt: str,
        *,
        repo: Path,
        scratch_dir: Path,
        artifact_dir: Path,
    ) -> AgentOutcome:
        """Run one agent turn with ``repo`` as the workspace.

        Writes agent_stdout.log / agent_stderr.log / transcript.jsonl /
        usage.json into ``artifact_dir``.
        """
        # Start from a clean scratch dir: a stale verification.json from an
        # earlier run that reused this run_id must never be read back (codex).
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir, ignore_errors=True)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = artifact_dir / "transcript.jsonl"
        usage_path = artifact_dir / "usage.json"

        argv: list[str] = [
            "opensquilla",
            "agent",
            "--message",
            prompt,
            "--workspace",
            str(repo),
            # Read containment to the repo (codex review #9: explicit, not default).
            "--workspace-strict",
            # Write containment: writes must stay under workspace or scratch.
            "--workspace-lockdown",
            "--scratch-dir",
            str(scratch_dir),
            "--stateless",
            "--stateless-keep-project-rules",
            "--no-memory-capture",
            "--session-db-path",
            ":memory:",
            "--json",
            "--timeout",
            str(self.timeout),
            "--max-iterations",
            str(self.max_iterations),
            "--iteration-timeout-seconds",
            str(DEFAULT_ITERATION_TIMEOUT),
            "--max-provider-retries",
            str(DEFAULT_MAX_PROVIDER_RETRIES),
            "--transcript-path",
            str(transcript_path),
            "--usage-path",
            str(usage_path),
            "--permissions",
            "bypass",
        ]
        if self.model:
            argv += ["--model", self.model]
        if self.thinking:
            argv += ["--thinking", self.thinking]

        py_code = f"import sys\nsys.argv = {argv!r}\nfrom opensquilla.cli.main import app\napp()\n"
        cmd = [agent_python(), "-c", py_code]

        start = time.time()
        timed_out = False
        # cwd = repo so relative tool paths and test commands resolve there.
        # env inherits OPENROUTER_API_KEY and points the agent at code-task's
        # own config (OPENSQUILLA_GATEWAY_CONFIG_PATH) so coding-irrelevant tools
        # are denied while network + squilla_router stay on.
        # Isolate the agent and any install/test descendants into their own
        # process group / job so a timeout can kill the WHOLE tree, not just
        # the direct python child (codex review #6). POSIX uses
        # start_new_session (setsid); Windows uses CREATE_NEW_PROCESS_GROUP.
        # Give the agent a PER-RUN tool-result/media store under scratch instead
        # of the shared global media root. The tool-result store rescans every
        # record on disk on each provider request; against the global store (all
        # sessions' accumulated history) that becomes a quadratic disk scan that
        # can saturate the event loop and burn the whole timeout doing nothing.
        # A fresh per-run dir keeps the scanned set tiny (this run only) and stops
        # code-task polluting the global store. attachments.media_root wins in
        # media_root_from_config(); tool_result_store_dir = media_root/tool-results.
        run_media_root = scratch_dir.expanduser().resolve() / "media"
        per_run_config = artifact_dir / "agent-config.toml"
        _base_cfg = tomllib.loads(agent_config_path().read_text(encoding="utf-8"))
        _attachments = _base_cfg.setdefault("attachments", {})
        if not isinstance(_attachments, dict):
            raise RuntimeError("code-task agent config has invalid [attachments]")
        _attachments["media_root"] = str(run_media_root)
        per_run_config.write_text(tomli_w.dumps(_base_cfg), encoding="utf-8")
        agent_env = {
            **os.environ,
            "OPENSQUILLA_GATEWAY_CONFIG_PATH": str(per_run_config),
        }
        popen_kwargs: dict[str, Any] = dict(
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=agent_env,
        )
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError as exc:
            raise RuntimeError(f"could not launch agent interpreter: {exc}") from exc

        try:
            stdout, stderr = proc.communicate(timeout=self.timeout + SUBPROCESS_TIMEOUT_BUFFER)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            _kill_process_group(proc)
            stdout, stderr = proc.communicate()
            logger.warning("agent subprocess timed out after %ds; killed group", self.timeout)

        duration = time.time() - start
        (artifact_dir / "agent_stdout.log").write_text(stdout or "", encoding="utf-8")
        (artifact_dir / "agent_stderr.log").write_text(stderr or "", encoding="utf-8")

        envelope = _parse_json_envelope(stdout)
        if timed_out:
            finish = "timeout"
        elif exit_code != 0:
            finish = "error"
        elif envelope is None:
            finish = "empty"
        else:
            status = envelope.get("status")
            text = (envelope.get("text") or "").strip()
            errors = envelope.get("errors") or []
            if status == "ok" and text:
                finish = "stop"
            elif errors:
                finish = "error"
            else:
                finish = "empty"

        usage = (envelope or {}).get("usage") or {}
        return AgentOutcome(
            success=finish == "stop",
            timeout=timed_out,
            exit_code=exit_code,
            finish_reason=finish,
            duration_seconds=round(duration, 1),
            session_id=(envelope or {}).get("session_key"),
            usage=usage,
        )


def _kill_process_group(proc) -> None:
    """Kill the agent subprocess and its descendants (best effort).

    On POSIX we signal the entire process group via ``killpg`` so install /
    test grandchildren die too. On Windows there is no POSIX process group;
    ``taskkill /F /T /PID <pid>`` walks the Windows parent-tree, which is
    enough for ordinary subprocess descendants but is NOT a containment
    boundary (a child that detaches, re-parents to a service, or is launched
    via a scheduler is not bound to the tree and can survive). We fall back
    to ``proc.kill()`` (direct child only) if taskkill is unavailable or
    reports failure, so the outer ``proc.communicate()`` cannot hang on a
    still-running direct child.
    """
    import os
    import signal

    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    else:
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
            # taskkill returns nonzero when the target is already gone or it
            # can't reach a descendant. The direct child may still be alive,
            # so we only short-circuit on a clean exit; otherwise we fall
            # through to proc.kill() so the outer proc.communicate() can't
            # block forever on a half-killed tree.
            if r.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _parse_json_envelope(stdout: str) -> dict | None:
    if not stdout:
        return None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
            break
    for raw in reversed(_JSON_OBJECT_RE.findall(stdout)):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and "status" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _decode(data) -> str:
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data or ""
