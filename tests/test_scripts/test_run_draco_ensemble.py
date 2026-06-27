from __future__ import annotations

import asyncio
import json
from argparse import Namespace
from pathlib import Path

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import (
    DoneEvent,
    ErrorEvent,
    Message,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)
from scripts.run_draco_ensemble import (
    GROUP_SPECS,
    RunResult,
    amain,
    benchmark_tool_policy,
    benchmark_tools_for_policy,
    configure_benchmark_sandbox_runtime,
    build_parser,
    build_benchmark_tool_context,
    build_local_web_tool_registry,
    build_profile_provider,
    candidate_texts,
    compact_chat_config,
    configure_local_web_search_runtime,
    collect_agent_run,
    collect_generation_with_retries,
    collect_run,
    generation_chat_config,
    generation_thinking_policy,
    group_timeout_seconds,
    judge_text,
    load_tasks,
    parse_domain_list,
    quality_total,
    render_markdown,
    run_one,
    run_result_summary,
    score_criterion_judgments,
    summarize,
)


@pytest.fixture(autouse=True)
def _reset_sandbox_runtime_for_draco_tests() -> None:
    from opensquilla.sandbox.integration import reset_runtime

    reset_runtime()
    yield
    reset_runtime()


class _CriterionJudgeProvider:
    model = "judge-test"
    provider_name = "judge"

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        prompt = str(messages[-1].content)
        verdict = "UNMET" if "type: negative" in prompt else "MET"
        yield TextDeltaEvent(
            text=f'```json\n{{"verdict":"{verdict}","rationale":"ok"}}\n```'
        )
        yield DoneEvent(model=self.model)

    async def list_models(self) -> list:
        return []


class _FlakyCriterionJudgeProvider:
    model = "judge-flaky"
    provider_name = "judge"

    def __init__(self, *, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls <= self.failures_before_success:
            yield TextDeltaEvent(text='{"verdict":"MAYBE","rationale":"not parseable"}')
        else:
            yield TextDeltaEvent(text='{"verdict":"MET","rationale":"ok"}')
        yield DoneEvent(model=self.model)

    async def list_models(self) -> list:
        return []


class _CountingJudgeProvider(_CriterionJudgeProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        self.calls += 1
        async for event in super().chat(messages, tools=tools, config=config):
            yield event


class _SlowProvider:
    provider_name = "slow"

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        await asyncio.sleep(1.0)
        yield TextDeltaEvent(text="late")
        yield DoneEvent(model="slow")

    async def list_models(self) -> list:
        return []


class _DiagnosticErrorProvider:
    provider_name = "diagnostic-error"

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        yield ErrorEvent(
            message="boom",
            code="diagnostic_boom",
            diagnostic_done=DoneEvent(
                input_tokens=7,
                output_tokens=3,
                billed_cost=0.12,
                model="diagnostic-model",
                ensemble_trace={"kept": True},
            ),
        )

    async def list_models(self) -> list:
        return []


class _EmptyThenSuccessProvider:
    provider_name = "empty-then-success"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls == 1:
            yield DoneEvent(model="empty")
            return
        yield TextDeltaEvent(text="recovered")
        yield DoneEvent(model="success")

    async def list_models(self) -> list:
        return []


class _AlwaysEmptyProvider:
    provider_name = "always-empty"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        yield DoneEvent(model="empty")

    async def list_models(self) -> list:
        return []


class _ErrorThenSuccessProvider:
    provider_name = "error-then-success"

    def __init__(self, *, failures_before_success: int = 1) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls <= self.failures_before_success:
            yield TextDeltaEvent(text="partial")
            yield ErrorEvent(message="boom", code="boom")
            return
        yield TextDeltaEvent(text="recovered")
        yield DoneEvent(model="success")

    async def list_models(self) -> list:
        return []


class _MissingDoneProvider:
    provider_name = "missing-done"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        yield TextDeltaEvent(text="partial answer")

    async def list_models(self) -> list:
        return []


class _ToolCaptureProvider:
    provider_name = "tool-capture"

    def __init__(self) -> None:
        self.seen_tools = None

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.seen_tools = tools
        yield TextDeltaEvent(text="ok")
        yield DoneEvent(model="tool-capture")

    async def list_models(self) -> list:
        return []


class _AgentToolLoopProvider:
    provider_name = "agent-tool-loop"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls == 1:
            yield ToolUseStartEvent(tool_use_id="call_1", tool_name="web_fetch")
            yield ToolUseDeltaEvent(
                tool_use_id="call_1",
                json_fragment='{"url":"https://huggingface.co/datasets/perplexity-ai/draco"}',
            )
            yield ToolUseEndEvent(
                tool_use_id="call_1",
                tool_name="web_fetch",
                arguments={
                    "url": "https://huggingface.co/datasets/perplexity-ai/draco"
                },
            )
            yield DoneEvent(input_tokens=10, output_tokens=2, model="tool-loop")
            return
        yield TextDeltaEvent(text="final after tool")
        yield DoneEvent(input_tokens=11, output_tokens=4, model="tool-loop")

    async def list_models(self) -> list:
        return []


@pytest.mark.asyncio
async def test_draco_runner_dry_run_writes_jsonl_and_summary(tmp_path: Path) -> None:
    input_path = tmp_path / "draco.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "id": "task-1",
                "prompt": "Explain the evidence carefully.",
                "domain": "science",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"
    args = Namespace(
        input=input_path,
        config=None,
        output_dir=output_dir,
        groups="B2,G1,G3",
        max_tasks=0,
        concurrency=2,
        timeout=10.0,
        runner_mode="provider",
        agent_max_iterations=12,
        dry_run=True,
        judge_model="dry-judge",
        judge_repeats=1,
        judge_concurrency=1,
        judge_max_attempts=3,
        judge_candidates=True,
        generation_max_attempts=3,
        generation_retry_backoff=0.0,
        command_argv=[
            ".venv/bin/python",
            "scripts/run_draco_ensemble.py",
            "--input",
            str(input_path),
            "--groups",
            "B2,G1,G3",
            "--dry-run",
        ],
    )

    rc = await amain(args)

    assert rc == 0
    [jsonl_path] = output_dir.glob("draco_ensemble_*.jsonl")
    rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["group"] for row in rows} == {"B2", "G1", "G3"}
    g1 = next(row for row in rows if row["group"] == "G1")
    assert g1["ensemble_trace"]["profile"] == "g1_code"
    g3 = next(row for row in rows if row["group"] == "G3")
    assert g3["ensemble_trace"]["profile"] == "g3_standard"
    assert g3["candidate_judges"]
    assert g3["usage"]["model_usage_breakdown"]
    assert g3["run_trace"]["event_count"] >= 2
    assert g3["final_text_sha256"]
    assert g3["runner_mode"] == "provider"
    assert g3["tools_enabled"] is False
    assert g3["stream_tool_call_count"] == 0
    assert g3["server_tool_call_count"] == 0
    assert g3["total_tool_call_count"] == 0
    assert g3["llm_request_count"] == 3
    assert g3["trajectory_steps"] == 3
    assert g3["generation_policy"]["generation_thinking"] == "high"
    assert g3["generation_config"]["thinking"] is True
    assert g3["generation_config"]["temperature"] == 0.0
    assert g3["generation_attempt_count"] == 1
    assert g3["generation_max_attempts"] == 3
    assert g3["generation_retry_backoff_s"] == 0.0
    assert g3["ensemble_trace"]["shuffle_candidates"] is False
    assert "huggingface.co" in g3["contamination_blocked_domains"]
    assert g3["tool_policy"]["contamination_controls"]["status"] == (
        "not_applicable_no_external_tools"
    )
    md_path = jsonl_path.with_suffix(".md")
    markdown = md_path.read_text(encoding="utf-8")
    assert "DRACO Ensemble Summary" in markdown
    assert "Contamination blocked domains" in markdown
    assert "temperature: `0.0`" in markdown
    summary_json_path = jsonl_path.with_suffix(".summary.json")
    assert summary_json_path.exists()
    [trace_path] = output_dir.glob("draco_run_*.trace.jsonl")
    trace_rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(trace_rows) == len(rows)
    assert trace_rows[0]["run_trace"]["events"]
    assert trace_rows[0]["generation_policy"]["generation_thinking"] == "high"
    assert trace_rows[0]["generation_attempt_count"] == 1
    assert trace_rows[0]["generation_retry_backoff_s"] == 0.0
    assert "llm_request_count" in trace_rows[0]
    [command_path] = output_dir.glob("draco_run_*.command.txt")
    command_text = command_path.read_text(encoding="utf-8")
    assert "scripts/run_draco_ensemble.py" in command_text
    assert "--groups B2,G1,G3" in command_text
    [manifest_path] = output_dir.glob("draco_run_*.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["rows_written"] == len(rows)
    assert manifest["artifacts"]["trace_jsonl"] == str(trace_path)
    assert manifest["artifacts"]["command_txt"] == str(command_path)
    assert ".venv/bin/python scripts/run_draco_ensemble.py" in manifest["command"]["shell"]
    assert manifest["tool_policy"]["tool_mode"] == "provider_only"
    assert manifest["runner_mode"] == "provider"
    assert manifest["agent_max_iterations"] == 12
    assert manifest["generation_policy"]["generation_thinking"] == "high"
    assert "huggingface.co" in manifest["tool_policy"]["contamination_blocked_domains"]


def test_draco_runner_requires_explicit_groups() -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--input", "draco.jsonl"])

    assert exc.value.code == 2


def test_draco_runner_explicit_groups_preserve_runtime_defaults() -> None:
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G1",
    ])

    assert args.groups == "G1"
    assert GROUP_SPECS["G1"]["profile"] == "g1_code"
    assert args.judge_repeats == 3
    assert args.judge_concurrency == 1
    assert args.judge_max_attempts == 3
    assert args.generation_max_attempts == 3
    assert args.generation_retry_backoff == 2.0
    assert args.generation_thinking == "high"
    assert args.runner_mode == "agent_loop"
    assert args.agent_max_iterations == 12
    assert args.tool_mode == "provider_only"
    assert args.openrouter_web_search_engine == "exa"
    assert args.openrouter_web_fetch_engine == "openrouter"
    assert "hf.co" in parse_domain_list(args.contamination_blocked_domains)
    assert "huggingface.co" in parse_domain_list(args.contamination_blocked_domains)
    assert "arxiv.org" not in parse_domain_list(args.contamination_blocked_domains)


def test_draco_runner_single_model_baselines_cover_extra_frontiers() -> None:
    expected = {
        "B2": "z-ai/glm-5.2",
        "B4": "deepseek/deepseek-v4-pro",
        "B5": "moonshotai/kimi-k2.7-code",
        "B6": "qwen/qwen3.7-plus",
        "B7": "google/gemini-3-flash-preview",
    }
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        ",".join(expected),
    ])
    requested_groups = args.groups.split(",")

    for group, model in expected.items():
        assert group in requested_groups
        assert GROUP_SPECS[group] == {"kind": "single", "model": model}


def test_draco_runner_contamination_domains_normalize_and_dedupe() -> None:
    domains = parse_domain_list(
        "https://HuggingFace.co/datasets/x,https://hf.co/datasets/perplexity-ai/draco,"
        "*.OPENROUTER.AI, huggingface.co"
    )

    assert domains == ["huggingface.co", "hf.co", "openrouter.ai"]


def test_draco_runner_openrouter_server_tools_policy_enforces_conflict_domains() -> None:
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "openrouter_server_tools",
        "--contamination-blocked-domains",
        "huggingface.co,github.com",
    ])

    policy = benchmark_tool_policy(args)
    tools = benchmark_tools_for_policy(policy)

    assert policy["tools_enabled"] is True
    assert policy["tool_names"] == ["openrouter:web_search", "openrouter:web_fetch"]
    assert policy["contamination_controls"]["status"] == (
        "enforced_by_openrouter_server_tools"
    )
    assert policy["openrouter_server_tools"]["web_search"]["parameters"][
        "excluded_domains"
    ] == ["huggingface.co", "github.com"]
    assert policy["openrouter_server_tools"]["web_fetch"]["parameters"][
        "blocked_domains"
    ] == ["huggingface.co", "github.com"]
    assert tools is not None
    assert [tool.provider_tool["type"] for tool in tools] == [  # type: ignore[index]
        "openrouter:web_search",
        "openrouter:web_fetch",
    ]


def test_draco_runner_local_web_tools_policy_enforces_conflict_domains() -> None:
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--contamination-blocked-domains",
        "huggingface.co,github.com",
    ])

    policy = benchmark_tool_policy(args)
    tools = benchmark_tools_for_policy(policy)

    assert policy["tools_enabled"] is True
    assert policy["tool_names"] == ["web_search", "web_fetch"]
    assert policy["contamination_controls"]["status"] == "enforced_by_local_web_tools"
    assert policy["local_web_tools"]["web_search"]["excluded_domains"] == [
        "huggingface.co",
        "github.com",
    ]
    assert policy["local_web_tools"]["web_fetch"]["blocked_domains"] == [
        "huggingface.co",
        "github.com",
    ]
    assert policy["local_web_tools"]["web_fetch"]["max_content_chars"] == 200_000
    assert tools is not None
    assert [tool.name for tool in tools] == ["web_search", "web_fetch"]


def test_draco_runner_local_web_tool_context_matches_recorded_budget() -> None:
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--openrouter-web-search-max-results",
        "7",
        "--openrouter-web-fetch-max-content-tokens",
        "1234",
    ])
    policy = benchmark_tool_policy(args)

    ctx = build_benchmark_tool_context(
        task_id="task-1",
        group="G3",
        tool_policy=policy,
    )

    assert ctx.tool_run_budget_policy.max_web_search_results == 7
    assert ctx.tool_run_budget_policy.max_single_fetch_chars == 4936
    assert policy["local_web_tools"]["web_fetch"]["max_content_chars"] == 4936


def test_draco_runner_configures_sandbox_runtime_for_local_web_tools() -> None:
    from opensquilla.sandbox.integration import get_runtime

    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
    ])

    runtime = configure_benchmark_sandbox_runtime(
        GatewayConfig(),
        benchmark_tool_policy(args),
    )

    assert runtime["configured"] is True
    assert runtime["backend"] == "noop"
    assert runtime["approval_queue"] == "auto_deny_unattended"
    assert runtime["effective"]["sandbox_enabled"] is False
    assert get_runtime() is not None


@pytest.mark.asyncio
async def test_draco_runner_local_web_search_clamps_model_max_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def _fake_search(query: str, max_results: int | None = None) -> dict:
        calls.append((query, int(max_results or 0)))
        return {"results": [{"url": "https://example.com/source", "title": "source"}]}

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.run_web_search_payload",
        _fake_search,
    )
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--openrouter-web-search-max-results",
        "7",
    ])
    registry = build_local_web_tool_registry(benchmark_tool_policy(args))
    registered = registry.get("web_search")

    assert registered is not None
    await registered.handler(query="research topic", max_results="999")
    await registered.handler(query="research topic", max_results="not-a-number")

    assert [call[1] for call in calls] == [7, 7]


@pytest.mark.asyncio
async def test_draco_runner_local_web_fetch_clamps_model_max_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int | None] = []

    async def _fake_fetch(
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
    ) -> str:
        calls.append(max_chars)
        return json.dumps(
            {"url": url, "extract_mode": extract_mode, "max_chars": max_chars}
        )

    monkeypatch.setattr("opensquilla.tools.builtin.web_fetch.web_fetch", _fake_fetch)
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--openrouter-web-fetch-max-content-tokens",
        "1234",
    ])
    registry = build_local_web_tool_registry(benchmark_tool_policy(args))
    registered = registry.get("web_fetch")

    assert registered is not None
    await registered.handler(url="https://example.com/source", max_chars="999999")
    await registered.handler(url="https://example.com/source", max_chars="10")
    await registered.handler(url="https://example.com/source", max_chars="bad")

    assert calls == [4936, 100, 4936]


@pytest.mark.asyncio
async def test_draco_runner_local_web_fetch_uses_configured_sandbox_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    from opensquilla.tools.types import current_tool_context

    web_fetch_mod = importlib.import_module("opensquilla.tools.builtin.web_fetch")
    web_fetch_mod._cache.clear()
    monkeypatch.setattr(web_fetch_mod, "_check_ssrf", lambda url: None)

    class _FakeResponse:
        def __init__(self, url: str) -> None:
            self.status_code = 200
            self.url = url
            self.headers = {"content-type": "text/plain"}
            self.text = "benchmark fetch ok"

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> _FakeResponse:
            return _FakeResponse(url)

    monkeypatch.setattr(web_fetch_mod.httpx, "AsyncClient", _FakeClient)
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
    ])
    policy = benchmark_tool_policy(args)
    configure_benchmark_sandbox_runtime(GatewayConfig(), policy)
    ctx = build_benchmark_tool_context(
        task_id="task-1",
        group="G3",
        tool_policy=policy,
    )
    registry = build_local_web_tool_registry(policy)
    registered = registry.get("web_fetch")

    assert registered is not None
    token = current_tool_context.set(ctx)
    try:
        raw = await registered.handler(url="https://example.com/draco-runtime")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(raw)
    assert payload["status"] == 200
    assert payload["extractor"] == "raw"
    assert "benchmark fetch ok" in payload["text"]
    assert "runtime_unconfigured" not in raw


def test_draco_runner_configures_local_search_runtime_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_configure_search(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-secret")
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.configure_search",
        _fake_configure_search,
    )
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--openrouter-web-search-max-results",
        "7",
    ])

    runtime = configure_local_web_search_runtime(
        GatewayConfig(search_max_results=2),
        benchmark_tool_policy(args),
    )

    assert calls
    assert calls[0]["provider_name"] == "brave"
    assert calls[0]["api_key"] == "brave-secret"
    assert calls[0]["max_results"] == 7
    assert runtime["provider"] == "brave"
    assert runtime["max_results"] == 7
    assert runtime["api_key_configured"] is True
    assert "brave-secret" not in json.dumps(runtime)


def test_draco_runner_candidate_texts_can_scope_to_final_agent_call() -> None:
    done = DoneEvent(
        ensemble_trace={
            "calls": [
                {"candidates": [{"text": "tool planning candidate"}]},
                {"candidates": [{"text": "final answer candidate"}]},
            ]
        }
    )

    assert candidate_texts(done) == [
        "tool planning candidate",
        "final answer candidate",
    ]
    assert candidate_texts(done, final_agent_call_only=True) == [
        "final answer candidate"
    ]


def test_draco_runner_profile_groups_exist_in_default_config() -> None:
    cfg = GatewayConfig()
    missing = [
        group
        for group, spec in GROUP_SPECS.items()
        if spec["kind"] == "profile" and spec["profile"] not in cfg.llm_ensemble.profiles
    ]

    assert missing == []


def test_draco_runner_profile_groups_exist_when_example_config_is_loaded() -> None:
    cfg = GatewayConfig.load("opensquilla.toml.example")
    missing = [
        group
        for group, spec in GROUP_SPECS.items()
        if spec["kind"] == "profile" and spec["profile"] not in cfg.llm_ensemble.profiles
    ]

    assert missing == []


def test_draco_runner_profile_provider_records_candidates_for_results() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G3",
        profile="g3_standard",
        dry_run=False,
    )

    assert provider.record_candidates is True
    assert provider.shuffle_candidates is False


def test_draco_runner_profile_provider_enables_proposer_tools_when_requested() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G3",
        profile="g3_standard",
        dry_run=False,
        enable_proposer_tools=True,
    )

    assert provider.proposer_tools is True


def test_draco_runner_generation_thinking_policy_overrides_profile_members() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )
    policy = generation_thinking_policy(Namespace(generation_thinking="off"))

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G3",
        profile="g3_standard",
        dry_run=False,
        generation_policy=policy,
    )

    assert provider.record_candidates is True
    assert provider.shuffle_candidates is False
    assert provider.proposer_timeout_seconds == 120.0
    assert provider.aggregator_timeout_seconds == 300.0
    assert [member.thinking for member in provider.proposers] == ["off", "off", "off"]
    assert provider.aggregator.thinking == "off"


def test_draco_runner_profile_timeouts_expand_with_requested_timeout() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G3",
        profile="g3_standard",
        dry_run=False,
        requested_timeout=900.0,
    )

    assert provider.proposer_timeout_seconds == pytest.approx(232.5)
    assert provider.aggregator_timeout_seconds == pytest.approx(637.5)


def test_draco_runner_generation_policy_overrides_profile_member_temperature() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )
    profile = cfg.llm_ensemble.profiles["g3_standard"]
    cfg.llm_ensemble.profiles["g3_standard"] = profile.model_copy(
        update={
            "proposers": [
                proposer.model_copy(update={"temperature": 0.7})
                for proposer in profile.proposers
            ],
            "aggregator": profile.aggregator.model_copy(update={"temperature": 0.7}),
        }
    )
    policy = generation_thinking_policy(Namespace(generation_thinking="profile"))

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G3",
        profile="g3_standard",
        dry_run=False,
        generation_policy=policy,
    )

    assert [member.temperature for member in provider.proposers] == [0.0, 0.0, 0.0]
    assert provider.aggregator.temperature == 0.0


def test_draco_runner_g15_profile_configures_topk_prefilter() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G15",
        profile="g15_g8_top3_prefilter",
        dry_run=False,
        generation_policy=generation_thinking_policy(Namespace(generation_thinking="high")),
    )

    assert provider.candidate_prefilter_top_k == 3
    assert provider.candidate_scorer is not None
    assert (
        provider.candidate_scorer.provider_config.model
        == "google/gemini-3-flash-preview"
    )
    assert provider.candidate_scorer.temperature == 0.0
    assert provider.candidate_scorer.thinking == "high"


def test_draco_runner_g16_preserves_profile_sampling_temperature() -> None:
    cfg = GatewayConfig()
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_profile_provider(
        config=cfg,
        inherited=inherited,
        group="G16",
        profile="g16_sampled_cheap_proposers",
        dry_run=False,
        generation_policy=generation_thinking_policy(Namespace(generation_thinking="high")),
    )

    assert [member.provider_config.model for member in provider.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert [member.k for member in provider.proposers] == [1, 1, 2, 2]
    assert [member.temperature for member in provider.proposers] == [
        0.0,
        0.0,
        0.3,
        0.3,
    ]
    assert [member.thinking for member in provider.proposers] == [
        "high",
        "high",
        "high",
        "high",
    ]
    assert provider.aggregator.provider_config.model == "z-ai/glm-5.2"
    assert provider.aggregator.temperature == 0.0


@pytest.mark.asyncio
async def test_draco_runner_collect_run_passes_tools_to_provider() -> None:
    provider = _ToolCaptureProvider()
    tool = ToolDefinition(
        name="openrouter:web_search",
        description="Search the web.",
        input_schema=ToolInputSchema(),
        provider_tool={"type": "openrouter:web_search"},
    )

    run = await collect_run(provider, "research this", timeout=10.0, tools=[tool])

    assert run.final_text == "ok"
    assert provider.seen_tools == [tool]


@pytest.mark.asyncio
async def test_draco_runner_collect_agent_run_executes_local_web_tool_loop() -> None:
    provider = _AgentToolLoopProvider()
    args = build_parser().parse_args([
        "--input",
        "draco.jsonl",
        "--groups",
        "G3",
        "--tool-mode",
        "local_web_tools",
        "--contamination-blocked-domains",
        "huggingface.co",
    ])
    policy = benchmark_tool_policy(args)

    run = await collect_agent_run(
        provider,
        "research this",
        timeout=10.0,
        config=generation_chat_config(
            generation_thinking_policy(Namespace(generation_thinking="off"))
        ),
        tools=benchmark_tools_for_policy(policy),
        tool_policy=policy,
        task_id="task-1",
        group="B0",
        max_iterations=4,
    )

    summary = run_result_summary(run)

    assert provider.calls == 2
    assert run.final_text == "final after tool"
    assert run.error == ""
    assert run.tool_call_count == 1
    assert run.done is not None
    assert run.done.provider_usage["agent_iterations"] == 2
    assert summary["llm_request_count"] == 2
    assert any(
        event.get("kind") == "tool_result" and event.get("tool_name") == "web_fetch"
        for event in run.trace_events
    )


def test_draco_runner_generation_chat_config_uses_explicit_high_by_default() -> None:
    policy = generation_thinking_policy(Namespace(generation_thinking="high"))

    config = generation_chat_config(policy)

    assert config is not None
    assert config.thinking is True
    assert str(config.thinking_level) == "high"
    assert config.thinking_budget_tokens == 20_000
    assert config.temperature == 0.0


def test_draco_runner_compact_generation_config_marks_profile_thinking() -> None:
    policy = generation_thinking_policy(Namespace(generation_thinking="profile"))
    config = generation_chat_config(policy)

    compact = compact_chat_config(config, policy)

    assert compact["thinking"] == "profile_default"
    assert compact["temperature"] == 0.0


def test_draco_runner_expands_outer_timeout_for_profile_budget() -> None:
    cfg = GatewayConfig()

    assert group_timeout_seconds(requested_timeout=360.0, config=cfg, group="G3") == 450.0
    assert group_timeout_seconds(requested_timeout=360.0, config=cfg, group="G6") == 450.0
    assert group_timeout_seconds(requested_timeout=600.0, config=cfg, group="G6") == 600.0
    assert group_timeout_seconds(requested_timeout=900.0, config=cfg, group="G3") == 900.0
    assert group_timeout_seconds(requested_timeout=360.0, config=cfg, group="B2") == 360.0


def test_draco_summary_compares_avg_quality_and_cost_pct_against_baselines() -> None:
    rows = [
        {
            "task_id": "task-1",
            "group": "B0",
            "latency_ms": 100,
            "quality_total": 40.0,
            "judge": {"pass_rate": 40.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.10, "input_tokens": 10, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-1",
            "group": "B1",
            "latency_ms": 200,
            "quality_total": 30.0,
            "judge": {"pass_rate": 30.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.20, "input_tokens": 12, "output_tokens": 6},
            "error": "",
        },
        {
            "task_id": "task-1",
            "group": "G2",
            "latency_ms": 300,
            "quality_total": 45.0,
            "judge": {"pass_rate": 50.0, "judge_error_count": 0},
            "stream_tool_call_count": 1,
            "trajectory_steps": 8,
            "llm_request_count": 4,
            "usage": {
                "billed_cost": 0.05,
                "input_tokens": 14,
                "output_tokens": 7,
                "reasoning_tokens": 3,
                "provider_usage": {
                    "server_tool_use": {
                        "web_search_requests": 2,
                    },
                },
                "model_usage_breakdown": [
                    {
                        "provider_usage": {
                            "server_tool_use": {
                                "web_search_requests": 2,
                            },
                        },
                    },
                    {
                        "provider_usage": {
                            "server_tool_use": {
                                "web_fetch_requests": 1,
                            },
                        },
                    }
                ],
            },
            "error": "",
        },
    ]

    summary = summarize(rows)
    g2 = summary["groups"]["G2"]

    assert g2["avg_quality_scored"] == pytest.approx(45.0)
    assert g2["avg_quality_pct_delta_vs_b0"] == pytest.approx(12.5)
    assert g2["avg_cost_pct_delta_vs_b0"] == pytest.approx(-50.0)
    assert g2["avg_quality_pct_delta_vs_b1"] == pytest.approx(50.0)
    assert g2["avg_cost_pct_delta_vs_b1"] == pytest.approx(-75.0)
    assert g2["avg_visible_tokens"] == pytest.approx(21.0)
    assert g2["avg_reasoning_tokens"] == pytest.approx(3.0)
    assert g2["avg_total_tokens"] == pytest.approx(24.0)
    assert g2["avg_stream_tool_calls"] == pytest.approx(1.0)
    assert g2["avg_server_tool_calls"] == pytest.approx(3.0)
    assert g2["avg_tool_calls"] == pytest.approx(4.0)
    assert g2["total_tool_calls"] == 4
    assert g2["tool_call_rate_pct"] == pytest.approx(100.0)
    assert g2["avg_trajectory_steps"] == pytest.approx(8.0)
    assert g2["avg_llm_requests"] == pytest.approx(4.0)
    assert g2["total_llm_requests"] == 4
    markdown = render_markdown(summary, Path("reports/draco/draco_ensemble_test.jsonl"))
    assert "Win vs" not in markdown
    assert "AvgQ % vs B0" in markdown
    assert "AvgQ Scored" in markdown
    assert "| Group | Rows | Done | Scored |" not in markdown
    assert "Avg Reason" in markdown
    assert "Avg Tools" in markdown
    assert "Avg LLM Req" in markdown
    assert "+12.50%" in markdown
    assert "-50.00%" in markdown


def test_draco_summary_uses_generation_attempt_cost_and_tokens() -> None:
    rows = [
        {
            "task_id": "task-1",
            "group": "G3",
            "latency_ms": 300,
            "quality_total": 50.0,
            "judge": {"pass_rate": 50.0, "judge_error_count": 0},
            "usage": {
                "billed_cost": 0.20,
                "input_tokens": 20,
                "output_tokens": 10,
                "reasoning_tokens": 2,
            },
            "execution": {
                "generation_attempts": [
                    {
                        "attempt": 1,
                        "run": {
                            "usage": {
                                "billed_cost": 0.10,
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "reasoning_tokens": 1,
                            }
                        },
                    },
                    {
                        "attempt": 2,
                        "run": {
                            "usage": {
                                "billed_cost": 0.20,
                                "input_tokens": 20,
                                "output_tokens": 10,
                                "reasoning_tokens": 2,
                            }
                        },
                    },
                ],
            },
            "error": "",
        },
    ]

    group = summarize(rows)["groups"]["G3"]

    assert group["avg_cost_usd"] == pytest.approx(0.30)
    assert group["avg_visible_tokens"] == pytest.approx(45.0)
    assert group["avg_reasoning_tokens"] == pytest.approx(3.0)
    assert group["avg_total_tokens"] == pytest.approx(48.0)


def test_draco_summary_counts_unscored_rows_as_zero_quality() -> None:
    rows = [
        {
            "task_id": "task-1",
            "group": "B0",
            "latency_ms": 100,
            "quality_total": 40.0,
            "judge": {"pass_rate": 40.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.10, "input_tokens": 10, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-2",
            "group": "B0",
            "latency_ms": 110,
            "quality_total": 40.0,
            "judge": {"pass_rate": 40.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.10, "input_tokens": 10, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-1",
            "group": "G2",
            "latency_ms": 200,
            "quality_total": 50.0,
            "judge": {"pass_rate": 50.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.05, "input_tokens": 20, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-2",
            "group": "G2",
            "latency_ms": 210,
            "quality_total": None,
            "judge": {"judge_error_count": 1},
            "usage": {"billed_cost": 0.01, "input_tokens": 6, "output_tokens": 1},
            "error": "",
        },
    ]

    summary = summarize(rows)
    g2 = summary["groups"]["G2"]

    assert g2["rows"] == 2
    assert g2["completed"] == 2
    assert g2["avg_quality"] == 25.0
    assert g2["avg_quality_scored"] == 25.0
    assert g2["avg_quality_pct_delta_vs_b0"] == pytest.approx(-37.5)
    assert g2["avg_cost_usd"] == pytest.approx(0.03)
    assert g2["avg_cost_completed_usd"] == pytest.approx(0.03)


def test_draco_summary_avg_quality_scored_uses_only_done_rows() -> None:
    rows = [
        {
            "task_id": "task-1",
            "group": "G3",
            "latency_ms": 100,
            "quality_total": 80.0,
            "judge": {"pass_rate": 80.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.10, "input_tokens": 10, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-2",
            "group": "G3",
            "latency_ms": 200,
            "quality_total": 10.0,
            "judge": {"pass_rate": 10.0, "judge_error_count": 0},
            "usage": {"billed_cost": 0.05, "input_tokens": 4, "output_tokens": 1},
            "error": "TimeoutError: run timed out after 900s",
        },
    ]

    group = summarize(rows)["groups"]["G3"]

    assert group["rows"] == 2
    assert group["completed"] == 1
    assert group["avg_quality"] == pytest.approx(40.0)
    assert group["avg_quality_scored"] == pytest.approx(80.0)


def test_draco_summary_leaves_quality_blank_when_no_judge_ran() -> None:
    rows = [
        {
            "task_id": "task-1",
            "group": "B0",
            "latency_ms": 100,
            "quality_total": None,
            "judge": None,
            "usage": {"billed_cost": 0.10, "input_tokens": 10, "output_tokens": 5},
            "error": "",
        },
        {
            "task_id": "task-1",
            "group": "G2",
            "latency_ms": 200,
            "quality_total": None,
            "judge": None,
            "usage": {"billed_cost": 0.05, "input_tokens": 20, "output_tokens": 5},
            "error": "",
        },
    ]

    summary = summarize(rows)

    assert summary["groups"]["B0"]["avg_quality"] is None
    assert summary["groups"]["G2"]["avg_quality"] is None
    assert summary["groups"]["G2"]["avg_quality_pct_delta_vs_b0"] is None


def test_load_tasks_accepts_official_draco_problem_and_answer(tmp_path: Path) -> None:
    input_path = tmp_path / "draco.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "task_id": "task-1",
                "problem": "Research this.",
                "answer": json.dumps(
                    {
                        "id": "rubric-1",
                        "sections": [
                            {
                                "id": "factual-accuracy",
                                "title": "Factual Accuracy",
                                "criteria": [
                                    {
                                        "id": "fact-1",
                                        "weight": 10,
                                        "requirement": "States the key fact",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    [task] = load_tasks(input_path)

    assert task["id"] == "task-1"
    assert task["prompt"] == "Research this."
    assert task["rubric"]["sections"][0]["criteria"][0]["id"] == "fact-1"


@pytest.mark.asyncio
async def test_judge_text_uses_draco_criterion_judgments() -> None:
    task = {
        "id": "task-1",
        "prompt": "Research this.",
        "rubric": {
            "id": "rubric-1",
            "sections": [
                {
                    "id": "factual-accuracy",
                    "title": "Factual Accuracy",
                    "criteria": [
                        {"id": "pos", "weight": 10, "requirement": "Contains fact"},
                        {"id": "neg", "weight": -5, "requirement": "Contains error"},
                    ],
                }
            ],
        },
    }

    result = await judge_text(
        judge_provider=_CriterionJudgeProvider(),
        task=task,
        answer="A researched answer.",
        dry_run=False,
    )

    assert result is not None
    assert result["mode"] == "draco_criterion_judgments"
    assert result["normalized_score"] == 100.0
    assert result["pass_rate"] == 100.0
    assert result["criteria_count"] == 2
    assert [item["verdict"] for item in result["criterion_judgments"]] == ["MET", "UNMET"]


@pytest.mark.asyncio
async def test_judge_text_retries_invalid_criterion_verdict_up_to_three() -> None:
    provider = _FlakyCriterionJudgeProvider(failures_before_success=2)
    task = {
        "id": "task-1",
        "prompt": "Research this.",
        "rubric": {
            "id": "rubric-1",
            "sections": [
                {
                    "id": "factual-accuracy",
                    "title": "Factual Accuracy",
                    "criteria": [
                        {"id": "pos", "weight": 10, "requirement": "Contains fact"},
                    ],
                }
            ],
        },
    }

    result = await judge_text(
        judge_provider=provider,
        task=task,
        answer="A researched answer.",
        dry_run=False,
        judge_max_attempts=9,
    )

    assert provider.calls == 3
    assert result is not None
    assert result["score_status"] == "complete"
    assert result["judge_error_count"] == 0
    [judgment] = result["criterion_judgments"]
    assert judgment["met"] is True
    assert judgment["judge_attempt_count"] == 3
    assert len(judgment["judge_attempts"]) == 3
    assert judgment["judge_attempts"][0]["met"] is None


def test_invalid_criterion_judgment_marks_score_partial() -> None:
    result = score_criterion_judgments(
        rubric_id="rubric-1",
        judge_model="judge-test",
        judge_repeats=1,
        judgments=[
            {"id": "pos", "weight": 10, "met": True},
            {
                "id": "neg",
                "weight": -5,
                "met": None,
                "error": "judge_verdict_parse_failed",
            },
        ],
    )

    assert result["score_status"] == "partial"
    assert result["invalid_criteria_count"] == 1
    assert result["pass_rate"] is None
    assert result["total"] is None
    assert result["valid_pass_rate"] == 100.0
    assert quality_total(result) is None


def test_quality_total_normalizes_legacy_dimension_scores() -> None:
    assert quality_total({"mode": "legacy_dimension_score", "total": 20}) == 100.0
    assert quality_total({"mode": "legacy_dimension_score", "total": 10}) == 50.0
    assert (
        quality_total(
            {
                "mode": "legacy_dimension_score",
                "scores": {
                    "accuracy": 5,
                    "completeness": 4,
                    "objectivity": 3,
                    "citation": 2,
                },
            }
        )
        == 70.0
    )


@pytest.mark.asyncio
async def test_run_one_skips_judge_when_generation_is_not_done(monkeypatch) -> None:  # noqa: ANN001
    async def _failed_generation(*args, **kwargs):  # noqa: ANN002, ANN003
        return (
            RunResult(final_text="partial answer", done=None, error=""),
            [],
            0,
        )

    monkeypatch.setattr(
        "scripts.run_draco_ensemble.collect_generation_with_retries",
        _failed_generation,
    )
    judge_provider = _CountingJudgeProvider()

    row = await run_one(
        task={"id": "task-1", "prompt": "Research this."},
        group="B0",
        config=GatewayConfig(),
        inherited=ProviderConfig(
            provider="openrouter",
            model="anthropic/claude-opus-4.8",
            api_key="sk-test",
            base_url="https://openrouter.ai/api",
        ),
        dry_run=False,
        judge_provider=judge_provider,
        judge_candidates=True,
        judge_repeats=1,
        judge_concurrency=1,
        judge_max_attempts=3,
        timeout=10.0,
        tool_policy={"tool_mode": "provider_only", "tools_enabled": False},
        generation_policy=generation_thinking_policy(Namespace(generation_thinking="high")),
        generation_max_attempts=1,
        generation_retry_backoff=0.0,
    )

    assert judge_provider.calls == 0
    assert row["error"] == "generation_missing_done"
    assert row["judge"] is None
    assert row["candidate_judges"] == []
    assert row["quality_total"] is None
    assert row["execution"]["judge_skipped_reason"] == "run_not_done"


@pytest.mark.asyncio
async def test_collect_run_enforces_outer_timeout() -> None:
    result = await collect_run(
        _SlowProvider(),
        "slow task",
        timeout=0.01,
    )

    assert result.final_text == ""
    assert "TimeoutError" in result.error
    assert result.trace_events[-1]["kind"] == "timeout"


@pytest.mark.asyncio
async def test_collect_run_preserves_error_diagnostic_done() -> None:
    result = await collect_run(
        _DiagnosticErrorProvider(),
        "diagnostic task",
        timeout=1.0,
    )

    assert result.error == "boom"
    assert result.done is not None
    assert result.done.model == "diagnostic-model"
    assert result.done.billed_cost == 0.12
    assert result.done.ensemble_trace == {"kept": True}
    assert [event["kind"] for event in result.trace_events] == [
        "diagnostic_done",
        "error",
    ]


@pytest.mark.asyncio
async def test_collect_generation_with_retries_recovers_from_empty_output() -> None:
    provider = _EmptyThenSuccessProvider()

    result, attempts, selected_attempt = await collect_generation_with_retries(
        provider,
        "task",
        timeout=1.0,
        max_attempts=3,
    )

    assert provider.calls == 2
    assert result.final_text == "recovered"
    assert result.error == ""
    assert selected_attempt == 2
    assert [attempt["retry_reason"] for attempt in attempts] == [
        "empty_generation_output",
        "",
    ]
    assert attempts[0]["will_retry"] is True
    assert attempts[0]["retry_backoff_s"] == 0.0
    assert attempts[1]["will_retry"] is False


@pytest.mark.asyncio
async def test_collect_generation_with_retries_marks_all_empty_output_as_failure() -> None:
    provider = _AlwaysEmptyProvider()

    result, attempts, selected_attempt = await collect_generation_with_retries(
        provider,
        "task",
        timeout=1.0,
        max_attempts=3,
    )

    assert provider.calls == 3
    assert selected_attempt == 3
    assert result.final_text == ""
    assert result.done is not None
    assert result.error == "empty_generation_output"
    assert all(
        attempt["retry_reason"] == "empty_generation_output"
        for attempt in attempts
    )
    assert all(
        attempt["run"]["error"] == "empty_generation_output"
        for attempt in attempts
    )


@pytest.mark.asyncio
async def test_collect_generation_with_retries_recovers_from_error() -> None:
    provider = _ErrorThenSuccessProvider(failures_before_success=1)

    result, attempts, selected_attempt = await collect_generation_with_retries(
        provider,
        "task",
        timeout=1.0,
        max_attempts=3,
    )

    assert provider.calls == 2
    assert result.final_text == "recovered"
    assert result.error == ""
    assert selected_attempt == 2
    assert [attempt["retry_reason"] for attempt in attempts] == ["boom", ""]


@pytest.mark.asyncio
async def test_collect_generation_with_retries_caps_attempts_at_three() -> None:
    provider = _ErrorThenSuccessProvider(failures_before_success=5)

    result, attempts, selected_attempt = await collect_generation_with_retries(
        provider,
        "task",
        timeout=1.0,
        max_attempts=9,
    )

    assert provider.calls == 3
    assert len(attempts) == 3
    assert selected_attempt == 1
    assert result.final_text == "partial"
    assert result.error == "boom"
    assert all(attempt["retry_reason"] == "boom" for attempt in attempts)


@pytest.mark.asyncio
async def test_collect_generation_with_retries_marks_missing_done_as_failure() -> None:
    provider = _MissingDoneProvider()

    result, attempts, selected_attempt = await collect_generation_with_retries(
        provider,
        "task",
        timeout=1.0,
        max_attempts=3,
    )

    assert provider.calls == 3
    assert selected_attempt == 1
    assert result.final_text == "partial answer"
    assert result.done is None
    assert result.error == "generation_missing_done"
    assert all(
        attempt["retry_reason"] == "generation_missing_done"
        for attempt in attempts
    )
    assert all(
        attempt["run"]["error"] == "generation_missing_done"
        for attempt in attempts
    )
