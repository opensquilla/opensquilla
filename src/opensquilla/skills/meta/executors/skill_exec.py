"""Executor for ``skill_exec`` meta-steps.

Runs a wrapped-CLI skill via its ``entrypoint`` manifest — no LLM, no
sub-Agent. Resolves ``skill.entrypoint`` from the injected ``skill_loader``,
renders ``command`` / ``args`` (and optional ``env`` / ``stdin`` / ``assemble``
templates) against ``inputs`` + ``outputs`` + ``with`` (the step's
rendered ``with_args``), then runs the subprocess in a worker thread.
Stdout is interpreted per ``parse`` (``text`` | ``json`` |
``lines``) and returned as the step output.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path as _Path
from typing import Any

import jinja2
import structlog

from opensquilla.redaction import redact_error_text
from opensquilla.safety.secret_redaction import is_secret_key
from opensquilla.skills.capability_runtime import (
    META_CAPABILITY_API_KEY_ENV,
    META_CAPABILITY_BASE_URL_ENV,
    META_CAPABILITY_INTERNAL_CREDENTIAL_LEASE_TOKEN,
    META_CAPABILITY_INTERNAL_CREDENTIAL_SOURCE,
    META_CAPABILITY_INTERNAL_PROVIDER,
    META_CAPABILITY_INTERNAL_SESSION_KEY,
    META_CAPABILITY_PROVIDER_ENV,
    META_CAPABILITY_PROXY_ENV,
    META_OPENROUTER_API_KEY_ENV,
)
from opensquilla.skills.meta.replay_safety import (
    SAFE_NO_SUBMIT_EXIT_CODE,
    encode_paid_replay_safety,
    is_external_paid_step,
)
from opensquilla.skills.meta.templating import _JINJA_ENV, render_with_args
from opensquilla.skills.meta.types import MetaStep
from opensquilla.skills.runtime_env import managed_skill_env
from opensquilla.skills.types import SkillLayer

log = structlog.get_logger(__name__)

_ERROR_DETAIL_MAX_CHARS = 500
_ERROR_DETAIL_SCAN_CHARS = _ERROR_DETAIL_MAX_CHARS * 4
_REDACTED = "[REDACTED]"
_PAID_MEDIA_TRUSTED_ENV = frozenset(
    {
        META_CAPABILITY_PROVIDER_ENV,
        META_CAPABILITY_API_KEY_ENV,
        META_CAPABILITY_BASE_URL_ENV,
        META_CAPABILITY_PROXY_ENV,
        META_OPENROUTER_API_KEY_ENV,
    }
)
_TRUSTED_ENV_ALLOWLIST: dict[str, frozenset[str]] = {
    "nano-banana-pro": _PAID_MEDIA_TRUSTED_ENV,
    "seedance-2-prompt": _PAID_MEDIA_TRUSTED_ENV,
}
_PAID_REPLAY_SAFE_EXIT_SKILLS = frozenset(_TRUSTED_ENV_ALLOWLIST)
_PROFILE_POOL_SOURCE = "profile_pool"
_PROVIDER_FAILURE_EXIT_KINDS = {
    79: "auth_invalid",
    80: "insufficient_credits",
    81: "rate_limited",
}
# String sequences (OSC/DCS/SOS/PM/APC) tolerate a missing terminator so a
# diagnostic clipped by the subprocess cannot expose terminal control payloads.
_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x07\x1b\x9c\n]*(?:\x07|\x1b\\|\x9c)?"
    r"|[PX^_][^\x1b\x9c\n]*(?:\x1b\\|\x9c)?"
    r"|[@-Z\\-_]"
    r")"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r"|\x9d[^\x07\x9c\x1b\n]*(?:\x07|\x9c|\x1b\\)?"
    r"|[\x90\x98\x9e\x9f][^\x9c\x1b\n]*(?:\x9c|\x1b\\)?"
)
# Keep tabs/newlines readable while removing executable C0/C1 controls.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _is_sensitive_env_key(key: str) -> bool:
    lowered = key.lower()
    return (
        is_secret_key(lowered)
        or lowered.endswith(("token", "_token", "-token", ".token"))
        or key == META_CAPABILITY_PROXY_ENV
    )


def _declared_ambient_secret_keys(
    skill_spec: Any,
    *,
    effective_skill: str,
) -> frozenset[str]:
    """Return ambient secrets an exact code-owned skill may receive.

    Workspace/project overrides are intentionally denied all ambient secrets.
    Bundled skills retain only secret-shaped variables explicitly declared in
    their eligibility metadata. Paid-media capability consumers receive no
    ambient secrets at all: a validated parent's dedicated volatile key is
    injected later, after this filter.
    """

    if getattr(skill_spec, "layer", None) != SkillLayer.BUNDLED:
        return frozenset()
    # Provider-capability consumers are never allowed to rediscover an
    # ambient key while running under MetaOrchestrator. Otherwise an
    # untrusted workspace parent could compose the genuine bundled child and
    # bypass the trusted top-level workflow gate. Direct CLI invocation keeps
    # its documented environment behavior because it does not use this
    # executor.
    if effective_skill in _TRUSTED_ENV_ALLOWLIST:
        return frozenset()
    metadata = getattr(skill_spec, "metadata", None)
    requires = getattr(metadata, "requires", None)
    declared = (
        *(getattr(requires, "env", ()) or ()),
        *(getattr(requires, "env_any", ()) or ()),
    )
    return frozenset(
        name.casefold()
        for name in declared
        if isinstance(name, str) and name and _is_sensitive_env_key(name)
    )


def _report_profile_pool_failure(
    *,
    returncode: int,
    trusted_env: Mapping[str, str] | None,
) -> None:
    """Park a failed pooled key for the next explicit run, never this run.

    Only reserved exits from exact bundled paid-media entrypoints reach this
    helper. The internal provenance fields are created by the parent runtime,
    ignored by child environment injection, and contain no credential bytes.
    """

    kind_value = _PROVIDER_FAILURE_EXIT_KINDS.get(returncode)
    if kind_value is None or not trusted_env:
        return
    if (
        trusted_env.get(META_CAPABILITY_INTERNAL_CREDENTIAL_SOURCE)
        != _PROFILE_POOL_SOURCE
    ):
        return
    provider_id = str(trusted_env.get(META_CAPABILITY_INTERNAL_PROVIDER) or "").strip().lower()
    session_key = str(trusted_env.get(META_CAPABILITY_INTERNAL_SESSION_KEY) or "").strip()
    lease_token = str(
        trusted_env.get(META_CAPABILITY_INTERNAL_CREDENTIAL_LEASE_TOKEN) or ""
    ).strip()
    if not provider_id or not session_key or not lease_token:
        return
    try:
        from opensquilla.engine.selector_override import (
            report_profile_credential_lease_failure,
        )
        from opensquilla.provider.failures import ProviderFailureKind

        # Paid media must never fall back to the compatibility session-only
        # reporter: a stale child result could otherwise park a newer key.
        report_profile_credential_lease_failure(
            provider_id,
            session_key,
            lease_token,
            ProviderFailureKind(kind_value),
        )
    except (ImportError, ValueError):
        # Credential bookkeeping is fail-soft and must never replace the
        # original paid-step failure or trigger an automatic retry.
        log.debug(
            "meta_orchestrator.profile_pool_failure_report_failed",
            provider=provider_id,
            failure_kind=kind_value,
        )


def _sanitize_failure_stream(text: str, *, child_env: Mapping[str, str]) -> str:
    """Return a bounded, terminal-safe, secret-redacted failure stream."""

    if not text:
        return ""
    cleaned = _CONTROL_RE.sub(
        "",
        _ANSI_RE.sub("", text[:_ERROR_DETAIL_SCAN_CHARS]),
    ).strip()
    secret_values = {
        value
        for key, value in child_env.items()
        if value and _is_sensitive_env_key(key)
    }
    # Longest first prevents a shorter credential from exposing the remainder
    # of a longer credential that happens to contain it.
    for value in sorted(secret_values, key=len, reverse=True):
        cleaned = cleaned.replace(value, _REDACTED)
    return redact_error_text(cleaned, max_len=_ERROR_DETAIL_MAX_CHARS)


def _format_failure_detail(
    *,
    stderr_text: str,
    stdout_text: str,
    child_env: Mapping[str, str],
) -> str:
    """Prefer stderr, append stdout when it fits, and cap the total detail."""

    stderr = _sanitize_failure_stream(stderr_text, child_env=child_env)
    stdout = _sanitize_failure_stream(stdout_text, child_env=child_env)
    if stderr and stdout:
        detail = f"stderr: {stderr}\nstdout: {stdout}"
    else:
        detail = stderr or stdout
    if len(detail) <= _ERROR_DETAIL_MAX_CHARS:
        return detail
    return detail[: _ERROR_DETAIL_MAX_CHARS - 1].rstrip() + "…"


async def run_skill_exec_step(
    step: MetaStep,
    effective_skill: str,
    inputs: dict[str, Any],
    outputs: dict[str, str],
    *,
    skill_loader: Any,
    workspace_dir: str | None = None,
    trusted_env: Mapping[str, str] | None = None,
) -> str:
    """Run a wrapped-CLI skill via its ``entrypoint`` manifest — no LLM.

    Resolves ``skill.entrypoint`` from the loader, renders ``command`` /
    ``args`` against ``inputs`` + ``outputs`` + ``with`` (the step's
    rendered ``with_args``), then runs the subprocess in a worker thread.
    Stdout is interpreted per ``parse`` (``text`` |
    ``json`` | ``lines``) and returned as the step output.

    Optional features:

    * ``entrypoint.env`` — Jinja-rendered environment override keys and
      values. Empty rendered values are ignored so parent environment
      fallbacks survive.
    * ``entrypoint.stdin`` — Jinja-rendered template (with ``{baseDir}``
      substitution) piped to the subprocess's stdin.
    * ``entrypoint.assemble`` — a list of ``{into, from_template}``
      entries; each ``from_template`` is rendered and written to ``into``
      (resolved against ``workdir`` for relative paths) before the
      subprocess starts.
    * ``trusted_env`` — volatile parent-runtime values applied after manifest
      rendering. These values are never part of the Jinja context or argv and
      therefore cannot be persisted by the plan or redirected by workspace
      configuration.
    * Ambient secret-shaped variables are removed by default. An exact bundled
      skill may inherit only names declared in its eligibility requirements;
      project and workspace skills inherit none.

    Errors (missing entrypoint, non-zero exit, timeout, invalid JSON
    when ``parse=json``, invalid ``stdin``/``assemble`` shape) raise
    :class:`RuntimeError` so the orchestrator's step-failure path catches
    them and the meta-skill falls back to a normal turn instead of
    silently feeding garbage downstream.
    """

    skill_spec = skill_loader.get_by_name(effective_skill)
    if skill_spec is None:
        raise RuntimeError(
            f"step {step.id!r}: skill {effective_skill!r} not found in loader",
        )
    # Operator gate: a coding-mode / disabled skill stays unreachable even when
    # a meta-skill composes it as a step (codex review — every reach path).
    from opensquilla.skills.eligibility import is_skill_available_live

    if not is_skill_available_live(effective_skill):
        raise RuntimeError(
            f"step {step.id!r}: skill {effective_skill!r} is gated by operator config",
        )
    entrypoint = getattr(skill_spec, "entrypoint", None)
    if not isinstance(entrypoint, dict) or not entrypoint:
        raise RuntimeError(
            f"step {step.id!r}: skill {effective_skill!r} has no "
            f"entrypoint manifest — cannot run as skill_exec",
        )
    command_raw = entrypoint.get("command")
    if not isinstance(command_raw, str) or not command_raw.strip():
        raise RuntimeError(
            f"step {step.id!r}: skill {effective_skill!r} entrypoint "
            f"missing non-empty 'command'",
        )

    # Render with_args first so it becomes part of the Jinja context for
    # the entrypoint templates (lets the entrypoint reference ``with.q``
    # in addition to the global ``inputs`` / ``outputs``).
    rendered_with = render_with_args(step.with_args, inputs=inputs, outputs=outputs)
    base_dir = str(getattr(skill_spec, "base_dir", "") or "")
    context = {
        "inputs": inputs,
        "outputs": outputs,
        "with": rendered_with,
        "baseDir": base_dir,
    }

    def _render(value: str) -> str:
        try:
            return _JINJA_ENV.from_string(value).render(**context)
        except jinja2.UndefinedError as exc:
            raise RuntimeError(f"entrypoint template undefined: {exc}") from exc
        except jinja2.TemplateSyntaxError as exc:
            raise RuntimeError(f"entrypoint template syntax error: {exc}") from exc

    # `{baseDir}` is a static placeholder (not Jinja) — substitute before
    # rendering so it survives shlex.split() below.
    command_str = command_raw.replace("{baseDir}", base_dir)
    command_str = _render(command_str)

    raw_args = entrypoint.get("args") or []
    if not isinstance(raw_args, list):
        raise RuntimeError(
            f"step {step.id!r}: entrypoint.args must be a list",
        )
    rendered_args: list[str] = []
    for index, item in enumerate(raw_args):
        if not isinstance(item, str):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.args[{index}] must be a string",
            )
        rendered_args.append(_render(item.replace("{baseDir}", base_dir)))

    # Resolve cwd early so assemble's relative-path anchoring matches the
    # subprocess's working directory. Precedence:
    # 1. ``entrypoint.cwd`` — skill-author override, wins everything.
    # 2. orchestrator-level ``workspace_dir`` — shared workspace for the
    #    whole meta-skill so cross-skill files (results.csv → plot,
    #    references.bib → bibtex, etc.) land in the same tree.
    # 3. ``base_dir`` — fallback to the skill's own directory.
    cwd = entrypoint.get("cwd")
    if isinstance(cwd, str) and cwd:
        cwd = cwd.replace("{baseDir}", base_dir)
        workdir: str | None = cwd
    elif workspace_dir:
        workdir = workspace_dir
    else:
        workdir = base_dir or None
    allowed_workdir_root = workspace_dir or base_dir
    if workdir and allowed_workdir_root:
        allowed_root = _Path(allowed_workdir_root).expanduser().resolve()
        workdir_path = _Path(workdir).expanduser()
        if not workdir_path.is_absolute():
            workdir_path = allowed_root / workdir_path
        resolved_workdir = workdir_path.resolve()
        if (
            resolved_workdir != allowed_root
            and not resolved_workdir.is_relative_to(allowed_root)
        ):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.cwd path "
                f"{resolved_workdir!s} escapes allowed root "
                f"{allowed_root!s}",
            )
        resolved_workdir.mkdir(parents=True, exist_ok=True)
        workdir = str(resolved_workdir)

    # Optional assemble: render templated files to disk before exec.
    assemble_raw = entrypoint.get("assemble") or []
    if assemble_raw and not isinstance(assemble_raw, list):
        raise RuntimeError(
            f"step {step.id!r}: entrypoint.assemble must be a list of mappings",
        )
    for index, entry in enumerate(assemble_raw):
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.assemble[{index}] must be a mapping",
            )
        into_raw = entry.get("into")
        template_raw = entry.get("from_template")
        if not isinstance(into_raw, str) or not into_raw:
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.assemble[{index}] missing 'into'",
            )
        if not isinstance(template_raw, str):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.assemble[{index}] missing "
                f"'from_template'",
            )
        into_path_str = _render(into_raw.replace("{baseDir}", base_dir))
        template_body = _render(template_raw.replace("{baseDir}", base_dir))
        # Relative paths anchor to cwd (workdir), absolute paths pass through.
        target = _Path(into_path_str)
        if not target.is_absolute() and workdir:
            target = _Path(workdir) / target
        # Path-traversal defence: resolve to canonical form then ensure
        # the target stays within the allowed root. Precedence matches
        # the cwd resolution above:
        # 1. orchestrator-level ``workspace_dir`` — the shared meta-skill
        #    workspace tree (preferred root when set).
        # 2. ``base_dir`` — the skill's own directory.
        # An ``assemble.into`` of ``../../etc/passwd`` or an absolute path
        # outside the root would otherwise let a malicious or buggy
        # skill author write arbitrary files.
        allowed_root_str = workspace_dir or base_dir
        if allowed_root_str:
            allowed_root = _Path(allowed_root_str).resolve()
            resolved = target.resolve()
            if (
                resolved != allowed_root
                and not resolved.is_relative_to(allowed_root)
            ):
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.assemble[{index}] 'into' "
                    f"path {resolved!s} escapes allowed root "
                    f"{allowed_root!s}",
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template_body, encoding="utf-8")
        log.info(
            "meta_orchestrator.skill_exec_assemble",
            step=step.id,
            into=str(target),
            bytes=len(template_body),
        )

    argv = shlex.split(command_str, posix=os.name != "nt") + rendered_args
    if not argv:
        raise RuntimeError(f"step {step.id!r}: empty argv after rendering")

    # Resolve bare interpreter names ("python", "python3") to the current
    # process's sys.executable so wrapped-CLI skills authored as
    # `command: python <script>` work regardless of whether the parent
    # process's PATH includes a "python" symlink (e.g. uv-managed venvs
    # ship only "python" inside .venv/bin but the gateway's runtime PATH
    # may not surface it). Absolute paths and other commands pass through
    # unchanged so authors can pin a specific interpreter when needed.
    if argv[0] in ("python", "python3"):
        argv[0] = sys.executable

    timeout_raw = entrypoint.get("timeout", 60.0)
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = 60.0
    parse_mode = str(entrypoint.get("parse", "text"))

    raw_env = entrypoint.get("env") or {}
    if raw_env and not isinstance(raw_env, dict):
        raise RuntimeError(
            f"step {step.id!r}: entrypoint.env must be a mapping",
        )
    # Do not hand the Gateway's complete credential environment to arbitrary
    # skill subprocesses. Only an exact bundled skill may inherit a
    # secret-shaped variable, and only when its manifest declares that name.
    # Parent-resolved paid-media credentials take the stricter path below and
    # are injected under one dedicated volatile name after ambient filtering.
    allowed_ambient_secrets = _declared_ambient_secret_keys(
        skill_spec,
        effective_skill=effective_skill,
    )
    child_env = managed_skill_env(os.environ)
    for key in tuple(child_env):
        if (
            _is_sensitive_env_key(key)
            and key.casefold() not in allowed_ambient_secrets
        ):
            child_env.pop(key, None)
    if isinstance(raw_env, dict):
        for key, value in raw_env.items():
            if not isinstance(key, str) or not key:
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.env keys must be non-empty strings",
                )
            if not isinstance(value, str):
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.env[{key!r}] must be a string template",
                )
            rendered_key = _render(key.replace("{baseDir}", base_dir))
            if not rendered_key:
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.env key rendered empty",
                )
            rendered_value = _render(value.replace("{baseDir}", base_dir))
            if rendered_value:
                child_env[rendered_key] = rendered_value

    # Parent-resolved credentials override manifest/ambient values, but only
    # for the exact skill selected by MetaOrchestrator. Validate the in-memory
    # boundary defensively and never render these values through Jinja.
    allowed_trusted_keys = (
        _TRUSTED_ENV_ALLOWLIST.get(effective_skill, frozenset())
        if getattr(skill_spec, "layer", None) == SkillLayer.BUNDLED
        else frozenset()
    )
    for key, value in (trusted_env or {}).items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise RuntimeError(f"step {step.id!r}: trusted child env is invalid")
        if key in allowed_trusted_keys and value:
            child_env[key] = value

    # Optional stdin: render Jinja template and pipe to the subprocess.
    stdin_raw = entrypoint.get("stdin")
    stdin_bytes: bytes | None = None
    if isinstance(stdin_raw, str) and stdin_raw:
        stdin_text = _render(stdin_raw.replace("{baseDir}", base_dir))
        try:
            stdin_bytes = stdin_text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.stdin rendered to text that "
                f"cannot be encoded as UTF-8: {exc}",
            ) from exc
    elif stdin_raw not in (None, ""):
        raise RuntimeError(
            f"step {step.id!r}: entrypoint.stdin must be a string template",
        )

    log.info(
        "meta_orchestrator.skill_exec_spawn",
        step=step.id,
        skill=effective_skill,
        argv_head=argv[0],
        argc=len(argv),
        timeout=timeout,
        parse=parse_mode,
        stdin_bytes=len(stdin_bytes) if stdin_bytes is not None else 0,
    )

    # Run subprocess.run in a dedicated thread. This avoids asyncio
    # child-watcher flakiness across repeated pytest event loops without
    # blocking the gateway event loop for long-running wrapped CLIs.
    completed_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _run_sync() -> None:
        try:
            completed_box["completed"] = subprocess.run(  # noqa: S603 - argv is manifest-authored and pre-split.
                argv,
                input=stdin_bytes,
                capture_output=True,
                cwd=workdir,
                env=child_env,
                timeout=timeout,
                check=False,
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised on event-loop thread
            error_box["error"] = exc

    thread = threading.Thread(
        target=_run_sync,
        name=f"meta-skill-exec-{step.id}",
        daemon=True,
    )
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.05)

    if "error" in error_box:
        err = error_box["error"]
        if isinstance(err, FileNotFoundError):
            message = f"skill {effective_skill!r} command not found: {argv[0]!r}"
            if is_external_paid_step(step):
                message = encode_paid_replay_safety(message, safe_no_submit=True)
            raise RuntimeError(message) from err
        if isinstance(err, subprocess.TimeoutExpired):
            message = f"skill {effective_skill!r} timed out after {timeout}s"
            if is_external_paid_step(step):
                # Once the child starts, a timeout cannot prove whether its
                # non-idempotent provider POST was accepted.
                message = encode_paid_replay_safety(message, safe_no_submit=False)
            raise RuntimeError(message) from err
        raise err

    completed = completed_box["completed"]

    returncode = completed.returncode
    stdout_bytes = completed.stdout
    stderr_bytes = completed.stderr
    stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
    if returncode != 0:
        detail = _format_failure_detail(
            stderr_text=stderr_text,
            stdout_text=stdout_text,
            child_env=child_env,
        )
        if is_external_paid_step(step):
            if (
                effective_skill in _PAID_REPLAY_SAFE_EXIT_SKILLS
                and getattr(skill_spec, "layer", None) == SkillLayer.BUNDLED
            ):
                _report_profile_pool_failure(
                    returncode=returncode,
                    trusted_env=trusted_env,
                )
            detail = encode_paid_replay_safety(
                detail,
                # Do not trust stderr: provider-controlled diagnostics could
                # spoof text. Only audited bundled entrypoints may assert the
                # reserved pre-submit exit code.
                safe_no_submit=(
                    returncode == SAFE_NO_SUBMIT_EXIT_CODE
                    and effective_skill in _PAID_REPLAY_SAFE_EXIT_SKILLS
                    and getattr(skill_spec, "layer", None) == SkillLayer.BUNDLED
                ),
            )
        raise RuntimeError(
            f"skill {effective_skill!r} exited {returncode}: "
            f"{detail}",
        )

    if parse_mode == "json":
        try:
            parsed = _json.loads(stdout_text)
        except _json.JSONDecodeError as exc:
            raise RuntimeError(
                f"skill {effective_skill!r} stdout was not valid JSON: {exc}",
            ) from exc
        return _json.dumps(parsed, ensure_ascii=False)
    if parse_mode == "lines":
        lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
        return _json.dumps(lines, ensure_ascii=False)
    return stdout_text.strip()


__all__ = ["run_skill_exec_step"]
