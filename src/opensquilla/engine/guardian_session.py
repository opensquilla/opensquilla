"""Reusable, read-only Guardian Agent trunk with ephemeral parallel forks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from opensquilla.engine.guardian_prompt import (
    build_guardian_prompt,
    collect_guardian_transcript_entries,
    guardian_output_schema,
    guardian_policy_prompt,
)
from opensquilla.engine.types import AgentConfig, ErrorEvent, TextDeltaEvent
from opensquilla.provider import LLMProvider, Message
from opensquilla.sandbox.permissions import FileSystemPermissionProfile
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, InteractionMode, ToolContext

READ_ONLY_GUARDIAN_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "glob_search",
        "grep_search",
        "git_status",
        "git_diff",
        "git_log",
    }
)

_TRANSIENT_SESSION_CODES = frozenset(
    {
        "server_overloaded",
        "http_connection_failed",
        "response_stream_connection_failed",
        "internal_server_error",
        "response_stream_disconnected",
        "request_error",
        "provider_internal",
        "429",
        "500",
        "502",
        "503",
        "504",
    }
)


class GuardianSessionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient


class _GuardianAgent(Protocol):
    def set_history(self, messages: list[Message]) -> None: ...

    def history_snapshot(self) -> list[Message]: ...

    def run_turn(self, message: str) -> Any: ...


GuardianAgentFactory = Callable[[list[Message]], _GuardianAgent]
GuardianResponseValidator = Callable[[str], Any]


def build_read_only_guardian_registry(source: ToolRegistry) -> ToolRegistry:
    """Copy exactly the seven Codex Guardian inspection tools."""

    registry = ToolRegistry()
    missing: list[str] = []
    for name in sorted(READ_ONLY_GUARDIAN_TOOLS):
        registered = source.get(name)
        if registered is None:
            missing.append(name)
            continue
        registry.register(replace(registered.spec), registered.handler)
    if missing:
        raise ValueError(f"guardian_read_only_tools_missing:{','.join(missing)}")
    return registry


class GuardianReviewSessionManager:
    """Own one committed Guardian history and fork it for overlapping reviews."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        tool_registry: ToolRegistry,
        workspace: Path,
        parent_config: AgentConfig,
        timeout_seconds: float = 90.0,
        file_system_profile: FileSystemPermissionProfile | None = None,
        agent_factory: GuardianAgentFactory | None = None,
    ) -> None:
        self._provider = provider
        self._workspace = workspace.expanduser().resolve(strict=False)
        self._timeout_seconds = timeout_seconds
        self._registry = build_read_only_guardian_registry(tool_registry)
        self._context = ToolContext(
            is_owner=True,
            caller_kind=CallerKind.AGENT,
            interaction_mode=InteractionMode.UNATTENDED,
            agent_id="guardian",
            workspace_dir=str(self._workspace),
            workspace_strict=False,
            session_key="guardian-review",
            run_mode="standard",
            allowed_tools=set(READ_ONLY_GUARDIAN_TOOLS),
            sandbox_file_system_profile=(
                file_system_profile or FileSystemPermissionProfile.read_only()
            ).as_read_only(),
            coding_mode=True,
            source_diff_preservation_mode="off",
            source_diff_candidate_mode="off",
        )
        policy_prompt = guardian_policy_prompt()
        self._config = AgentConfig(
            max_iterations=8,
            timeout=timeout_seconds,
            iteration_timeout=timeout_seconds,
            request_timeout=min(parent_config.request_timeout, timeout_seconds),
            tool_timeout=min(parent_config.tool_timeout, timeout_seconds),
            max_tokens=1_000,
            temperature=0,
            thinking=False,
            system_prompt=policy_prompt,
            workspace_dir=str(self._workspace),
            model_id=parent_config.model_id,
            provider_id=parent_config.provider_id,
            max_provider_retries=0,
            cache_breakpoints=[{"text": policy_prompt, "cache": "true"}],
            cache_mode=parent_config.cache_mode,
            output_json_schema=guardian_output_schema(),
            output_json_schema_strict=False,
            context_window_tokens=parent_config.context_window_tokens,
            max_history_turns=0,
            flush_enabled=False,
            repair_enabled=False,
            tool_result_compression_enabled=False,
            source_diff_preservation_mode="off",
            source_diff_candidate_mode="off",
            runtime_recovery_mode="off",
            final_diff_contract_mode="off",
            metadata={"agent_role": "guardian", "ephemeral": True},
        )
        self._agent_factory = agent_factory or self._default_agent_factory
        self._trunk: _GuardianAgent | None = None
        self._committed_history: list[Message] = []
        self._committed_parent_entries: list[tuple[str, str, str]] = []
        self._busy = False

    @property
    def allowed_tools(self) -> frozenset[str]:
        return READ_ONLY_GUARDIAN_TOOLS

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(self._registry.list_names())

    def _default_agent_factory(self, history: list[Message]) -> _GuardianAgent:
        from opensquilla.engine.agent import Agent

        handler = build_tool_handler(self._registry, self._context)
        agent = Agent(
            provider=self._provider,
            config=replace(self._config),
            tool_definitions=self._registry.to_tool_definitions(self._context),
            tool_handler=handler,
            session_key="guardian-review",
            tool_registry=self._registry,
            tool_context=replace(self._context),
        )
        agent.set_history(history)
        return agent

    def prewarm(self) -> bool:
        """Eagerly create the reusable trunk without calling the provider."""

        if self._trunk is not None or self._busy:
            return False
        self._trunk = self._agent_factory(list(self._committed_history))
        return True

    async def review(
        self,
        prompt: str,
        *,
        response_validator: GuardianResponseValidator | None = None,
    ) -> str:
        """Run on the trunk when idle; otherwise use an uncommitted fork."""

        if not self._busy:
            self._busy = True
            try:
                if self._trunk is None:
                    self._trunk = self._agent_factory(list(self._committed_history))
                result = await self._run(self._trunk, prompt)
                if response_validator is not None:
                    response_validator(result)
                self._committed_history = self._trunk.history_snapshot()
                return result
            except Exception:
                self._trunk = None
                raise
            finally:
                self._busy = False

        fork = self._agent_factory(list(self._committed_history))
        result = await self._run(fork, prompt)
        if response_validator is not None:
            response_validator(result)
        return result

    async def review_action(
        self,
        transcript: list[Message],
        action: Mapping[str, Any],
        *,
        retry_reason: str | None = None,
        response_validator: GuardianResponseValidator | None = None,
    ) -> str:
        """Build a full or delta prompt against the latest committed trunk cursor."""

        current_entries = collect_guardian_transcript_entries(transcript)
        cursor = len(self._committed_parent_entries)
        can_delta = (
            cursor > 0
            and cursor <= len(current_entries)
            and current_entries[:cursor] == self._committed_parent_entries
        )
        prompt = build_guardian_prompt(
            transcript,
            dict(action),
            retry_reason=retry_reason,
            entry_offset=cursor if can_delta else 0,
            delta=can_delta,
        ).text
        was_busy = self._busy
        result = await self.review(prompt, response_validator=response_validator)
        if not was_busy:
            self._committed_parent_entries = list(current_entries)
        return result

    async def _run(self, agent: _GuardianAgent, prompt: str) -> str:
        answer_parts: list[str] = []
        async with asyncio.timeout(self._timeout_seconds):
            async for event in agent.run_turn(prompt):
                if isinstance(event, TextDeltaEvent) and event.presentation == "answer":
                    answer_parts.append(event.text)
                elif isinstance(event, ErrorEvent):
                    code = str(event.code or "").strip().lower()
                    raise GuardianSessionError(
                        event.message or code or "guardian_session_error",
                        code=code,
                        transient=code in _TRANSIENT_SESSION_CODES,
                    )
        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("guardian_session_empty_response")
        return answer


__all__ = [
    "GuardianReviewSessionManager",
    "GuardianSessionError",
    "READ_ONLY_GUARDIAN_TOOLS",
    "build_read_only_guardian_registry",
]
