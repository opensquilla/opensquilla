"""Dream — per-agent cron-scheduled memory consolidation.

Two phases:
  Phase 1 — plain LLM call that analyses new ``memory/*.md`` files plus the
            current ``MEMORY.md`` and produces a text rationale.
  Phase 2 — LLM sub-agent with ``read_file`` / ``edit_file`` tools makes
            surgical edits to ``MEMORY.md`` based on Phase 1's rationale.

On success: processed ``memory/*.md`` files are deleted and the cursor
advances. On failure: the cursor still advances on Phase-2 failure but
not on Phase-1 failure; processed files are retained either way and the
PR5 TTL/FIFO path sweeps them later.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from opensquilla.memory.dream_prompts import (
    phase1_prompt,
    phase1_prompt_from_contents,
    phase2_prompt,
)
from opensquilla.memory.protocols import MemoryProviderCapability
from opensquilla.provider.types import Message

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


async def _run_complete(
    provider: MemoryProviderCapability,
    messages: list[Message],
    max_tokens: int,
) -> str:
    """Completion through the explicit memory provider capability surface.

    Prefers ``provider.complete(messages=..., max_tokens=...)`` when
    present (unit tests + stubs). Falls back to streaming
    ``provider.chat(messages)`` and concatenating text deltas (real
    providers like OpenAIProvider).
    """
    complete = getattr(provider, "complete", None)
    if callable(complete):
        resp = await complete(messages=messages, max_tokens=max_tokens)
        return getattr(resp, "content", None) or getattr(resp, "text", "") or ""
    chat = getattr(provider, "chat", None)
    if not callable(chat):
        raise TypeError(
            f"Provider {type(provider).__name__} supports neither complete() nor chat()"
        )
    from opensquilla.provider.types import ChatConfig

    chunks: list[str] = []
    async for event in chat(messages, config=ChatConfig(max_tokens=max_tokens)):
        ev_name = type(event).__name__
        if ev_name == "ErrorEvent":
            # Surface provider errors (auth, rate-limit, HTTP) instead of
            # pretending we got an empty response — empty text downstream
            # turns into a misleading "Phase 2 did not contain JSON".
            msg = getattr(event, "message", "") or "provider error"
            raise RuntimeError(f"provider error: {msg}")
        text = getattr(event, "text", "") or ""
        if text and "Delta" in ev_name:
            chunks.append(text)
    return "".join(chunks)


@dataclass
class _Phase2Outcome:
    tool_calls: int
    changes: int
    applied_operations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _CandidateIdentity:
    path: str
    mtime_ns: int
    size: int
    sha256: str


class _DreamFileLock:
    """Small cross-process exclusive lock for Dream file mutations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any | None = None

    def __enter__(self) -> _DreamFileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+b")
        self._fh.seek(0, os.SEEK_END)
        if self._fh.tell() == 0:
            self._fh.write(b"\0")
            self._fh.flush()
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            getattr(msvcrt, "locking")(self._fh.fileno(), getattr(msvcrt, "LK_LOCK"), 1)
        else:
            fcntl = cast(Any, __import__("fcntl"))

            flock = getattr(fcntl, "flock")
            lock_ex = getattr(fcntl, "LOCK_EX")
            flock(self._fh.fileno(), lock_ex)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                getattr(msvcrt, "locking")(
                    self._fh.fileno(), getattr(msvcrt, "LK_UNLCK"), 1
                )
            else:
                fcntl = cast(Any, __import__("fcntl"))

                flock = getattr(fcntl, "flock")
                lock_un = getattr(fcntl, "LOCK_UN")
                flock(self._fh.fileno(), lock_un)
        finally:
            self._fh.close()
            self._fh = None


class DreamCursor:
    """Timestamp (UTC epoch seconds) of the last successful Dream batch.

    Persisted at ``<memory_dir>/.dream_cursor``. Files with mtime greater
    than the cursor are candidates for the next Dream run.
    """

    def __init__(self, memory_dir: Path) -> None:
        self._path = memory_dir / ".dream_cursor"

    def load(self) -> float:
        if not self._path.exists():
            return 0.0
        try:
            return float(self._path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return 0.0

    def save(self, ts: float) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(f"{ts}\n", encoding="utf-8")

    def reset(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


@dataclass
class DreamResult:
    """Outcome of a Dream run — emitted to logs and receipts."""

    files_considered: int = 0
    files_processed: int = 0
    files_deleted: int = 0
    phase1_status: str = "skipped"  # skipped | ok | error
    phase2_status: str = "skipped"  # skipped | ok | error
    phase1_ms: int = 0
    phase2_ms: int = 0
    phase2_tool_calls: int = 0
    error: str | None = None
    cursor_before: float = 0.0
    cursor_after: float = 0.0
    memory_md_sha_before: str | None = None
    memory_md_sha_after: str | None = None
    input_slimming: str = "off"
    phase1_prompt_chars: int = 0
    phase1_fallback_used: bool = False
    dry_run: bool = False
    edit_receipt_path: str | None = None


class Dream:
    """Per-agent Dream runner. Constructed once per cron invocation."""

    def __init__(
        self,
        *,
        workspace: Path,
        provider: Any,
        model: str,
        tool_registry: Any,
        session_lock: asyncio.Lock | None,
        config: Any,  # DreamConfig — avoid circular import
        agent_id: str = "main",
    ) -> None:
        self.workspace = workspace
        self.memory_dir = workspace / "memory"
        self.memory_md = workspace / "MEMORY.md"
        self.cursor = DreamCursor(self.memory_dir)
        self.provider = provider
        self.model = model
        self.tool_registry = tool_registry
        self.session_lock = session_lock
        self.config = config
        self.agent_id = agent_id

    def _emit_log(self, result: DreamResult) -> None:
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        log_dir = self.workspace / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"dream-{self.agent_id}-{today}.jsonl"
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "agent_id": getattr(self, "agent_id", "main"),
            "cursor_before": result.cursor_before,
            "cursor_after": result.cursor_after,
            "files_considered": result.files_considered,
            "files_processed": result.files_processed,
            "files_deleted": result.files_deleted,
            "phase1_ms": result.phase1_ms,
            "phase1_status": result.phase1_status,
            "phase2_ms": result.phase2_ms,
            "phase2_status": result.phase2_status,
            "phase2_tool_calls": result.phase2_tool_calls,
            "memory_md_sha_before": result.memory_md_sha_before,
            "memory_md_sha_after": result.memory_md_sha_after,
            "input_slimming": result.input_slimming,
            "phase1_prompt_chars": result.phase1_prompt_chars,
            "phase1_fallback_used": result.phase1_fallback_used,
            "dry_run": result.dry_run,
            "edit_receipt_path": result.edit_receipt_path,
            "error": result.error,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _candidate_files(self) -> list[Path]:
        """Top-level ``memory/*.md`` newer than cursor, oldest-first, capped.

        Tolerates ``FileNotFoundError`` on every ``stat()`` call so a
        concurrent ``MemorySyncManager._do_ttl_sweep`` (or any other
        unlinker) cannot crash the cron job mid-scan.
        """
        if not self.memory_dir.exists():
            return []
        cursor = self.cursor.load()
        # Pair (path, mtime) so we don't re-stat for sort and stay
        # tolerant of races between filter and sort.
        candidates: list[tuple[Path, float]] = []
        for p in self.memory_dir.iterdir():
            try:
                if not p.is_file():
                    continue
            except FileNotFoundError:
                continue
            if p.name.startswith("."):
                continue
            if p.name == "MEMORY.md":
                continue
            if p.suffix.lower() != ".md":
                continue
            try:
                mtime = p.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime <= cursor:
                continue
            candidates.append((p, mtime))
        candidates.sort(key=lambda item: item[1])
        return [p for p, _ in candidates[: self.config.max_batch_size]]

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[truncated]"

    def _phase1_prompt_budgeted(
        self,
        files: list[Path],
        *,
        total_max_chars: int,
        per_file_max_chars: int,
        memory_max_chars: int,
    ) -> tuple[str, int]:
        memory_md_text = (
            self.memory_md.read_text(encoding="utf-8", errors="replace")
            if self.memory_md.exists()
            else ""
        )
        memory_md_text = self._truncate_text(memory_md_text, memory_max_chars)
        remaining = max(0, int(total_max_chars or 0))
        seen_hashes: set[str] = set()
        contents: list[tuple[str, str]] = []
        for path in sorted(files, key=lambda p: (p.stat().st_mtime, p.name)):
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            budget = per_file_max_chars if per_file_max_chars > 0 else len(raw)
            if remaining > 0:
                budget = min(budget, remaining)
            chunk = self._truncate_text(raw, budget)
            if not chunk:
                continue
            contents.append((path.name, chunk))
            if remaining > 0:
                remaining -= len(chunk)
                if remaining <= 0:
                    break
        prompt = phase1_prompt_from_contents(memory_md_text, contents)
        return prompt, len(prompt)

    async def _phase1_analyze(self, files: list[Path]) -> str:
        """Phase 1: plain LLM call returning analysis text."""
        prompt, prompt_chars, phase = self._phase1_prompt(files)
        messages = [Message(role="user", content=prompt)]
        _ = phase
        text = await _run_complete(self.provider, messages, 2048)
        self._last_phase1_prompt_chars = prompt_chars
        return text.strip()

    def _phase1_prompt(self, files: list[Path]) -> tuple[str, int, str]:
        mode = getattr(self.config, "input_slimming", "off")
        if mode == "on":
            prompt, chars = self._phase1_prompt_budgeted(
                files,
                total_max_chars=getattr(self.config, "candidate_total_max_chars", 24_000),
                per_file_max_chars=getattr(self.config, "candidate_file_max_chars", 4_000),
                memory_max_chars=getattr(self.config, "memory_max_chars", 12_000),
            )
            return prompt, chars, "dream.phase1.slim"
        memory_md_text = (
            self.memory_md.read_text(encoding="utf-8") if self.memory_md.exists() else ""
        )
        prompt = phase1_prompt(memory_md_text, files)
        if mode == "shadow":
            try:
                _slim_prompt, slim_chars = self._phase1_prompt_budgeted(
                    files,
                    total_max_chars=getattr(self.config, "candidate_total_max_chars", 24_000),
                    per_file_max_chars=getattr(self.config, "candidate_file_max_chars", 4_000),
                    memory_max_chars=getattr(self.config, "memory_max_chars", 12_000),
                )
                logger.info(
                    "dream.phase1.slim_shadow",
                    extra={"full_chars": len(prompt), "slim_chars": slim_chars},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("dream.phase1.slim_shadow_failed", extra={"error": str(exc)})
        return prompt, len(prompt), "dream.phase1"

    @staticmethod
    def _phase1_analysis_needs_fallback(analysis: str) -> bool:
        """Return True when slim Phase 1 output is too weak to feed Phase 2."""

        normalized = " ".join(analysis.strip().lower().split())
        if not normalized:
            return True
        if len(normalized) < 12:
            return True
        weak_markers = (
            "low confidence",
            "insufficient context",
            "not enough context",
            "cannot determine",
            "unable to determine",
            "unable to analyze",
            "no usable",
            "no useful",
            "truncated input",
            "input was truncated",
            "invalid analysis",
            "analysis invalid",
        )
        return any(marker in normalized for marker in weak_markers)

    def _artifact_id(self) -> str:
        import time

        return f"{getattr(self, 'agent_id', 'main')}-{int(time.time() * 1000)}"

    def _workspace_relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(path)

    def _phase2_lock_path(self) -> Path:
        return self.memory_dir / ".dream.lock"

    def _candidate_identities(self, files: list[Path]) -> dict[str, _CandidateIdentity]:
        identities: dict[str, _CandidateIdentity] = {}
        for path in files:
            rel_path = self._workspace_relative(path)
            try:
                stat = path.stat()
                data = path.read_bytes()
            except OSError:
                continue
            identities[rel_path] = _CandidateIdentity(
                path=rel_path,
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
                sha256=hashlib.sha256(data).hexdigest(),
            )
        return identities

    def _stale_batch_reason(
        self,
        files: list[Path],
        expected: dict[str, _CandidateIdentity],
        *,
        cursor_before: float,
    ) -> str | None:
        current_cursor = self.cursor.load()
        if current_cursor != cursor_before:
            return "cursor advanced"
        current = self._candidate_identities(files)
        expected_paths = {self._workspace_relative(path) for path in files}
        if set(expected) != expected_paths:
            missing = sorted(expected_paths - set(expected))
            return f"candidate identity missing before phase2: {missing}"
        if set(current) != expected_paths:
            missing = sorted(expected_paths - set(current))
            return f"candidate disappeared or became unreadable: {missing}"
        for rel_path in sorted(expected_paths):
            if current[rel_path] != expected[rel_path]:
                return f"candidate changed: {rel_path}"
        return None

    def _backup_memory_md(self, artifact_id: str) -> str:
        backup_dir = self.memory_dir / ".dream_backups" / artifact_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "MEMORY.md"
        backup_path.write_bytes(
            self.memory_md.read_bytes() if self.memory_md.exists() else b""
        )
        return self._workspace_relative(backup_path)

    def _backup_candidates(
        self,
        files: list[Path],
        artifact_id: str,
    ) -> list[dict[str, Any]]:
        backup_dir = self.memory_dir / ".dream_backups" / artifact_id / "candidates"
        backups: list[dict[str, Any]] = []
        for path in files:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / path.name
            backup_path.write_bytes(data)
            backups.append(
                {
                    "path": self._workspace_relative(path),
                    "backup_path": self._workspace_relative(backup_path),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        return backups

    def _write_edit_receipt(
        self,
        *,
        artifact_id: str,
        result: DreamResult,
        outcome: _Phase2Outcome,
        files: list[Path],
        deleted_paths: list[str],
        memory_backup_path: str,
        candidate_backups: list[dict[str, Any]],
        max_candidate_mtime: float,
        error: str | None = None,
    ) -> str:
        receipt_dir = self.memory_dir / ".dream_receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"{artifact_id}.json"
        payload = {
            "agent_id": getattr(self, "agent_id", "main"),
            "dry_run": result.dry_run,
            "memory_md_path": self._workspace_relative(self.memory_md),
            "memory_md_backup_path": memory_backup_path,
            "memory_md_sha_before": result.memory_md_sha_before,
            "memory_md_sha_after": result.memory_md_sha_after,
            "cursor_before": result.cursor_before,
            "cursor_after": result.cursor_after,
            "max_candidate_mtime": max_candidate_mtime,
            "candidate_paths": [self._workspace_relative(path) for path in files],
            "candidate_backups": candidate_backups,
            "deleted_paths": deleted_paths,
            "applied_operations": outcome.applied_operations,
            "error": error,
            "rollback": {
                "restore_memory_from": memory_backup_path,
                "restore_candidates_from": candidate_backups,
                "reset_cursor_to": result.cursor_before,
            },
        }
        receipt_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return self._workspace_relative(receipt_path)

    async def _phase1_analyze_with_fallback(self, files: list[Path]) -> tuple[str, bool]:
        analysis = await self._phase1_analyze(files)
        if getattr(self.config, "input_slimming", "off") != "on":
            return analysis, False
        if not self._phase1_analysis_needs_fallback(analysis):
            return analysis, False

        prompt, prompt_chars = self._phase1_prompt_budgeted(
            files,
            total_max_chars=getattr(self.config, "fallback_total_max_chars", 80_000),
            per_file_max_chars=max(
                getattr(self.config, "candidate_file_max_chars", 4_000),
                getattr(self.config, "fallback_total_max_chars", 80_000),
            ),
            memory_max_chars=max(
                getattr(self.config, "memory_max_chars", 12_000),
                getattr(self.config, "fallback_total_max_chars", 80_000),
            ),
        )
        messages = [Message(role="user", content=prompt)]
        text = await _run_complete(self.provider, messages, 2048)
        self._last_phase1_prompt_chars = prompt_chars
        fallback_analysis = text.strip()
        if self._phase1_analysis_needs_fallback(fallback_analysis):
            raise ValueError("Phase 1 fallback analysis was empty, invalid, or low-confidence")
        return fallback_analysis, True

    async def _phase2_generate_edit_plan(
        self,
        phase1_output: str,
    ) -> list[dict[str, Any]]:
        """Phase 2 provider call: request and validate a JSON edit plan."""
        prompt = phase2_prompt(phase1_output)
        messages = [Message(role="user", content=prompt)]
        text = await _run_complete(self.provider, messages, 4096)
        m = _JSON_BLOCK_RE.search(text)
        if not m:
            raise ValueError(f"Phase 2 response did not contain JSON: {text[:300]}")
        try:
            plan = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Phase 2 JSON invalid: {exc}: {m.group(0)[:300]}") from exc

        edits = plan.get("edits") or []
        if not isinstance(edits, list):
            raise ValueError(f"Phase 2 edits must be a list, got {type(edits).__name__}")
        return [edit for edit in edits if isinstance(edit, dict)]

    async def _phase2_apply_edit_plan(
        self,
        edits: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> _Phase2Outcome:
        """Apply an already-generated Phase 2 edit plan to MEMORY.md."""
        content = self.memory_md.read_text(encoding="utf-8") if self.memory_md.exists() else ""
        changes = 0
        applied_operations: list[dict[str, Any]] = []
        for edit in edits:
            op = edit.get("op")
            if op == "append":
                addition = edit.get("text", "")
                if content and not content.endswith("\n"):
                    content += "\n"
                content += addition
                changes += 1
                applied_operations.append(
                    {
                        "op": "append",
                        "changed": True,
                        "text_chars": len(addition),
                        "text_sha256": hashlib.sha256(
                            addition.encode("utf-8")
                        ).hexdigest(),
                    }
                )
            elif op == "replace":
                find = edit.get("find", "")
                repl = edit.get("with", "")
                if find and find in content:
                    content = content.replace(find, repl, 1)
                    changes += 1
                    changed = True
                else:
                    changed = False
                applied_operations.append(
                    {
                        "op": "replace",
                        "changed": changed,
                        "find_sha256": hashlib.sha256(
                            str(find).encode("utf-8")
                        ).hexdigest(),
                        "with_chars": len(str(repl)),
                        "with_sha256": hashlib.sha256(
                            str(repl).encode("utf-8")
                        ).hexdigest(),
                    }
                )
            else:
                logger.warning("dream.phase2.unknown_op", extra={"op": op})
                applied_operations.append(
                    {
                        "op": str(op),
                        "changed": False,
                        "error": "unknown_op",
                    }
                )

        if changes and not dry_run:
            self.memory_md.parent.mkdir(parents=True, exist_ok=True)
            self.memory_md.write_text(content, encoding="utf-8")

        return _Phase2Outcome(
            tool_calls=1,
            changes=changes,
            applied_operations=applied_operations,
        )

    async def _phase2_apply_edits(
        self,
        phase1_output: str,
        *,
        dry_run: bool = False,
    ) -> _Phase2Outcome:
        """Back-compat wrapper for tests that call the old combined helper."""
        edits = await self._phase2_generate_edit_plan(phase1_output)
        return await self._phase2_apply_edit_plan(edits, dry_run=dry_run)

    async def run(self) -> DreamResult:
        """Entry point — orchestrates Phase 1 + Phase 2.

        Phase 1 error: no cursor advance, no delete.
        Phase 2 error: cursor advances (avoid retry loop), files retained
        (PR5 TTL/FIFO sweeps later).
        Success: delete processed files, advance cursor.
        """
        import time

        result = DreamResult(
            cursor_before=self.cursor.load(),
            memory_md_sha_before=(
                hashlib.sha256(self.memory_md.read_bytes()).hexdigest()
                if self.memory_md.exists()
                else None
            ),
            input_slimming=getattr(self.config, "input_slimming", "off"),
            dry_run=bool(
                getattr(self.config, "preview_mode", False)
                or getattr(self.config, "dry_run", False)
            ),
        )

        files = self._candidate_files()
        result.files_considered = len(files)
        if len(files) < getattr(self.config, "min_batch_size", 1):
            result.cursor_after = result.cursor_before
            try:
                self._emit_log(result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("dream.log_emit_failed", extra={"error": str(exc)})
            return result

        # Phase 1 — pure read, no lock.
        p1_start = time.monotonic()
        try:
            analysis, fallback_used = await self._phase1_analyze_with_fallback(files)
            result.phase1_ms = int((time.monotonic() - p1_start) * 1000)
            result.phase1_status = "ok"
            result.phase1_prompt_chars = int(getattr(self, "_last_phase1_prompt_chars", 0) or 0)
            result.phase1_fallback_used = fallback_used
        except Exception as exc:  # noqa: BLE001
            result.phase1_ms = int((time.monotonic() - p1_start) * 1000)
            result.phase1_status = "error"
            result.error = f"phase1: {exc}"
            logger.warning("dream.phase1.error", extra={"error": str(exc)})
            result.cursor_after = result.cursor_before
            return result

        # Phase 2 — provider planning stays outside file locks; only
        # filesystem mutation/cursor/receipt side effects are serialized.
        p2_start = time.monotonic()
        max_mtime = max(
            (p.stat().st_mtime for p in files),
            default=result.cursor_before,
        )
        artifact_id = self._artifact_id()
        expected_identities = self._candidate_identities(files)

        async def _phase2_apply_locked(edits: list[dict[str, Any]]) -> _Phase2Outcome:
            nonlocal max_mtime
            with _DreamFileLock(self._phase2_lock_path()):
                stale_reason = self._stale_batch_reason(
                    files,
                    expected_identities,
                    cursor_before=result.cursor_before,
                )
                if stale_reason is not None:
                    result.phase2_status = "conflict"
                    result.error = f"phase2_stale_batch: {stale_reason}"
                    result.cursor_after = result.cursor_before
                    result.memory_md_sha_after = (
                        hashlib.sha256(self.memory_md.read_bytes()).hexdigest()
                        if self.memory_md.exists()
                        else None
                    )
                    outcome = _Phase2Outcome(tool_calls=1, changes=0)
                    result.edit_receipt_path = self._write_edit_receipt(
                        artifact_id=artifact_id,
                        result=result,
                        outcome=outcome,
                        files=files,
                        deleted_paths=[],
                        memory_backup_path="",
                        candidate_backups=[],
                        max_candidate_mtime=result.cursor_before,
                        error=result.error,
                    )
                    return outcome

                current_mtimes: list[float] = []
                for path in files:
                    try:
                        current_mtimes.append(path.stat().st_mtime)
                    except OSError:
                        pass
                max_mtime = max(current_mtimes, default=result.cursor_before)
                memory_backup_path = self._backup_memory_md(artifact_id)
                candidate_backups = self._backup_candidates(files, artifact_id)
                outcome = await self._phase2_apply_edit_plan(edits, dry_run=result.dry_run)

                deleted_paths: list[str] = []
                cleanup_error: Exception | None = None
                if result.dry_run:
                    result.files_processed = 0
                    result.cursor_after = result.cursor_before
                else:
                    for p in files:
                        try:
                            p.unlink()
                            deleted_paths.append(self._workspace_relative(p))
                            result.files_deleted += 1
                        except FileNotFoundError:
                            pass
                        except Exception as exc:  # noqa: BLE001
                            cleanup_error = cleanup_error or exc
                            logger.warning(
                                "dream.candidate_delete_failed",
                                extra={"path": str(p), "error": str(exc)},
                            )
                    result.files_processed = len(files)
                    try:
                        self.cursor.save(max_mtime)
                        result.cursor_after = max_mtime
                    except Exception as exc:  # noqa: BLE001
                        cleanup_error = cleanup_error or exc
                        result.cursor_after = result.cursor_before
                result.memory_md_sha_after = (
                    hashlib.sha256(self.memory_md.read_bytes()).hexdigest()
                    if self.memory_md.exists()
                    else None
                )
                if cleanup_error is not None:
                    result.phase2_status = "error"
                    result.error = f"phase2_cleanup: {cleanup_error}"
                result.edit_receipt_path = self._write_edit_receipt(
                    artifact_id=artifact_id,
                    result=result,
                    outcome=outcome,
                    files=files,
                    deleted_paths=deleted_paths,
                    memory_backup_path=memory_backup_path,
                    candidate_backups=candidate_backups,
                    max_candidate_mtime=max_mtime,
                    error=result.error,
                )
                return outcome

        outcome: _Phase2Outcome | None = None
        try:
            edits = await self._phase2_generate_edit_plan(analysis)
            if self.session_lock is not None:
                async with self.session_lock:
                    outcome = await _phase2_apply_locked(edits)
            else:
                outcome = await _phase2_apply_locked(edits)
            result.phase2_ms = int((time.monotonic() - p2_start) * 1000)
            if result.phase2_status not in {"conflict", "error"}:
                result.phase2_status = "ok"
            result.phase2_tool_calls = outcome.tool_calls
        except Exception as exc:  # noqa: BLE001
            result.phase2_ms = int((time.monotonic() - p2_start) * 1000)
            result.phase2_status = "error"
            result.error = f"phase2: {exc}"
            logger.warning("dream.phase2.error", extra={"error": str(exc)})
            # Advance cursor anyway so a bad batch doesn't retry forever.
            try:
                self.cursor.save(max_mtime)
                result.cursor_after = max_mtime
            except Exception as cursor_exc:  # noqa: BLE001
                result.cursor_after = result.cursor_before
                result.error = f"{result.error}; cursor_save: {cursor_exc}"
            result.memory_md_sha_after = (
                hashlib.sha256(self.memory_md.read_bytes()).hexdigest()
                if self.memory_md.exists()
                else None
            )
            if outcome is not None:
                try:
                    result.edit_receipt_path = self._write_edit_receipt(
                        artifact_id=artifact_id,
                        result=result,
                        outcome=outcome,
                        files=files,
                        deleted_paths=[],
                        memory_backup_path="",
                        candidate_backups=[],
                        max_candidate_mtime=max_mtime,
                        error=result.error,
                    )
                except Exception as receipt_exc:  # noqa: BLE001
                    logger.warning(
                        "dream.edit_receipt_failed",
                        extra={"error": str(receipt_exc)},
                    )

        if self.memory_md.exists() and result.memory_md_sha_after is None:
            result.memory_md_sha_after = hashlib.sha256(self.memory_md.read_bytes()).hexdigest()

        try:
            self._emit_log(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dream.log_emit_failed", extra={"error": str(exc)})

        return result
