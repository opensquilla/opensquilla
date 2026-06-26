"""Coding-mode toggle: ON enforces code-task, OFF makes it unreachable."""

from __future__ import annotations

import shlex
import sys
from types import SimpleNamespace

import pytest

from opensquilla.engine.steps.coding_mode import enforce_coding_mode
from opensquilla.engine.steps.skills_filter import _eligibility_ctx
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc_config import _SAFE_WRITE_PATCH_PATHS
from opensquilla.skills.eligibility import (
    CODING_MODE_SKILLS,
    effective_disabled,
    is_skill_available,
)
from opensquilla.tools.policy_config import (
    CODING_MODE_DENIED_TOOLS,
    coding_mode_denied_tools,
)


class TestAvailabilityHelper:
    def test_codetask_gated_when_coding_mode_off(self):
        assert is_skill_available("code-task", disabled=[], coding_mode=False) is False

    def test_codetask_available_when_coding_mode_on(self):
        assert is_skill_available("code-task", disabled=[], coding_mode=True) is True

    def test_other_skill_unaffected_by_coding_mode(self):
        assert is_skill_available("git-diff", disabled=[], coding_mode=False) is True

    def test_other_skill_still_respects_disabled(self):
        assert is_skill_available("git-diff", disabled=["git-diff"], coding_mode=True) is False

    def test_effective_disabled_adds_codetask_when_off(self):
        assert CODING_MODE_SKILLS <= effective_disabled([], coding_mode=False)
        assert "code-task" not in effective_disabled([], coding_mode=True)


class TestConfig:
    def test_coding_mode_defaults_off(self):
        assert GatewayConfig().skills.coding_mode is False

    def test_coding_mode_is_safe_write_path(self):
        assert "skills.coding_mode" in _SAFE_WRITE_PATCH_PATHS


class TestSkillsFilterGate:
    def test_off_gates_codetask(self):
        ctx = _eligibility_ctx(SimpleNamespace(disabled=[], coding_mode=False))
        assert "code-task" in ctx.disabled_set

    def test_on_does_not_gate_codetask(self):
        ctx = _eligibility_ctx(SimpleNamespace(disabled=[], coding_mode=True))
        assert "code-task" not in ctx.disabled_set


class TestDirectiveInjection:
    @pytest.fixture(autouse=True)
    def _stub_resolver(self, monkeypatch):
        # Deterministic, no subprocess: the directive's command line is the
        # resolved code-task invocation; pin it for these assertions.
        from opensquilla.engine.steps import coding_mode as _cm
        monkeypatch.setattr(
            _cm, "resolve_code_task_command", lambda: "/opt/x/opensquilla code-task"
        )

    def _ctx(self, coding_mode: bool):
        return SimpleNamespace(
            config=SimpleNamespace(skills=SimpleNamespace(coding_mode=coding_mode)),
            system_prompt="BASE",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_on_injects_directive_and_pins(self):
        ctx = await enforce_coding_mode(self._ctx(True))
        base, suffix = ctx.system_prompt
        assert base == "BASE"
        assert "CODING MODE" in suffix
        assert "opensquilla code-task solve" in suffix
        assert "DISABLED while coding mode is on" in suffix
        assert "code-task" in ctx.metadata["pinned_skills"]
        assert ctx.metadata["coding_mode"] is True

    @pytest.mark.asyncio
    async def test_directive_clarify_gate_asks_when_only_a_category(self):
        """Build-from-scratch clarify gate: a bare app category with no concrete
        features/scope/user gets 1-2 questions; a request that names concrete
        features/scope builds directly. Asserted as normalized concept groups so
        harmless rewording survives."""
        ctx = await enforce_coding_mode(self._ctx(True))
        _, suffix = ctx.system_prompt
        low = suffix.lower()
        # Trigger is "only a category / no concrete features".
        assert "only a" in low and "category" in low
        assert "concrete features" in low
        # Build (don't ask) once concrete features/scope/users are named.
        assert "do not ask" in low and "build it" in low
        # Bounded (<=2) and ask-then-stop (Lovable's "wait before calling tools").
        assert "1-2" in low and "at most 2" in low
        assert "stop this turn" in low
        assert "do not call code-task until" in low
        # Defaultable details are never asked about.
        assert "platform" in low and "styling" in low

    @pytest.mark.asyncio
    async def test_directive_warns_against_killing_running_code_task(self):
        """Isolation rule: the source repo stays empty until verified, so don't
        judge progress by it and don't kill/retry a running code-task."""
        ctx = await enforce_coding_mode(self._ctx(True))
        _, suffix = ctx.system_prompt
        low = suffix.lower()
        assert "isolated run directory" in low
        assert "stays empty until" in low  # source empty until verified
        assert "do not judge progress by the source" in low
        assert "do not kill" in low
        assert "status.json" in low

    @pytest.mark.asyncio
    async def test_directive_mandates_background_not_blocking_exec(self):
        ctx = await enforce_coding_mode(self._ctx(True))
        _, suffix = ctx.system_prompt
        low = suffix.lower()
        assert "always launch it with background_process" in low
        assert "do not run code-task with a" in low and "blocking exec_command" in low
        assert "600s" in suffix

    @pytest.mark.asyncio
    async def test_directive_mandates_task_file_staging(self):
        """Field report: a multi-line task passed inline as `--task "<text>"`
        gets truncated at the first \\n by cmd.exe on Windows, silently
        eating --yes and hanging code-task for 90 minutes at typer.confirm.
        The directive must teach the agent to stage task text via stdin
        into a temp file, then pass --task-file <path>."""
        ctx = await enforce_coding_mode(self._ctx(True))
        _, suffix = ctx.system_prompt

        # The command-line examples use --task-file, NOT inline --task.
        assert "--task-file <path>" in suffix
        # The scratch-mode template no longer emits the inline --task form.
        scratch_block = suffix.split("scratch --yes", 1)[0]
        assert '--task "<text>" --verification-mode' not in scratch_block

        # The "why + how" section is present and unambiguous.
        assert "TASK-FILE STAGING" in suffix
        # No exception language — inline --task is FORBIDDEN regardless of
        # length/complexity. This guards against re-introducing the "single-
        # line ASCII is fine" escape hatch a model could rationalize into.
        assert "FORBIDDEN" in suffix
        assert "is an optimization" not in suffix
        assert "newline" in suffix.lower()
        assert "cmd.exe" in suffix.lower()

        # The two-step recipe references both tools by name and the
        # exec_command(stdin=...) escape hatch that bypasses cmd.exe.
        assert "exec_command" in suffix
        assert "stdin=" in suffix
        assert "background_process" in suffix
        assert "sys.stdin.buffer.read()" in suffix
        # Atomic-and-secure file creation (mkstemp), not a guessed path.
        assert "tempfile.mkstemp" in suffix
        # os.fdopen+write handles partial writes from large stdin; raw
        # os.write can short-write at multi-100KB payloads on some OS.
        assert "os.fdopen" in suffix
        # Cross-platform shell-quoting: " on Windows, shlex.quote on POSIX.
        # Defends against $/`/backslash on POSIX and against the path
        # itself containing characters that need shell escaping.
        assert "shlex.quote" in suffix
        # Both real-repo (case 1) and scratch (case 2) recipes are shown,
        # otherwise weaker models copy the scratch command for repo edits.
        assert "Case 1, real repo" in suffix
        assert "Case 2, scratch" in suffix
        # Explicit framing of exec_command's exit_code=0 prefix so the
        # agent doesn't try to parse the wrong stdout line.
        assert "exit_code=0" in suffix
        # Cleanup instructions: temp prose can contain private issue text;
        # the directive must tell the agent to drop the file after wait.
        cleanup_block = suffix.lower()
        assert "cleanup" in cleanup_block
        assert "del " in suffix and "rm " in suffix  # Windows + POSIX

    @pytest.mark.asyncio
    async def test_directive_uses_resolved_python_not_bare_name(
        self, monkeypatch
    ):
        """The staging recipe must invoke the SAME interpreter the gateway
        is running on — not a bare ``python`` that could resolve to a
        different (or broken) interpreter via PATH. Mirrors how
        __CODE_TASK_CMD__ is already a fully-qualified path."""
        from opensquilla.engine.steps import coding_mode as _cm
        monkeypatch.setattr(
            _cm, "sys", SimpleNamespace(executable="/fake/venv/bin/python")
        )

        ctx = await enforce_coding_mode(self._ctx(True))
        _, suffix = ctx.system_prompt
        assert "/fake/venv/bin/python -c" in suffix
        # No bare `python -c` invocation anywhere — always the resolved path.
        # (Allow the literal word "python" in prose; check it never appears
        # as a standalone command token.)
        assert " python -c" not in suffix and "\npython -c" not in suffix

    @pytest.mark.asyncio
    async def test_off_injects_nothing(self):
        ctx = await enforce_coding_mode(self._ctx(False))
        # system_prompt unchanged (still a plain str), no pin.
        assert ctx.system_prompt == "BASE"
        assert "pinned_skills" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_directive_appends_to_existing_suffix(self):
        ctx = self._ctx(True)
        ctx.system_prompt = ("BASE", "PRIOR")
        out = await enforce_coding_mode(ctx)
        base, suffix = out.system_prompt
        assert base == "BASE"
        assert suffix.startswith("PRIOR")
        assert "CODING MODE" in suffix


class TestWriteToolDeny:
    """coding ON denies the in-session write tools (forces code-task)."""

    def test_on_denies_write_tools(self):
        denied = coding_mode_denied_tools(True)
        for t in ("write_file", "edit_file", "apply_patch", "execute_code", "git_commit"):
            assert t in denied
        assert denied == CODING_MODE_DENIED_TOOLS

    def test_off_denies_nothing(self):
        assert coding_mode_denied_tools(False) == frozenset()

    def test_shell_and_read_tools_kept(self):
        # shell stays so the agent can still LAUNCH code-task; reads stay.
        denied = coding_mode_denied_tools(True)
        for t in ("exec_command", "background_process", "process",
                  "read_file", "list_dir", "grep_search", "git_diff"):
            assert t not in denied


class TestWriteToolDenyEnforcement:
    """Integration: the deny set actually drops write tools from the live
    tool surface built from the default registry (pins the enforcement seam,
    not just the pure helper)."""

    def _surface(self, denied):
        import opensquilla.tools.builtin  # noqa: F401  (registers builtins)
        from opensquilla.tools.registry import get_default_registry
        from opensquilla.tools.types import CallerKind, ToolContext

        registry = get_default_registry()
        ctx = ToolContext(
            is_owner=True,
            caller_kind=CallerKind.AGENT,
            denied_tools=set(denied),
        )
        return {t.name for t in registry.to_tool_definitions(ctx)}

    def test_on_drops_write_tools_from_surface(self):
        names = self._surface(coding_mode_denied_tools(True))
        assert {
            "write_file",
            "edit_file",
            "apply_patch",
            "execute_code",
            "git_commit",
        }.isdisjoint(names)

    def test_on_keeps_codetask_launch_and_read_tools(self):
        # shell stays so the agent can still LAUNCH `opensquilla code-task solve`;
        # read-only tools stay so it can understand the repo.
        names = self._surface(coding_mode_denied_tools(True))
        for keep in ("exec_command", "background_process", "process",
                     "read_file", "list_dir", "grep_search"):
            assert keep in names, keep

    def test_off_is_noop_keeps_write_tools(self):
        names = self._surface(coding_mode_denied_tools(False))
        assert "write_file" in names
        assert "edit_file" in names


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
class TestCodeTaskResolution:
    """resolve_code_task_command picks a PATH-independent, runnable invocation."""

    def test_prefers_adjacent_cli(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        cli = tmp_path / "opensquilla"
        cli.write_text("")
        cli.chmod(0o755)
        monkeypatch.setattr(cm.sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: argv[0] == str(cli))
        assert cm.resolve_code_task_command() == f"{shlex.quote(str(cli))} code-task"
        cm._reset_resolution_cache()

    def test_falls_back_to_module_invocation(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        py = str(tmp_path / "python")  # no adjacent opensquilla file exists
        monkeypatch.setattr(cm.sys, "executable", py)
        monkeypatch.setattr(cm.shutil, "which", lambda name: None)
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: argv[:2] == [py, "-P"])
        assert (
            cm.resolve_code_task_command()
            == f"{shlex.quote(py)} -P -m opensquilla.cli.main code-task"
        )
        cm._reset_resolution_cache()

    def test_adjacent_exists_but_preflight_fails_falls_through(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        cli = tmp_path / "opensquilla"
        cli.write_text("")
        cli.chmod(0o755)
        py = str(tmp_path / "python")
        monkeypatch.setattr(cm.sys, "executable", py)
        monkeypatch.setattr(cm.shutil, "which", lambda name: None)
        # adjacent CLI exists but its --help fails; module invocation works
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: argv[:2] == [py, "-P"])
        assert (
            cm.resolve_code_task_command()
            == f"{shlex.quote(py)} -P -m opensquilla.cli.main code-task"
        )
        cm._reset_resolution_cache()

    def test_failure_is_not_cached_retries(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        monkeypatch.setattr(cm.sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(cm.shutil, "which", lambda name: None)
        calls = {"n": 0}
        def flaky(argv):
            calls["n"] += 1
            return calls["n"] > 1  # first probe fails, later succeed
        monkeypatch.setattr(cm, "_runs_code_task", flaky)
        assert cm.resolve_code_task_command() is None      # transient failure, NOT cached
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: True)
        assert cm.resolve_code_task_command() is not None  # retried, resolves
        cm._reset_resolution_cache()

    def test_falls_back_to_path_which(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        monkeypatch.setattr(cm.sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(cm.shutil, "which", lambda name: "/usr/bin/opensquilla")
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: argv[0] == "/usr/bin/opensquilla")
        assert cm.resolve_code_task_command() == "/usr/bin/opensquilla code-task"
        cm._reset_resolution_cache()

    def test_none_when_nothing_runs(self, monkeypatch, tmp_path):
        from opensquilla.engine.steps import coding_mode as cm
        cm._reset_resolution_cache()
        monkeypatch.setattr(cm.sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(cm.shutil, "which", lambda name: None)
        monkeypatch.setattr(cm, "_runs_code_task", lambda argv: False)
        assert cm.resolve_code_task_command() is None
        cm._reset_resolution_cache()

    def test_directive_uses_resolved_command_not_bare(self, monkeypatch):
        from opensquilla.engine.steps import coding_mode as cm
        monkeypatch.setattr(
            cm, "resolve_code_task_command",
            lambda: "/opt/env/bin/python -P -m opensquilla.cli.main code-task",
        )
        d = cm._build_coding_mode_directive()
        assert "/opt/env/bin/python -P -m opensquilla.cli.main code-task solve --repo" in d
        low = d.lower()
        assert "pip install" in low and "do not" in low
        assert "stop and report" in low

    def test_directive_fail_loud_when_unavailable(self, monkeypatch):
        from opensquilla.engine.steps import coding_mode as cm
        monkeypatch.setattr(cm, "resolve_code_task_command", lambda: None)
        d = cm._build_coding_mode_directive()
        assert "UNAVAILABLE" in d
        low = d.lower()
        assert "hand-edit" in low and "pip install" in low
        assert "stop and tell the user" in low
