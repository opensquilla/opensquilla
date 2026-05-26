"""Compare OpenSquilla meta-skills against an OpenClaw gateway.

The script defines seven fixed benchmark cases for the high-value meta-skill
scenarios and can run them end-to-end through both gateways.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_DIR = Path(
    os.environ.get("OPENSQUILLA_COMPARE_REPORT_DIR", ".reports/meta-skill-comparison")
)


@dataclass(frozen=True)
class ComparisonCase:
    case_id: str
    skill_name: str
    prompt: str
    expected_advantage: str
    optimization_if_not_better: str


@dataclass(frozen=True)
class ResponseScore:
    total: int
    dimensions: dict[str, int]
    notes: list[str]


@dataclass
class EndpointResult:
    endpoint: str
    case_id: str
    ok: bool
    elapsed_s: float
    response_text: str
    score: dict[str, Any]
    error: str | None = None
    session_key: str | None = None
    model: str | None = None
    provider: str | None = None
    event_count: int = 0


COMPARISON_CASES: list[ComparisonCase] = [
    ComparisonCase(
        case_id="web_research_report",
        skill_name="meta-web-research-to-report",
        prompt=(
            "I'm the CTO of a small product team and need a concise research report "
            "before our planning meeting. Should we adopt local-first AI coding "
            "assistants in 2026? Please include the assumptions you're making, "
            "5 key findings, practical risks, and a source list. Keep it compact "
            "enough to paste into a decision memo, but make it artifact-ready."
        ),
        expected_advantage=(
            "OpenSquilla should infer report preferences, search/curate sources, "
            "draft with citations, and run a readiness gate."
        ),
        optimization_if_not_better=(
            "Tighten source-quality gating, require explicit source-to-claim mapping, "
            "and add a final report checklist before export."
        ),
    ),
    ComparisonCase(
        case_id="paper_write",
        skill_name="meta-paper-write",
        prompt=(
            "I'm preparing to draft a paper on meta-skill orchestration for AI "
            "agents, but I only need the first pass today. Please produce an "
            "academic manuscript plan and a compact LaTeX-ready draft skeleton. "
            "Include abstract, introduction, method, evaluation design, expected "
            "results, limitations, and at least 20 reference placeholders. Also "
            "explain how the full version would reach 10+ pages."
        ),
        expected_advantage=(
            "OpenSquilla should preserve paper structure, citation planning, length "
            "gate, citation integrity gate, and LaTeX sanitization."
        ),
        optimization_if_not_better=(
            "Make the paper workflow expose a short benchmark mode while keeping "
            "the full 10-page gate for production paper requests."
        ),
    ),
    ComparisonCase(
        case_id="pdf_intelligence",
        skill_name="meta-pdf-intelligence",
        prompt=(
            "I don't have the PDF upload handy, but please treat this as a PDF "
            "intelligence task from `agent-observability.pdf`: page 3 says "
            "'Trace spans identify tool calls, model routing, and error recovery.' "
            "Page 4 says 'missing provenance makes evaluation unreliable.' Return "
            "a traceable digest with page evidence, key facts, open questions, "
            "and a reusable memory index."
        ),
        expected_advantage=(
            "OpenSquilla should classify the PDF task, preserve document/page "
            "references, synthesize traceably, and create a memory index."
        ),
        optimization_if_not_better=(
            "Add an inline-excerpt fallback path for PDF intelligence when the user "
            "provides page excerpts instead of a file upload."
        ),
    ),
    ComparisonCase(
        case_id="stack_trace_investigator",
        skill_name="meta-stack-trace-investigator",
        prompt=(
            "Can you investigate this stack trace from our agent runtime?\n"
            "Traceback (most recent call last):\n"
            "  File \"src/agent/runtime.py\", line 88, in run_step\n"
            "    payload = parse_tool_result(raw)\n"
            "  File \"src/agent/tools.py\", line 41, in parse_tool_result\n"
            "    return json.loads(raw)['result']\n"
            "KeyError: 'result'\n\n"
            "I need root-cause hypotheses, repo search targets, related checks, "
            "and exact verification commands I can run next."
        ),
        expected_advantage=(
            "OpenSquilla should classify the runtime, parse frames, search repo "
            "symbols, inspect history/issues, and synthesize verification commands."
        ),
        optimization_if_not_better=(
            "Improve degraded behavior when repo symbols are absent by producing "
            "language-specific reproduction snippets and patch targets."
        ),
    ),
    ComparisonCase(
        case_id="travel_planner",
        skill_name="meta-travel-planner",
        prompt=(
            "My partner and I are visiting Tokyo for the first time in late June. "
            "Could you build a 3-day travel plan with a balanced pace? We care "
            "about food, transit-friendly neighborhood grouping, rain backups, "
            "and a moderate budget. Please include your assumptions, a daily "
            "schedule, weather-aware risks, a few variants, and budget notes."
        ),
        expected_advantage=(
            "OpenSquilla should infer trip preferences, check weather/search results, "
            "extract constraints, and append variants plus bad-weather backup."
        ),
        optimization_if_not_better=(
            "Improve constraint extraction for dates, opening hours, neighborhood "
            "grouping, and budget notes before itinerary drafting."
        ),
    ),
    ComparisonCase(
        case_id="meta_skill_creator",
        skill_name="meta-skill-creator",
        prompt=(
            "I want to compose a meta-skill for our analyst workflow. It should "
            "combine web research, PDF intelligence, and a final docx export into "
            "a reusable due-diligence brief workflow. Please include triggers, "
            "inputs, the step graph, collision risks, gates, and a preview of the "
            "SKILL.md."
        ),
        expected_advantage=(
            "OpenSquilla should distinguish meta-skill vs normal skill, harvest "
            "patterns, assemble a candidate, run collision/risk/lint/smoke gates, "
            "and show a proposal preview."
        ),
        optimization_if_not_better=(
            "Expose clearer preview sections and make collision/risk findings more "
            "visible when the generated skill is only a draft."
        ),
    ),
    ComparisonCase(
        case_id="migration_assistant",
        skill_name="meta-migration-assistant",
        prompt=(
            "We're planning to migrate a small frontend package from CommonJS "
            "to native ESM next sprint. Please give me a practical migration "
            "checklist with breaking changes, grep patterns for files likely "
            "affected, validation commands, and rollout risks. Assume this is "
            "for the current repo, but don't make up files you cannot verify."
        ),
        expected_advantage=(
            "OpenSquilla should classify the migration kind, route to an "
            "authoritative guide source, optionally inspect current repo diff "
            "context, and produce a concrete validation checklist."
        ),
        optimization_if_not_better=(
            "Strengthen migration-kind classification, make repo-context use "
            "more selective, and require explicit source/command evidence in "
            "the final checklist."
        ),
    ),
]


def score_response(text: str) -> ResponseScore:
    lowered = text.lower()
    dimensions = {
        "structure": min(
            5,
            _count_matches(text, [r"^#", r"^\s*[-*]\s+", r"^\s*\d+[.)]\s+", r"\|.+\|"])
            + (1 if len(text) > 800 else 0),
        ),
        "evidence": min(
            5,
            _count_matches(
                text,
                [
                    r"https?://",
                    r"\[[0-9]+\]",
                    r"\bpage\s+\d+\b",
                    r"\bsource\b",
                    r"\bcitation\b",
                    r"\bfile\s+\"?",
                ],
            ),
        ),
        "artifact_readiness": min(
            5,
            _count_words(
                lowered,
                [
                    "artifact",
                    "docx",
                    "pptx",
                    "latex",
                    "bib",
                    "html",
                    "slide",
                    "report",
                    "manuscript",
                    "migration",
                    "checklist",
                ],
            ),
        ),
        "actionability": min(
            5,
            _count_words(
                lowered,
                ["command", "verify", "check", "next step", "schedule", "itinerary", "risk"],
            ),
        ),
        "constraint_handling": min(
            5,
            _count_words(
                lowered,
                ["assumption", "constraint", "budget", "audience", "limitation", "preference"],
            ),
        ),
        "traceability": min(
            5,
            _count_words(
                lowered,
                ["evidence", "source", "page", "reference", "trace", "reproduce", "gate"],
            ),
        ),
    }
    notes = [
        name
        for name, value in dimensions.items()
        if value <= 1
    ]
    return ResponseScore(total=sum(dimensions.values()), dimensions=dimensions, notes=notes)


def _count_matches(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.I | re.M))


def _count_words(text: str, words: list[str]) -> int:
    return sum(1 for word in words if word in text)


def extract_text_from_events(events: list[dict[str, Any]]) -> str:
    candidates: list[str] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = _content_to_text(message.get("content"))
            if text:
                candidates.append(text)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            candidates.append(data["text"])
        for key in ("text", "delta", "content", "final", "response"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, str) and value.strip():
                candidates.append(value)
    if not candidates:
        return ""
    return max(candidates, key=len).strip()


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


class OpenSquillaRunner:
    def __init__(self, url: str, token: str | None, elevated: str | None = None) -> None:
        self.url = url
        self.token = token
        self.elevated = elevated

    async def run(self, case: ComparisonCase, timeout_s: float) -> EndpointResult:
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self._run(case), timeout=timeout_s)
            result.elapsed_s = round(time.monotonic() - start, 2)
            return result
        except SystemExit as exc:
            return _error_result("opensquilla", case.case_id, start, exc)
        except Exception as exc:
            return _error_result("opensquilla", case.case_id, start, exc)

    async def _run(self, case: ComparisonCase) -> EndpointResult:
        from opensquilla.cli.gateway_client import GatewayClient

        client = GatewayClient()
        events: list[dict[str, Any]] = []
        session_key: str | None = None
        try:
            await client.connect(self.url, token=self.token)
            session_key = await client.create_session(
                agent_id="main",
                display_name=f"meta compare {case.case_id}",
            )
            async for event in client.send_message(
                session_key,
                case.prompt,
                elevated=self.elevated,
            ):
                events.append(event)
            text = extract_text_from_events(events)
            score = score_response(text)
            provider, model = _provider_model_from_events(events)
            return EndpointResult(
                endpoint="opensquilla",
                case_id=case.case_id,
                ok=bool(text),
                elapsed_s=0.0,
                response_text=text,
                score=asdict(score),
                session_key=session_key,
                provider=provider,
                model=model,
                event_count=len(events),
            )
        finally:
            await client.close()


class OpenClawRunner:
    def __init__(self, url: str, token: str, idle_timeout_s: float = 90.0) -> None:
        self.url = url
        self.token = token
        self.idle_timeout_s = idle_timeout_s

    async def run(self, case: ComparisonCase, timeout_s: float) -> EndpointResult:
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self._run(case), timeout=timeout_s)
            result.elapsed_s = round(time.monotonic() - start, 2)
            return result
        except Exception as exc:
            return _error_result("openclaw", case.case_id, start, exc)

    async def _run(self, case: ComparisonCase) -> EndpointResult:
        import websockets

        control_events: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        async with websockets.connect(self.url, ping_interval=None) as ws:
            first = json.loads(await ws.recv())
            if first.get("event") != "connect.challenge":
                raise RuntimeError(f"unexpected OpenClaw handshake: {first}")
            await self._call(
                ws,
                "connect",
                {
                    "minProtocol": 1,
                    "maxProtocol": 3,
                    "role": "operator",
                    "scopes": ["operator.admin"],
                    "auth": {"token": self.token},
                    "client": {
                        "id": "openclaw-tui",
                        "mode": "cli",
                        "version": "0",
                        "platform": "linux",
                    },
                },
                control_events,
            )
            created = await self._call(
                ws,
                "sessions.create",
                {"agentId": "main"},
                control_events,
            )
            session_key = str(created["key"])
            await self._call(
                ws,
                "sessions.messages.subscribe",
                {"key": session_key},
                control_events,
            )
            await self._call(
                ws,
                "sessions.send",
                {"key": session_key, "message": case.prompt},
                events,
            )
            await self._read_openclaw_stream(ws, events)
        text = extract_text_from_events(events)
        score = score_response(text)
        provider, model = _provider_model_from_events(events)
        return EndpointResult(
            endpoint="openclaw",
            case_id=case.case_id,
            ok=bool(text),
            elapsed_s=0.0,
            response_text=text,
            score=asdict(score),
            session_key=session_key,
            provider=provider,
            model=model,
            event_count=len(events),
        )

    async def _call(
        self,
        ws: Any,
        method: str,
        params: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        await ws.send(
            json.dumps({"type": "req", "id": req_id, "method": method, "params": params})
        )
        while True:
            frame = json.loads(await ws.recv())
            if frame.get("type") == "event":
                events.append(frame)
                continue
            if frame.get("type") == "res" and frame.get("id") == req_id:
                if not frame.get("ok"):
                    raise RuntimeError(f"{method} failed: {frame.get('error')}")
                payload = frame.get("payload")
                return payload if isinstance(payload, dict) else {}

    async def _read_openclaw_stream(self, ws: Any, events: list[dict[str, Any]]) -> None:
        deadline = time.monotonic() + self.idle_timeout_s
        while True:
            timeout = max(0.1, deadline - time.monotonic())
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            except TimeoutError:
                return
            if frame.get("type") != "event":
                continue
            events.append(frame)
            if frame.get("event") == "chat":
                payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
                if payload.get("state") == "final":
                    return
            if frame.get("event") == "session.event.error":
                return


def _provider_model_from_events(events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    for event in reversed(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, dict):
            provider = message.get("provider") or message.get("modelProvider")
            model = message.get("model")
            if provider or model:
                return (
                    str(provider) if provider else None,
                    str(model) if model else None,
                )
        provider = payload.get("provider") if isinstance(payload, dict) else None
        model = payload.get("model") if isinstance(payload, dict) else None
        if provider or model:
            return (str(provider) if provider else None, str(model) if model else None)
    return None, None


def _error_result(endpoint: str, case_id: str, start: float, exc: Exception) -> EndpointResult:
    return EndpointResult(
        endpoint=endpoint,
        case_id=case_id,
        ok=False,
        elapsed_s=round(time.monotonic() - start, 2),
        response_text="",
        score=asdict(score_response("")),
        error=f"{type(exc).__name__}: {exc}",
    )


def read_openclaw_token(config_path: Path) -> str:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    token = data.get("gateway", {}).get("auth", {}).get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"OpenClaw token missing in {config_path}")
    return token


def read_opensquilla_token() -> str | None:
    for env_name in ("OPENSQUILLA_GATEWAY_TOKEN", "OPENSQUILLA_TOKEN"):
        value = os.environ.get(env_name)
        if value:
            return value
    token_file = os.environ.get("OPENSQUILLA_GATEWAY_TOKEN_FILE")
    if token_file:
        path = Path(token_file)
        match = re.search(r'^TOKEN\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    return None


async def run_live(args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = _select_cases(args.case)
    if not args.openclaw_config:
        raise SystemExit("Pass --openclaw-config or set OPENCLAW_CONFIG.")
    openclaw_token = read_openclaw_token(Path(args.openclaw_config))
    opensquilla = OpenSquillaRunner(
        args.opensquilla_url,
        args.opensquilla_token,
        elevated=args.opensquilla_elevated,
    )
    openclaw = OpenClawRunner(args.openclaw_url, openclaw_token, args.openclaw_idle_timeout)

    rows: list[dict[str, Any]] = []
    for case in selected:
        print(f"running {case.case_id} ...", flush=True)
        sq_result, claw_result = await asyncio.gather(
            opensquilla.run(case, args.timeout),
            openclaw.run(case, args.timeout),
        )
        row = compare_results(case, sq_result, claw_result)
        rows.append(row)
        print(
            f"{case.case_id}: opensquilla={sq_result.score['total']} "
            f"openclaw={claw_result.score['total']} winner={row['winner']}",
            flush=True,
        )
    write_reports(rows)
    return rows


def compare_results(
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
) -> dict[str, Any]:
    sq_total = int(opensquilla.score["total"])
    claw_total = int(openclaw.score["total"])
    if not opensquilla.ok and openclaw.ok:
        winner = "openclaw"
    elif opensquilla.ok and not openclaw.ok:
        winner = "opensquilla"
    elif sq_total > claw_total:
        winner = "opensquilla"
    elif claw_total > sq_total:
        winner = "openclaw"
    else:
        winner = "tie"
    return {
        "case": asdict(case),
        "opensquilla": asdict(opensquilla),
        "openclaw": asdict(openclaw),
        "winner": winner,
        "opensquilla_better": winner == "opensquilla",
        "recommended_optimization": None
        if winner == "opensquilla"
        else case.optimization_if_not_better,
    }


def write_reports(rows: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = REPORT_DIR / f"openclaw_vs_opensquilla_meta_skill_{stamp}.jsonl"
    md_path = REPORT_DIR / f"openclaw_vs_opensquilla_meta_skill_{stamp}.md"
    prompts_path = REPORT_DIR / f"openclaw_vs_opensquilla_meta_skill_prompts_{stamp}.md"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    md_path.write_text(render_markdown(rows, jsonl_path), encoding="utf-8")
    prompts_path.write_text(render_prompts_markdown(rows, jsonl_path), encoding="utf-8")
    print(f"wrote {jsonl_path}")
    print(f"wrote {md_path}")
    print(f"wrote {prompts_path}")


def render_markdown(rows: list[dict[str, Any]], jsonl_path: Path) -> str:
    total = len(rows)
    sq_wins = sum(1 for row in rows if row["winner"] == "opensquilla")
    claw_wins = sum(1 for row in rows if row["winner"] == "openclaw")
    ties = sum(1 for row in rows if row["winner"] == "tie")
    failed = [
        row["case"]["case_id"]
        for row in rows
        if not row["opensquilla"]["ok"] or not row["openclaw"]["ok"]
    ]
    lines = [
        "# OpenClaw vs OpenSquilla Meta-Skill Comparison",
        "",
        f"Raw JSONL: `{jsonl_path}`",
        "",
        "## Conclusion",
        "",
        (
            f"OpenSquilla won {sq_wins}/{total} cases; OpenClaw won "
            f"{claw_wins}/{total}; ties: {ties}."
        ),
    ]
    if failed:
        lines.append(f"Cases with endpoint errors/timeouts: {', '.join(failed)}.")
    else:
        lines.append("No endpoint errors or timeouts were recorded.")
    if claw_wins or ties or failed:
        lines.append(
            "Rows that do not show an OpenSquilla win include an optimization note."
        )
    else:
        lines.append("All completed cases favored OpenSquilla under this rubric.")
    lines.extend([
        "",
        "## Score Table",
        "",
        "| Case | OpenSquilla | OpenClaw | Winner | Optimization |",
        "| --- | ---: | ---: | --- | --- |",
    ])
    for row in rows:
        opt = row["recommended_optimization"] or ""
        lines.append(
            "| {case} | {sq} | {claw} | {winner} | {opt} |".format(
                case=row["case"]["case_id"],
                sq=row["opensquilla"]["score"]["total"],
                claw=row["openclaw"]["score"]["total"],
                winner=row["winner"],
                opt=opt.replace("|", "/"),
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in rows:
        lines.append(f"### {row['case']['case_id']}")
        lines.append("")
        lines.append("Prompt:")
        lines.append("")
        lines.append("```text")
        lines.append(row["case"]["prompt"])
        lines.append("```")
        lines.append(f"- Expected advantage: {row['case']['expected_advantage']}")
        if row["recommended_optimization"]:
            lines.append(f"- Optimize: {row['recommended_optimization']}")
        for endpoint in ("opensquilla", "openclaw"):
            result = row[endpoint]
            error = f", error={result['error']}" if result["error"] else ""
            lines.append(
                f"- {endpoint}: ok={result['ok']}, elapsed={result['elapsed_s']}s, "
                f"events={result['event_count']}, provider={result['provider']}, "
                f"model={result['model']}{error}"
            )
        lines.append("")
    return "\n".join(lines)


def render_prompts_markdown(rows: list[dict[str, Any]], jsonl_path: Path) -> str:
    lines = [
        "# OpenClaw vs OpenSquilla Meta-Skill Benchmark Prompts",
        "",
        f"Raw JSONL: `{jsonl_path}`",
        "",
    ]
    for row in rows:
        case = row["case"]
        lines.append(f"## {case['case_id']}")
        lines.append("")
        lines.append(f"- Meta-skill: `{case['skill_name']}`")
        lines.append(f"- Expected advantage: {case['expected_advantage']}")
        lines.append("")
        lines.append("```text")
        lines.append(case["prompt"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _select_cases(case_arg: str) -> list[ComparisonCase]:
    if case_arg == "all":
        return COMPARISON_CASES
    selected = [case for case in COMPARISON_CASES if case.case_id == case_arg]
    if not selected:
        valid = ", ".join(case.case_id for case in COMPARISON_CASES)
        raise SystemExit(f"Unknown case {case_arg!r}. Valid: {valid}")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Run both gateways.")
    parser.add_argument("--case", default="all", help="Case id or 'all'.")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--opensquilla-url", default="ws://127.0.0.1:8081/ws")
    parser.add_argument("--opensquilla-token", default=read_opensquilla_token())
    parser.add_argument(
        "--opensquilla-elevated",
        default="bypass",
        choices=["off", "on", "bypass", "full"],
        help="Gateway elevated mode for OpenSquilla tool calls.",
    )
    parser.add_argument("--openclaw-url", default="ws://127.0.0.1:18789/ws")
    parser.add_argument("--openclaw-config", default=os.environ.get("OPENCLAW_CONFIG"))
    parser.add_argument("--openclaw-idle-timeout", type=float, default=90.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.run_live:
        for case in _select_cases(args.case):
            print(json.dumps(asdict(case), indent=2))
        return
    asyncio.run(run_live(args))


if __name__ == "__main__":
    main()
