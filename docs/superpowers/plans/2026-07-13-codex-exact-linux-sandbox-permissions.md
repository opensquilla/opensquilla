# Codex-Exact Linux Sandbox Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OpenSquilla's sensitive-path approximation with the default permission, escalation, continuation, and Guardian semantics of Codex `ea15456284` for sandboxed local Linux execution.

**Architecture:** A typed filesystem permission profile becomes the single source of truth for direct tools and bubblewrap. Existing one-shot elevation records are converted into exact suspended-action reviews, while a reusable read-only Guardian agent session performs Codex-policy risk and authorization review before the same tool request resumes. Experimental Codex features that are disabled by default remain unexposed.

**Tech Stack:** Python 3.12, asyncio, Pydantic settings, bubblewrap, pytest/pytest-asyncio, OpenSquilla provider and tool registries.

---

## File Structure

New focused modules:

- `src/opensquilla/sandbox/permissions.py`: canonical access entries, default workspace profile, path resolution, denied-read detection, and mount projection.
- `src/opensquilla/sandbox/approval_runtime.py`: exact action identity, approval routing, suspended-call continuation metadata, and retry decisions.
- `src/opensquilla/engine/guardian_prompt.py`: Codex policy text, bounded transcript projection, action truncation, and structured-output parsing.
- `src/opensquilla/engine/guardian_session.py`: reusable read-only Guardian agent trunk, parallel fork behavior, model/config alignment, and overall review deadline.

Existing modules retain their current responsibilities:

- `sandbox/types.py` and `sandbox/policy.py` carry the compiled profile on every backend request.
- `sandbox/backend/linux_permissions.py` and `linux_bwrap.py` project the profile into mounts and masks.
- `sandbox/path_validation.py` resolves direct-tool access from the same profile.
- `sandbox/elevation.py` remains a compatibility facade over the new approval runtime.
- `engine/guardian_review.py` owns retry classification, decisions, and circuit breaking.
- `engine/agent.py` owns the suspended exact tool call and reviewer lifecycle.
- built-in tools construct exact actions but do not independently classify sensitive paths.

### Task 1: Canonical Filesystem Permission Profile

**Files:**
- Create: `src/opensquilla/sandbox/permissions.py`
- Modify: `src/opensquilla/sandbox/types.py`
- Modify: `src/opensquilla/sandbox/policy.py`
- Test: `tests/test_sandbox/test_permission_profiles.py`

- [ ] **Step 1: Write failing default-profile resolution tests**

```python
def test_workspace_profile_reads_root_and_writes_declared_roots(tmp_path, monkeypatch):
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path / "repo",
        writable_roots=(tmp_path / "cache",),
    )
    assert profile.resolve(Path("/etc/hosts")) is FileSystemAccess.READ
    assert profile.resolve(tmp_path / "repo" / "src" / "a.py") is FileSystemAccess.WRITE
    assert profile.resolve(Path("/tmp") / "x") is FileSystemAccess.WRITE
    assert profile.resolve(tmpdir / "x") is FileSystemAccess.WRITE


@pytest.mark.parametrize("name", [".git", ".agents", ".codex"])
def test_workspace_profile_reprotects_metadata(tmp_path, name):
    profile = FileSystemPermissionProfile.workspace(workspace=tmp_path)
    assert profile.resolve(tmp_path / name / "config") is FileSystemAccess.READ


def test_explicit_denied_read_prevents_unsandboxed_execution(tmp_path):
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path,
        denied_read_roots=(tmp_path / "secret",),
    )
    assert profile.resolve(tmp_path / "secret" / "token") is FileSystemAccess.DENY
    assert profile.has_denied_reads
    assert not profile.unsandboxed_execution_allowed
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `uv run pytest tests/test_sandbox/test_permission_profiles.py -q`

Expected: collection fails because `opensquilla.sandbox.permissions` does not exist.

- [ ] **Step 3: Implement the permission types and precedence**

```python
class FileSystemAccess(StrEnum):
    DENY = "deny"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class FileSystemPermissionEntry:
    path: Path
    access: FileSystemAccess


@dataclass(frozen=True)
class FileSystemPermissionProfile:
    entries: tuple[FileSystemPermissionEntry, ...]
    denied_read_globs: tuple[str, ...] = ()

    @classmethod
    def workspace(cls, *, workspace: Path, writable_roots=(), denied_read_roots=()):
        entries = [FileSystemPermissionEntry(Path("/"), FileSystemAccess.READ)]
        entries.extend(FileSystemPermissionEntry(Path(p), FileSystemAccess.WRITE)
                       for p in (workspace, Path("/tmp"), *writable_roots))
        if raw_tmpdir := os.environ.get("TMPDIR"):
            entries.append(FileSystemPermissionEntry(Path(raw_tmpdir), FileSystemAccess.WRITE))
        for root in (workspace, *writable_roots):
            entries.extend(FileSystemPermissionEntry(Path(root) / name, FileSystemAccess.READ)
                           for name in (".git", ".agents", ".codex"))
        entries.extend(FileSystemPermissionEntry(Path(p), FileSystemAccess.DENY)
                       for p in denied_read_roots)
        return cls(tuple(entries))

    def resolve(self, path: Path) -> FileSystemAccess:
        candidate = path.expanduser().resolve(strict=False)
        matches = [(len(entry.path.parts), index, entry.access)
                   for index, entry in enumerate(self.entries)
                   if candidate.is_relative_to(entry.path.expanduser().resolve(strict=False))]
        return max(matches, default=(0, -1, FileSystemAccess.DENY))[-1]
```

Equal-specificity access uses declaration order so explicit later rules can override defaults. Deny globs are checked before path entries and count toward `has_denied_reads`.

- [ ] **Step 4: Compile the profile into `SandboxPolicy`**

Add `file_system: FileSystemPermissionProfile` to `SandboxPolicy`. In `build_policy`, construct the workspace profile from the workspace, session mounts, extra writable roots, `/tmp`, `$TMPDIR`, protected metadata, and explicit unreadable roots/globs. Derive legacy `mounts`, `workspace_rw`, and `tmp_writable` from this profile until all backends consume it directly.

- [ ] **Step 5: Run focused and existing policy tests**

Run: `uv run pytest tests/test_sandbox/test_permission_profiles.py tests/test_sandbox/test_policy_network.py tests/test_sandbox/test_run_modes.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/sandbox/permissions.py src/opensquilla/sandbox/types.py src/opensquilla/sandbox/policy.py tests/test_sandbox/test_permission_profiles.py
git commit -m "feat: add canonical sandbox permission profiles"
```

### Task 2: Linux Root-Read Enforcement Without Default Sensitive Masks

**Files:**
- Modify: `src/opensquilla/sandbox/backend/linux_permissions.py`
- Modify: `src/opensquilla/sandbox/backend/linux_bwrap.py`
- Modify: `src/opensquilla/sandbox/backend/linux_helper.py`
- Modify: `src/opensquilla/sandbox/backend/bubblewrap.py`
- Test: `tests/test_sandbox/test_linux_permissions.py`
- Test: `tests/test_sandbox/test_linux_bwrap.py`
- Test: `tests/test_sandbox/test_trusted_sandbox_execution.py`

- [ ] **Step 1: Write failing Linux projection tests**

```python
def test_default_linux_permissions_have_no_builtin_sensitive_denies(policy):
    permissions = compile_linux_permissions(policy)
    assert permissions.read_all is True
    assert permissions.denied_roots == ()


def test_explicit_denied_reads_are_preserved(policy, tmp_path):
    policy = replace(policy, file_system=replace(
        policy.file_system,
        entries=(*policy.file_system.entries,
                 FileSystemPermissionEntry(tmp_path / "secret", FileSystemAccess.DENY)),
    ))
    assert compile_linux_permissions(policy).denied_roots == (tmp_path / "secret",)


def test_bwrap_order_is_root_dev_write_protect_deny(policy):
    permissions = compile_linux_permissions(policy)
    argv = build_bwrap_argv(
        command=["/bin/true"],
        command_cwd=policy.workspace,
        permissions=permissions,
        options=BwrapOptions(bwrap_path="bwrap", mount_proc=True),
    )
    root_index = argv.index("--ro-bind")
    write_index = argv.index("--bind")
    protected_index = argv.index("--ro-bind", root_index + 1)
    assert argv[root_index : root_index + 3] == ["--ro-bind", "/", "/"]
    assert argv.index("--dev") < write_index < protected_index
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_sandbox/test_linux_permissions.py tests/test_sandbox/test_linux_bwrap.py -q`

Expected: failures show the current `linux_runtime_sensitive_deny_roots()` masks.

- [ ] **Step 3: Project only profile-defined denies**

Remove `linux_runtime_sensitive_deny_roots()` from `compile_linux_permissions`. Populate read/write/deny roots from `policy.file_system`, preserving identity mappings and protected `.git/.agents/.codex` subpaths. Keep deny-glob expansion, missing protected-create targets, canonical symlink targets, minimal `/dev`, fresh `/proc`, user/PID namespaces, and existing seccomp/network behavior.

- [ ] **Step 4: Correct `/tmp` semantics**

Use a writable bind for the profile's actual `/tmp` and `$TMPDIR` roots, matching Codex workspace-write semantics. Do not replace host `/tmp` with a private tmpfs when the active profile explicitly grants `/tmp = write`; keep private tmpfs only for profiles that intentionally request it.

- [ ] **Step 5: Run real bubblewrap acceptance tests**

Run: `uv run pytest tests/test_sandbox/test_linux_bwrap.py tests/test_sandbox/test_trusted_sandbox_execution.py -q`

Expected: `/` lists, `/etc/hosts` reads, external writes fail, workspace writes pass, and explicit denied reads remain masked.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/sandbox/backend tests/test_sandbox/test_linux_permissions.py tests/test_sandbox/test_linux_bwrap.py tests/test_sandbox/test_trusted_sandbox_execution.py
git commit -m "fix: align Linux mounts with Codex workspace policy"
```

### Task 3: Shared Direct-Tool Path Decisions

**Files:**
- Modify: `src/opensquilla/sandbox/path_validation.py`
- Modify: `src/opensquilla/sandbox/run_context.py`
- Modify: `src/opensquilla/sandbox/integration.py`
- Modify: `src/opensquilla/tools/builtin/filesystem.py`
- Modify: `src/opensquilla/tools/builtin/media.py`
- Test: `tests/test_sandbox/test_path_access.py`
- Test: `tests/test_tools/test_filesystem_read_workspace.py`
- Test: `tests/test_tools/test_media_image.py`

- [ ] **Step 1: Replace sensitive-path expectations with permission expectations**

```python
@pytest.mark.parametrize("path", ["/", "/home", "~/.ssh", "~/.aws", "/etc"])
def test_default_profile_allows_readable_host_paths(path, workspace):
    decision = decide_path_access(path, workspace=workspace, write=False)
    assert decision.status == "allowed"


def test_external_write_requests_elevation(workspace, tmp_path):
    decision = decide_path_access(tmp_path / "outside.txt", workspace=workspace, write=True)
    assert decision.status == "request"
    assert decision.reason == "outside_writable_roots"


def test_protected_project_metadata_write_requests_elevation(workspace):
    decision = decide_path_access(workspace / ".git" / "config", workspace=workspace, write=True)
    assert decision.status == "request"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_sandbox/test_path_access.py tests/test_tools/test_filesystem_read_workspace.py -q`

Expected: existing `sensitive_path` and root special-case assertions fail.

- [ ] **Step 3: Make `decide_path_access` resolve the active profile**

Delete `_POSIX_BLOCKED_PREFIXES`, credential metadata classification, and the root-only exception from sandbox-on authorization. Accept an optional compiled profile; when absent, construct the active default profile from workspace and mounts. Reads return allowed unless the profile resolves deny. Writes return allowed only for write, otherwise request with `outside_writable_roots` or `protected_metadata`.

- [ ] **Step 4: Remove read hard-blocks from built-ins**

Remove `_sensitive_access_block` calls from `read_file`, `list_dir`, `glob_search`, `grep_search`, and media inspection. Preserve workspace-strict product rules only when explicitly configured; they are separate from the default sandbox policy. Route backend and direct-host read paths through the same profile decision.

- [ ] **Step 5: Remove sensitive validation from sandbox session mounts**

`run_context.py` and `integration.py` must validate canonical paths, access mode, and denied-read profile entries, but must not reject `/`, `.ssh`, `.aws`, system directories, or dotfiles by name. A root read mount is valid; root write remains a distinct explicit full-write policy.

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/test_sandbox/test_path_access.py tests/test_sandbox/test_run_context_grants.py tests/test_sandbox/test_rpc_sandbox_access.py tests/test_tools/test_filesystem_read_workspace.py tests/test_tools/test_media_image.py -q`

Expected: all pass with permission-profile assertions replacing sensitive-path assertions.

- [ ] **Step 7: Commit**

```bash
git add src/opensquilla/sandbox/path_validation.py src/opensquilla/sandbox/run_context.py src/opensquilla/sandbox/integration.py src/opensquilla/tools/builtin/filesystem.py src/opensquilla/tools/builtin/media.py tests/test_sandbox tests/test_tools
git commit -m "fix: allow profile-governed host filesystem reads"
```

### Task 4: Exact Approval Actions and Suspended Continuation

**Files:**
- Create: `src/opensquilla/sandbox/approval_runtime.py`
- Modify: `src/opensquilla/sandbox/elevation.py`
- Modify: `src/opensquilla/sandbox/operation_runtime.py`
- Modify: `src/opensquilla/engine/agent.py`
- Test: `tests/test_sandbox/test_approval_runtime.py`
- Test: `tests/test_engine/test_interactive_approval_retry.py`

- [ ] **Step 1: Write failing exact-action tests**

```python
def test_patch_action_keeps_full_patch_for_review(tmp_path):
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** End Patch"
    action = ApprovalAction.apply_patch(
        call_id="call-1", cwd=tmp_path, files=(tmp_path / "a.py",), patch=patch
    )
    assert action.guardian_payload()["patch"] == patch


@pytest.mark.asyncio
async def test_approved_action_resumes_same_suspended_request(runtime):
    request = SuspendedToolRequest("call-1", "write_file", {"path": "/tmp/x", "content": "x"})
    outcome = await runtime.review_and_resume(request)
    assert outcome.executed_request is request
    assert outcome.execution_count == 1


def test_escalation_is_forbidden_with_denied_reads(profile):
    assert select_sandbox_override("require_escalated", profile) is SandboxOverride.NO_OVERRIDE
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_sandbox/test_approval_runtime.py tests/test_engine/test_interactive_approval_retry.py -q`

Expected: missing approval runtime types and full-payload assertions fail.

- [ ] **Step 3: Implement typed actions and suspended requests**

```python
@dataclass(frozen=True)
class ApprovalAction:
    kind: Literal["shell", "exec_command", "apply_patch", "filesystem", "code", "media", "network"]
    call_id: str
    cwd: str
    payload: Mapping[str, object]
    sandbox_permissions: Literal["use_default", "require_escalated"] = "use_default"
    justification: str | None = None


@dataclass
class SuspendedToolRequest:
    call_id: str
    tool_name: str
    arguments: dict[str, object]
    action: ApprovalAction
    state: Literal["suspended", "approved", "executing", "completed", "denied"] = "suspended"
```

Actions contain exact argv, cwd, TTY, files, full patch/code/mutation payload, network destination, and permission intent. Fingerprints remain audit/cache integrity fields, not the continuation object.

- [ ] **Step 4: Route old elevation facade through the new runtime**

Keep `ElevationAction` deserialization for old queued records, but new calls create `ApprovalAction`. `gate_elevated_action` delegates to the coordinator and rejects unsandboxed execution when the active profile has denied reads.

- [ ] **Step 5: Suspend before emitting a tool result**

In `Agent`, when a tool call returns an internal automatic review request, hold the original `ToolCall` and arguments in a `SuspendedToolRequest`. Do not append the pending envelope to provider history. Guardian reviews it, and approval invokes the same handler once with internal continuation metadata; denial produces the single terminal tool result. UI lifecycle events remain available separately.

- [ ] **Step 6: Add attributable sandbox-denial retry**

Only structured filesystem or managed-network sandbox denials can request a broader second attempt. Preserve original output and retry reason, require a fresh Guardian decision when the broader context differs, and never escalate generic non-zero exits.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_sandbox/test_approval_runtime.py tests/test_sandbox/test_elevation.py tests/test_engine/test_interactive_approval_retry.py -q`

Expected: all pass; side-effect counters prove exactly-once continuation.

```bash
git add src/opensquilla/sandbox/approval_runtime.py src/opensquilla/sandbox/elevation.py src/opensquilla/sandbox/operation_runtime.py src/opensquilla/engine/agent.py tests/test_sandbox/test_approval_runtime.py tests/test_sandbox/test_elevation.py tests/test_engine/test_interactive_approval_retry.py
git commit -m "feat: resume exact approved sandbox actions"
```

### Task 5: Codex Guardian Policy and Bounded Prompt

**Files:**
- Create: `src/opensquilla/engine/guardian_prompt.py`
- Modify: `src/opensquilla/engine/guardian_review.py`
- Test: `tests/test_engine/test_guardian_prompt.py`
- Test: `tests/test_engine/test_guardian_review.py`

- [ ] **Step 1: Write failing policy and projection tests**

```python
def test_low_and_medium_do_not_require_authorization():
    assert enforce_thresholds(assessment("low", "unknown", "allow")).outcome == "allow"
    assert enforce_thresholds(assessment("medium", "unknown", "allow")).outcome == "allow"


def test_post_denial_exact_user_reapproval_has_highest_default_precedence():
    prompt = build_guardian_prompt(transcript=[denial, informed_user_reapproval], action=action)
    assert "previously `Rejected`" in prompt.developer_context


def test_projection_limits_and_marks_omissions():
    projected = project_transcript(oversized_messages)
    assert projected.message_tokens <= 10_000
    assert projected.tool_tokens <= 10_000
    assert len(projected.entries) <= 40
    assert "<guardian_truncated" in projected.rendered
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_engine/test_guardian_prompt.py tests/test_engine/test_guardian_review.py -q`

Expected: current policy incorrectly requires authorization for medium risk and lacks bounded action/transcript structures.

- [ ] **Step 3: Port the source policy exactly**

Move the fixed policy to `guardian_prompt.py`. Include untrusted-evidence handling, authorization and risk taxonomies, read-only investigation guidance, exact default thresholds, prompt-injection exception, state-dependent delete guidance, and informed post-denial reapproval precedence. Tenant policy text is appended as policy data, not instructions from the action.

- [ ] **Step 4: Implement bounded transcript and action rendering**

Use the source limits: 10,000 message tokens, 10,000 tool tokens, 2,000 per message, 1,000 per tool entry, 40 recent entries, and 16,000 tokens per action string. Use the repository token estimator and explicit `<guardian_truncated ... />` markers. Retain developer/user/assistant/tool roles and label all artifacts as evidence.

- [ ] **Step 5: Tighten parsing and failure synthesis**

Parse exactly one schema-valid object. A final prompt/session/parse error synthesizes high risk, unknown authorization, deny, and `failed_closed`; timeout and abort remain distinct statuses.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/test_engine/test_guardian_prompt.py tests/test_engine/test_guardian_review.py -q`

Expected: all pass.

```bash
git add src/opensquilla/engine/guardian_prompt.py src/opensquilla/engine/guardian_review.py tests/test_engine/test_guardian_prompt.py tests/test_engine/test_guardian_review.py
git commit -m "feat: port Codex Guardian policy and prompt"
```

### Task 6: Reusable Read-Only Guardian Agent Session

**Files:**
- Create: `src/opensquilla/engine/guardian_session.py`
- Modify: `src/opensquilla/engine/agent.py`
- Modify: `src/opensquilla/engine/types.py`
- Modify: `src/opensquilla/tools/types.py`
- Test: `tests/test_engine/test_guardian_session.py`

- [ ] **Step 1: Write failing reviewer-session tests**

```python
@pytest.mark.asyncio
async def test_guardian_has_only_read_tools(manager):
    session = manager.build_session(parent_config)
    assert set(session.tool_names) == {"read_file", "list_dir", "glob_search", "grep_search", "git_status", "git_diff", "git_log"}
    assert session.tool_context.run_mode == "standard"
    assert session.tool_context.on_sandbox_auto_review is None


@pytest.mark.asyncio
async def test_second_review_uses_transcript_delta(manager):
    await manager.review(action1, transcript1)
    review = await manager.review(action2, transcript2)
    assert review.prompt_mode == "delta"


@pytest.mark.asyncio
async def test_busy_trunk_uses_ephemeral_fork(manager):
    results = await asyncio.gather(manager.review(action1, transcript), manager.review(action2, transcript))
    assert {result.session_mode for result in results} == {"trunk", "fork"}
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_engine/test_guardian_session.py -q`

Expected: module and session manager do not exist.

- [ ] **Step 3: Add safe Agent history snapshot support**

Add `Agent.history_snapshot() -> list[Message]` that returns a copy. Do not expose mutable history. This lets a committed Guardian trunk seed an ephemeral fork.

- [ ] **Step 4: Build the reviewer Agent**

```python
READ_ONLY_GUARDIAN_TOOLS = frozenset({
    "read_file", "list_dir", "glob_search", "grep_search",
    "git_status", "git_diff", "git_log",
})

config = replace(parent_config,
    max_iterations=4,
    timeout=90.0,
    request_timeout=min(parent_config.request_timeout, 90.0),
    thinking=ThinkingLevel.LOW if supported else False,
    system_prompt=guardian_policy_prompt(tenant_policy),
    skills_context_prompt=None,
    request_context_prompt=None,
    flush_enabled=False,
)
context = ToolContext(
    is_owner=True,
    workspace_dir=parent_config.workspace_dir,
    run_mode="standard",
    allowed_tools=set(READ_ONLY_GUARDIAN_TOOLS),
    denied_tools=set(),
    on_sandbox_auto_review=None,
)
```

Build definitions and handler from the existing registry under this context. Do not attach memory, skills, plugins, MCP, subagents, hooks, apps, or mutation tools. The normal managed network runtime remains inherited so read-only checks cannot bypass its allowlist.

- [ ] **Step 5: Implement trunk, cursor, and forks**

Keep one reusable reviewer Agent and transcript cursor per parent Agent/session configuration. Use the trunk lock without waiting: the lock winner runs and commits the cursor/history; a concurrent review gets an ephemeral Agent seeded from the last committed history and never advances the trunk cursor. Rebuild the trunk when provider/model/workspace/managed-network configuration changes.

- [ ] **Step 6: Enforce one 90-second deadline**

The overall deadline includes all provider attempts and read-only tool calls. Return structured terminal output to `GuardianReviewer`; do not let reviewer Agent errors escape as untyped exceptions.

- [ ] **Step 7: Run tests and commit**

Run: `uv run pytest tests/test_engine/test_guardian_session.py tests/test_engine/test_guardian_review.py -q`

Expected: all pass.

```bash
git add src/opensquilla/engine/guardian_session.py src/opensquilla/engine/agent.py src/opensquilla/engine/types.py src/opensquilla/tools/types.py tests/test_engine/test_guardian_session.py tests/test_engine/test_guardian_review.py
git commit -m "feat: run Guardian in a reusable read-only session"
```

### Task 7: Guardian Retry, Circuit Breaker, Audit, and Routing

**Files:**
- Modify: `src/opensquilla/engine/guardian_review.py`
- Modify: `src/opensquilla/engine/agent.py`
- Modify: `src/opensquilla/sandbox/config.py`
- Modify: `src/opensquilla/sandbox/network_runtime.py`
- Test: `tests/test_engine/test_guardian_review.py`
- Test: `tests/test_engine/test_interactive_approval_retry.py`
- Test: `tests/test_sandbox/test_network_runtime.py`
- Test: `tests/test_gateway/test_approval_event_push.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_circuit_breaker_trips_at_three_consecutive_denials():
    breaker = GuardianCircuitBreaker()
    assert [breaker.record("deny") for _ in range(3)] == [False, False, True]


def test_circuit_breaker_trips_at_ten_denials_in_last_fifty():
    breaker = GuardianCircuitBreaker()
    outcomes = ["deny", "allow"] * 9 + ["deny"]
    assert [breaker.record(outcome) for outcome in outcomes][-1] is True


def test_non_denial_resets_only_consecutive_counter():
    breaker = GuardianCircuitBreaker()
    breaker.record("deny")
    breaker.record("allow")
    assert breaker.consecutive_denials == 0
    assert list(breaker.recent_denials) == [True, False]

@pytest.mark.asyncio
async def test_only_transient_and_parse_failures_retry():
    reviewer = GuardianReviewer(session=scripted(overloaded, malformed, allow))
    assert (await reviewer.review(action, transcript)).outcome == "allow"
    assert reviewer.attempts == 3

@pytest.mark.asyncio
async def test_timeout_is_distinct_and_does_not_open_human_card(reviewer, events):
    assessment = await reviewer.review_with_session(
        session=NeverCompletesGuardianSession(),
        action=action,
        transcript=transcript,
        timeout_s=0.01,
    )
    assert assessment.status == "timed_out"
    assert assessment.outcome == "deny"
    assert all(event.human_actionable is False for event in events)
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_engine/test_guardian_review.py tests/test_engine/test_interactive_approval_retry.py tests/test_gateway/test_approval_event_push.py -q`

Expected: 3-only circuit breaker, 20-second default, and broad exception retries fail assertions.

- [ ] **Step 3: Port timeout and retry classification**

Set the default review timeout to 90 seconds and max attempts to 3. Retry only parse errors, overload, HTTP/stream connection failure, internal server error, and stream disconnection. Do not retry timeout, cancellation, prompt-build failure, or non-transient session failure.

- [ ] **Step 4: Implement 3-consecutive / 10-of-50 breaker**

```python
@dataclass
class GuardianCircuitBreaker:
    consecutive_denials: int = 0
    recent_denials: deque[bool] = field(default_factory=lambda: deque(maxlen=50))
    interrupt_triggered: bool = False
```

Count valid policy denials using Codex's classification; reset consecutive on non-denial; interrupt once when either threshold is reached; clear on turn end.

- [ ] **Step 5: Align network reviews and audit events**

Network Guardian actions include normalized host, protocol, port, target, and triggering action. Ambiguous attribution fails closed. Emit in-progress/approved/denied/timed-out/aborted events with review ID, action summary, model, risk, authorization, rationale, attempt, and latency. Automatic reviews stay `humanActionable=False`.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest tests/test_engine/test_guardian_review.py tests/test_engine/test_interactive_approval_retry.py tests/test_sandbox/test_network_runtime.py tests/test_gateway/test_approval_event_push.py -q`

Expected: all pass.

```bash
git add src/opensquilla/engine/guardian_review.py src/opensquilla/engine/agent.py src/opensquilla/sandbox/config.py src/opensquilla/sandbox/network_runtime.py tests/test_engine tests/test_sandbox/test_network_runtime.py tests/test_gateway/test_approval_event_push.py
git commit -m "fix: align Guardian lifecycle with Codex"
```

### Task 8: Migrate All Included Tool Surfaces

**Files:**
- Modify: `src/opensquilla/tools/builtin/shell.py`
- Modify: `src/opensquilla/tools/builtin/filesystem.py`
- Modify: `src/opensquilla/tools/builtin/patch.py`
- Modify: `src/opensquilla/tools/builtin/code_exec.py`
- Modify: `src/opensquilla/tools/builtin/media.py`
- Modify: `src/opensquilla/sandbox/escalation.py`
- Delete or compatibility-only: `src/opensquilla/sandbox/sensitive_paths.py`
- Test: `tests/test_tools/test_shell_approval_policy.py`
- Test: `tests/test_tools/test_apply_patch_gates.py`
- Test: `tests/test_tools/test_code_exec_python_resolution.py`
- Test: `tests/test_sandbox/test_shell_code_network_hints.py`

- [ ] **Step 1: Write cross-tool contract tests**

```python
@pytest.mark.parametrize("tool_name", ["exec_command", "write_file", "edit_file", "apply_patch", "execute_code"])
def test_tool_schema_exposes_only_default_codex_permission_modes(tool_name, registry):
    schema = schema_for(registry, tool_name)
    assert schema["sandbox_permissions"]["enum"] == ["use_default", "require_escalated"]


@pytest.mark.parametrize("tool_name", INCLUDED_LOCAL_TOOLS)
def test_tool_uses_shared_permission_and_approval_runtime(tool_name, registry):
    assert registry.get(tool_name).spec.sandbox.enforce is True
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_tools/test_shell_approval_policy.py tests/test_tools/test_apply_patch_gates.py tests/test_tools/test_code_exec_python_resolution.py tests/test_sandbox/test_shell_code_network_hints.py -q`

Expected: sensitive-path hard blocks and per-tool approval divergences fail the new contract.

- [ ] **Step 3: Remove tool-specific sensitive gates**

Delete sensitive-path scanning from shell command/stdin, filesystem mutations, patch paths, code source/path scanning, media paths, and network hints. Keep deterministic parsing only for exact action description, protected metadata detection, obvious command safety policy, and attributable sandbox denial.

- [ ] **Step 4: Send exact payloads to Guardian**

- shell: exact command/argv, cwd, stdin presence and bounded content, env key names, TTY, justification;
- filesystem: operation, canonical source/targets, and exact write/edit content;
- patch: affected files and full patch;
- code: interpreter, argv, cwd, full source/input, network posture;
- media: operation, input/output paths and destination;
- network: target/host/protocol/port plus trigger.

The executor retains untruncated originals; persistent audit logs store summaries/digests rather than raw secrets.

- [ ] **Step 5: Execute approved direct mutations exactly once**

Workspace writes remain sandboxed. Approved external direct mutations run their already-canonicalized operation on the host; they do not gain a general shell. Approved shell/code requests run the exact top-level invocation outside bubblewrap. Denied reads prevent unsandboxed execution globally.

- [ ] **Step 6: Remove competing legacy authority**

Keep `sensitive_paths.py` only if old persisted records or non-sandbox compatibility require its formatting helpers. No sandbox-on code may import it for authorization. Replace every old `reason == "sensitive_path"` test with permission-profile behavior; retain equivalent security coverage for explicit denied reads.

- [ ] **Step 7: Run all affected tool suites and commit**

Run: `uv run pytest tests/test_tools tests/test_sandbox/test_shell_code_network_hints.py tests/test_engine/test_interactive_approval_retry.py -q`

Expected: all pass.

```bash
git add src/opensquilla/tools src/opensquilla/sandbox tests/test_tools tests/test_sandbox/test_shell_code_network_hints.py tests/test_engine/test_interactive_approval_retry.py
git commit -m "refactor: unify sandbox permission handling across tools"
```

### Task 9: Documentation, Real Acceptance, and Full Verification

**Files:**
- Modify: `docs/tools-and-sandbox.md`
- Modify: `docs/approvals-and-permissions.md`
- Modify: `docs/configuration.md`
- Modify: `docs/troubleshooting.md`

- [ ] **Step 1: Update user-facing documentation**

Document root-read/workspace-write semantics, protected metadata, OS-level read permissions, explicit denied reads, the two default permission modes, exact suspended continuation, Guardian read-only investigation, 90-second deadline, retry classes, circuit thresholds, and the disabled-by-default experimental Codex features.

- [ ] **Step 2: Run documentation and static checks**

Run: `uv run pytest tests/test_release_consistency.py -q`

Expected: all pass.

- [ ] **Step 3: Run targeted real bubblewrap scenarios**

Run:

```bash
uv run pytest \
  tests/test_sandbox/test_linux_bwrap.py \
  tests/test_sandbox/test_trusted_sandbox_execution.py \
  tests/test_sandbox/test_permission_profiles.py \
  tests/test_engine/test_guardian_session.py \
  tests/test_engine/test_interactive_approval_retry.py -q
```

Expected: all pass; no skips except host capability checks explicitly reported by the tests.

- [ ] **Step 4: Reproduce the original gateway behavior**

Start a temporary gateway with isolated state, open a session whose pwd is the OpenSquilla checkout, and verify:

```text
list_dir("/") -> allowed
read_file("/etc/hosts") -> allowed
read_file(user-owned file outside workspace) -> allowed
write_file(outside workspace, use_default) -> elevation_required
same exact write with require_escalated -> Guardian decision -> same call completes once
explicit denied-read profile -> read denied and require_escalated cannot bypass
```

- [ ] **Step 5: Run the full repository suite**

Run: `uv run pytest -q`

Expected: zero failures.

- [ ] **Step 6: Inspect the final diff and sensitive-path imports**

Run:

```bash
git diff --check
rg -n "sensitive_path" src/opensquilla/sandbox src/opensquilla/tools src/opensquilla/engine
git status --short
```

Expected: no whitespace errors; remaining `sensitive_path` references are documented compatibility/non-sandbox code and none authorize sandbox-on access; status contains only intended files.

- [ ] **Step 7: Commit documentation**

```bash
git add docs/tools-and-sandbox.md docs/approvals-and-permissions.md docs/configuration.md docs/troubleshooting.md
git commit -m "docs: describe Codex-exact sandbox permissions"
```

## Final Requirement Review

Before claiming completion, map every section of
`docs/superpowers/specs/2026-07-13-codex-exact-linux-sandbox-permissions-design.md`
to a passing test or a documented excluded feature. Re-run the original root-read
symptom and the exact external-write auto-review scenario after the full suite,
then follow `superpowers:verification-before-completion` and
`superpowers:finishing-a-development-branch`.
