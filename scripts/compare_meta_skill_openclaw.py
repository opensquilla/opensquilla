"""Compare OpenSquilla meta-skills against an OpenClaw gateway.

The script defines seven fixed benchmark cases for the high-value meta-skill
scenarios and can run them end-to-end through both gateways.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import textwrap
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path(
    os.environ.get("OPENSQUILLA_COMPARE_REPORT_DIR", ".reports/meta-skill-comparison")
)
JUDGE_SUBSCORE_RANGES: dict[str, tuple[int, int]] = {
    "final_artifact_quality": (0, 40),
    "task_completion": (0, 20),
    "evidence_traceability": (0, 15),
    "actionability": (0, 10),
    "risk_boundary_safety": (0, 10),
    "meta_skill_fit": (0, 5),
}

OPENCLAW_BASELINE_WARMUP = (
    "本轮是任务评估会话。身份、称呼和初始化已经完成；后续请直接处理用户请求，"
    "不要询问姓名、称呼、workspace/bootstrap/onboarding，也不要要求用户在 A/B "
    "路径中选择。"
)

BENCHMARK_CONSTRAINTS = (
    "Benchmark constraints: return the final deliverable inline in chat. "
    "Do not create, edit, or write local files. If you would normally create "
    "a PDF, DOCX, SKILL.md, patch, or other artifact, include artifact-ready "
    "content inline instead. You may name verification commands, but do not "
    "execute them.\n\n"
)


@dataclass(frozen=True)
class RubricCriterion:
    name: str
    description: str
    patterns: tuple[str, ...]
    weight: int = 1


@dataclass(frozen=True)
class ComparisonCase:
    case_id: str
    skill_name: str
    prompt: str
    expected_advantage: str
    optimization_if_not_better: str
    scenario: str = "primary"
    rubric: tuple[RubricCriterion, ...] = ()
    failure_modes: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class JudgeResult:
    winner: str
    scores: dict[str, int]
    confidence: float
    rationale: str
    risks: list[str]
    raw: dict[str, Any]
    model: str


def criterion(
    name: str,
    description: str,
    *patterns: str,
    weight: int = 1,
) -> RubricCriterion:
    return RubricCriterion(name, description, tuple(patterns), weight)


SKILL_RUBRICS: dict[str, tuple[RubricCriterion, ...]] = {
    "meta-paper-write": (
        criterion(
            "paper_sections",
            "Includes canonical manuscript sections.",
            r"abstract",
            r"introduction",
            r"method",
            r"evaluation",
        ),
        criterion(
            "latex_ready", "Provides LaTeX or BibTeX-safe structure.", r"latex", r"\\begin", r"bib"
        ),
        criterion(
            "citation_integrity",
            "Avoids fabricated citations by marking placeholders.",
            r"placeholder",
            r"citation",
            r"reference",
        ),
        criterion(
            "length_plan",
            "Explains how the draft scales to a full paper.",
            r"page",
            r"expand",
            r"full version",
        ),
        criterion(
            "limitations", "Includes limitations and threats to validity.", r"limitation", r"threat"
        ),
    ),
    "meta-pdf-intelligence": (
        criterion(
            "page_traceability", "Preserves page-level evidence.", r"page\s+\d+", r"p\.\s*\d+"
        ),
        criterion(
            "fact_digest",
            "Extracts facts rather than generic summary.",
            r"fact",
            r"key finding",
            r"digest",
        ),
        criterion(
            "open_questions",
            "Lists open questions or missing evidence.",
            r"open question",
            r"unknown",
            r"missing",
        ),
        criterion(
            "memory_index",
            "Builds a reusable memory/index structure.",
            r"memory index",
            r"index",
            r"tag",
        ),
        criterion(
            "no_hallucinated_pdf",
            "Acknowledges missing document limits.",
            r"provided excerpt",
            r"cannot verify",
            r"upload",
        ),
    ),
    "meta-stack-trace-investigator": (
        criterion(
            "frame_parsing",
            "Identifies failing frame, exception, and data shape.",
            r"KeyError",
            r"frame",
            r"parse",
        ),
        criterion(
            "root_cause",
            "Provides ranked root-cause hypotheses.",
            r"root cause",
            r"hypothesis",
            r"likely",
        ),
        criterion("repo_search", "Gives concrete repo search targets.", r"rg ", r"grep", r"search"),
        criterion(
            "reproduction",
            "Gives a reproduction or focused check.",
            r"repro",
            r"fixture",
            r"minimal",
        ),
        criterion(
            "verification", "Gives exact verification commands.", r"pytest", r"command", r"verify"
        ),
    ),
    "meta-travel-planner": (
        criterion(
            "constraint_capture",
            "Captures dates, party, pace, budget, and interests.",
            r"assumption",
            r"constraint",
            r"budget",
        ),
        criterion(
            "geo_grouping",
            "Groups activities by neighborhood/transit.",
            r"neighborhood",
            r"transit",
            r"route",
        ),
        criterion(
            "daily_schedule", "Produces day-by-day itinerary.", r"day\s+1", r"day\s+2", r"schedule"
        ),
        criterion(
            "weather_backup",
            "Includes rain or weather backup plan.",
            r"rain",
            r"weather",
            r"backup",
        ),
        criterion(
            "variants", "Includes variants or alternatives.", r"variant", r"alternative", r"swap"
        ),
    ),
    "meta-skill-creator": (
        criterion("trigger_inputs", "Defines triggers and inputs.", r"trigger", r"input"),
        criterion(
            "step_graph",
            "Defines a workflow graph or ordered steps.",
            r"step",
            r"graph",
            r"workflow",
        ),
        criterion(
            "skill_preview", "Shows a SKILL.md-style preview.", r"SKILL\.md", r"```", r"name:"
        ),
        criterion(
            "collision_risk",
            "Checks collisions with existing skills.",
            r"collision",
            r"overlap",
            r"existing",
        ),
        criterion(
            "gates", "Defines lint, smoke, safety, or install gates.", r"gate", r"lint", r"smoke"
        ),
    ),
    "meta-migration-assistant": (
        criterion(
            "migration_scope",
            "Identifies source and target migration states.",
            r"CommonJS",
            r"ESM",
            r"from",
            r"to",
        ),
        criterion(
            "breaking_changes", "Names breaking changes.", r"breaking", r"interop", r"compat"
        ),
        criterion(
            "grep_patterns",
            "Provides grep/search patterns.",
            r"rg ",
            r"grep",
            r"require\(",
            r"module\.exports",
        ),
        criterion(
            "validation_commands",
            "Provides validation commands.",
            r"test",
            r"build",
            r"command",
            r"verify",
        ),
        criterion(
            "rollout_risk", "Includes staged rollout risks.", r"rollout", r"risk", r"rollback"
        ),
    ),
}


COMPARISON_CASES: list[ComparisonCase] = [
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
            '  File "src/agent/runtime.py", line 88, in run_step\n'
            "    payload = parse_tool_result(raw)\n"
            '  File "src/agent/tools.py", line 41, in parse_tool_result\n'
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


COMPARISON_CASES.extend(
    [
        ComparisonCase(
            case_id="paper_write_citation_boundary",
            skill_name="meta-paper-write",
            scenario="degraded",
            prompt=(
                "Draft a LaTeX-ready extended abstract about agent meta-skill "
                "orchestration. Do not fabricate real citations; use BibTeX keys "
                "like TODO:smith2026 until I provide a library. Include a related "
                "work plan, evaluation table, limitations, and a path to a 10-page "
                "paper."
            ),
            expected_advantage=(
                "OpenSquilla should keep manuscript structure while enforcing "
                "citation integrity rather than inventing references."
            ),
            optimization_if_not_better=(
                "Make citation-integrity gating explicit for short paper drafts and "
                "mark unresolved references as TODO placeholders."
            ),
            failure_modes=(
                "Invents real-looking citations.",
                "Omits LaTeX-ready structure.",
                "Does not explain expansion to full paper length.",
            ),
        ),
        ComparisonCase(
            case_id="paper_write_scope_control",
            skill_name="meta-paper-write",
            scenario="boundary",
            prompt=(
                "I do not want the full paper yet. Produce a one-page manuscript "
                "brief for a future paper on meta-skill evaluation: thesis, section "
                "outline, evaluation design, risks to validity, and what evidence "
                "must be collected before writing."
            ),
            expected_advantage=(
                "OpenSquilla should respect the user's scope and produce a planning "
                "artifact instead of a long manuscript."
            ),
            optimization_if_not_better=(
                "Add scope-control checks so paper mode can return briefs, outlines, "
                "or full drafts intentionally."
            ),
            failure_modes=(
                "Overproduces a full paper despite the request.",
                "Omits evidence collection plan.",
                "No limitations or validity risks.",
            ),
        ),
        ComparisonCase(
            case_id="pdf_intelligence_missing_file_boundary",
            skill_name="meta-pdf-intelligence",
            scenario="boundary",
            prompt=(
                "I forgot to attach the PDF. The title is Observability for Agentic "
                "Systems, but I do not remember the contents. Give me the intake "
                "questions, extraction plan, evidence table schema, and what you "
                "must not claim until the file is available."
            ),
            expected_advantage=(
                "OpenSquilla should fail gracefully without hallucinating document "
                "content and should prepare a traceable extraction workflow."
            ),
            optimization_if_not_better=(
                "Improve missing-PDF handling with an intake template and explicit "
                "non-claims section."
            ),
            failure_modes=(
                "Summarizes a PDF that was not provided.",
                "No evidence table or page schema.",
                "Does not ask for the file or page excerpts.",
            ),
        ),
        ComparisonCase(
            case_id="pdf_intelligence_two_doc_compare",
            skill_name="meta-pdf-intelligence",
            scenario="degraded",
            prompt=(
                "Compare two provided PDF excerpts. Doc A page 2 says traces show "
                "tool calls and model routing. Doc A page 7 says missing spans hide "
                "retries. Doc B page 4 says cost attribution needs per-step usage. "
                "Return a cross-document evidence matrix, conflicts, open questions, "
                "and a memory index."
            ),
            expected_advantage=(
                "OpenSquilla should compare page-grounded evidence across documents "
                "and preserve provenance in the output."
            ),
            optimization_if_not_better=(
                "Add a multi-document excerpt mode that renders evidence matrices before synthesis."
            ),
            failure_modes=(
                "Merges Doc A and Doc B without provenance.",
                "Drops page numbers.",
                "Omits conflicts or open questions.",
            ),
        ),
        ComparisonCase(
            case_id="stack_trace_ambiguous_boundary",
            skill_name="meta-stack-trace-investigator",
            scenario="boundary",
            prompt=(
                "I only have this vague error: 'tool result parse failed after a "
                "provider retry'. No stack trace yet. Give me the minimum data to "
                "collect, repo search targets, likely failure classes, and commands "
                "to narrow it down without pretending you know the exact root cause."
            ),
            expected_advantage=(
                "OpenSquilla should avoid false certainty and produce a targeted "
                "diagnostic collection plan."
            ),
            optimization_if_not_better=(
                "Improve ambiguous-error mode with evidence requirements before root cause claims."
            ),
            failure_modes=(
                "Claims a single root cause without evidence.",
                "No data collection checklist.",
                "No concrete repo search commands.",
            ),
        ),
        ComparisonCase(
            case_id="stack_trace_js_async",
            skill_name="meta-stack-trace-investigator",
            scenario="degraded",
            prompt=(
                "Investigate this Node stack trace:\n"
                "TypeError: Cannot read properties of undefined (reading 'content')\n"
                "  at parseAssistantMessage (src/stream/consumer.ts:77:21)\n"
                "  at onDelta (src/stream/consumer.ts:141:9)\n"
                "  at processTicksAndRejections (node:internal/process/task_queues:95:5)\n"
                "Include hypotheses, TypeScript grep targets, a minimal fixture, "
                "and verification commands."
            ),
            expected_advantage=(
                "OpenSquilla should adapt the stack-trace workflow to TypeScript "
                "and produce concrete reproduction and verification targets."
            ),
            optimization_if_not_better=(
                "Add language-aware stack parsing and fixture suggestions for "
                "JavaScript/TypeScript traces."
            ),
            failure_modes=(
                "Treats it as Python.",
                "No fixture or verification commands.",
                "Does not identify undefined content shape.",
            ),
        ),
        ComparisonCase(
            case_id="travel_planner_constraints",
            skill_name="meta-travel-planner",
            scenario="degraded",
            prompt=(
                "Plan 4 days in Kyoto for two adults and one parent with knee pain. "
                "We are vegetarian, prefer rail/bus over taxis, need one rest block "
                "per day, and have a tea ceremony booking at 15:00 on day 2 near "
                "Gion. Include assumptions, neighborhood grouping, rain backups, "
                "budget notes, and variants."
            ),
            expected_advantage=(
                "OpenSquilla should preserve mobility, dietary, fixed-booking, "
                "weather, budget, and transit constraints."
            ),
            optimization_if_not_better=(
                "Strengthen constraint extraction and schedule feasibility checks "
                "for accessibility and fixed events."
            ),
            failure_modes=(
                "Schedules high-walking days without rest blocks.",
                "Ignores vegetarian constraint.",
                "Misses fixed day-2 booking.",
            ),
        ),
        ComparisonCase(
            case_id="travel_planner_missing_dates_boundary",
            skill_name="meta-travel-planner",
            scenario="boundary",
            prompt=(
                "I might visit Seoul sometime next year but I have no dates, budget, "
                "or neighborhood preference yet. Give me a planning framework, the "
                "questions you need answered, seasonal tradeoffs, and a sample 2-day "
                "placeholder itinerary clearly marked as tentative."
            ),
            expected_advantage=(
                "OpenSquilla should ask for missing constraints and mark any sample "
                "itinerary as provisional."
            ),
            optimization_if_not_better=(
                "Improve missing-constraint mode so tentative plans are clearly "
                "separated from final itineraries."
            ),
            failure_modes=(
                "Presents a final itinerary despite missing dates.",
                "No clarifying questions.",
                "No seasonal tradeoffs.",
            ),
        ),
        ComparisonCase(
            case_id="meta_skill_creator_collision_boundary",
            skill_name="meta-skill-creator",
            scenario="boundary",
            prompt=(
                "Before creating anything, evaluate whether a new 'due-diligence "
                "brief' meta-skill would collide with existing web research, PDF "
                "intelligence, and doc export skills. Return a collision matrix, "
                "when not to create it, and a minimal SKILL.md preview only if it "
                "is still justified."
            ),
            expected_advantage=(
                "OpenSquilla should check whether composition is justified before "
                "drafting a new meta-skill."
            ),
            optimization_if_not_better=(
                "Add stronger no-new-skill and collision-first gates to the creator workflow."
            ),
            failure_modes=(
                "Creates a full skill without collision analysis.",
                "Does not mention existing skill overlap.",
                "No no-create criteria.",
            ),
        ),
        ComparisonCase(
            case_id="meta_skill_creator_safety_gates",
            skill_name="meta-skill-creator",
            scenario="degraded",
            prompt=(
                "Design a meta-skill that can run repo search and browser research "
                "but must never install dependencies, commit code, or publish files "
                "without explicit user approval. Include triggers, inputs, step "
                "graph, permission gates, failure modes, and a SKILL.md preview."
            ),
            expected_advantage=(
                "OpenSquilla should encode safety and permission gates as first-class "
                "workflow requirements."
            ),
            optimization_if_not_better=(
                "Make generated meta-skills include explicit authority boundaries "
                "and blocked actions by default."
            ),
            failure_modes=(
                "No explicit permission gates.",
                "Allows install/commit/publish without approval.",
                "No failure modes.",
            ),
        ),
        ComparisonCase(
            case_id="migration_assistant_repo_boundary",
            skill_name="meta-migration-assistant",
            scenario="boundary",
            prompt=(
                "Assess whether this repo is ready for a CommonJS to ESM migration, "
                "but do not assume files that you have not inspected. Give me a "
                "repo-discovery checklist, grep patterns, decision gates, and what "
                "would block migration."
            ),
            expected_advantage=(
                "OpenSquilla should distinguish actual repo evidence from a generic "
                "migration guide."
            ),
            optimization_if_not_better=(
                "Improve repo-evidence gating and make unsupported assumptions show up as blockers."
            ),
            failure_modes=(
                "Invents repository files.",
                "No discovery checklist.",
                "No migration blockers or decision gates.",
            ),
        ),
        ComparisonCase(
            case_id="migration_assistant_incremental_rollout",
            skill_name="meta-migration-assistant",
            scenario="degraded",
            prompt=(
                "We need an incremental CommonJS to ESM migration plan for a package "
                "used by downstream apps. Include dual-package hazards, package.json "
                "exports changes, test/build commands, grep patterns, rollback plan, "
                "and release sequencing."
            ),
            expected_advantage=(
                "OpenSquilla should produce a practical migration plan with rollout "
                "risk controls instead of only syntax changes."
            ),
            optimization_if_not_better=(
                "Strengthen rollout-risk handling for migrations that affect downstream consumers."
            ),
            failure_modes=(
                "Only describes import/export syntax.",
                "No rollback or release sequence.",
                "No dual-package hazard discussion.",
            ),
        ),
    ]
)


def rubric_for_case(case: ComparisonCase) -> tuple[RubricCriterion, ...]:
    return case.rubric or SKILL_RUBRICS.get(case.skill_name, ())


def score_response(text: str, case: ComparisonCase | None = None) -> ResponseScore:
    if case is not None and rubric_for_case(case):
        return score_case_response(text, case)
    return score_generic_response(text)


def score_case_response(text: str, case: ComparisonCase) -> ResponseScore:
    dimensions: dict[str, int] = {}
    notes: list[str] = []
    for item in rubric_for_case(case):
        matched = any(re.search(pattern, text, flags=re.I | re.M) for pattern in item.patterns)
        dimensions[item.name] = item.weight if matched else 0
        if not matched:
            notes.append(item.name)
    return ResponseScore(total=sum(dimensions.values()), dimensions=dimensions, notes=notes)


def score_generic_response(text: str) -> ResponseScore:
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
    notes = [name for name, value in dimensions.items() if value <= 1]
    return ResponseScore(total=sum(dimensions.values()), dimensions=dimensions, notes=notes)


def _count_matches(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.I | re.M))


def _count_words(text: str, words: list[str]) -> int:
    return sum(1 for word in words if word in text)


def normalized_winner(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"opensquilla", "openclaw", "tie"}:
        return lowered
    if lowered in {"a", "response_a", "candidate_a"}:
        return "opensquilla"
    if lowered in {"b", "response_b", "candidate_b"}:
        return "openclaw"
    return "tie"


def response_excerpt(text: str, *, max_chars: int = 12000) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    head = max_chars // 2
    tail = max_chars - head
    return (
        stripped[:head] + "\n\n[... middle truncated for judge prompt ...]\n\n" + stripped[-tail:]
    )


def blind_product_names(text: str) -> str:
    return (
        text.replace("OpenSquilla", "the specialized meta-skill system")
        .replace("opensquilla", "the specialized meta-skill system")
        .replace("OpenClaw", "the baseline agent system")
        .replace("openclaw", "the baseline agent system")
    )


def build_judge_prompt(
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
) -> str:
    rubric = "\n".join(f"- {item.name}: {item.description}" for item in rubric_for_case(case))
    failure_modes = "\n".join(f"- {item}" for item in case.failure_modes) or "- None listed"
    return textwrap.dedent(
        f"""
        You are judging a product-quality benchmark between two anonymous AI agent systems.
        Judge only the two answers. Do not reward brand assumptions. The user asked:

        {case.prompt}

        Evaluation constraints:
        - Judge the final user-visible answer, not hidden orchestration traces.
        - Do not reward claims that tools, files, commands, or external checks were
          completed unless the answer provides visible evidence.
        - If the user asked for an artifact, reward artifact-ready content that can
          be pasted or used directly.

        Meta-skill under test: {case.skill_name}
        Scenario: {case.scenario}
        Expected advantage being tested: {blind_product_names(case.expected_advantage)}

        Rubric dimensions:
        {rubric}

        Known failure modes to penalize:
        {blind_product_names(failure_modes)}

        Endpoint health:
        - Candidate A ok={opensquilla.ok}, error={opensquilla.error}
        - Candidate B ok={openclaw.ok}, error={openclaw.error}

        JSON label mapping:
        - Use "opensquilla" for Candidate A.
        - Use "openclaw" for Candidate B.
        These are opaque output labels for the two anonymous candidates, not
        product facts. Do not infer quality from the labels.

        Candidate A answer:
        ```text
        {response_excerpt(opensquilla.response_text)}
        ```

        Candidate B answer:
        ```text
        {response_excerpt(openclaw.response_text)}
        ```

        Prioritize the quality of the final user-visible deliverable. Meta-skill
        orchestration is valuable only when it produces a better final artifact.

        Score each candidate from 0 to 100 using these weights:
        - final_artifact_quality: 40 points. The final deliverable is complete,
          coherent, polished, directly usable, appropriately structured for the
          requested artifact, and avoids distracting boilerplate.
        - task_completion: 20 points. It directly solves the user's concrete
          request, including all requested sub-parts.
        - evidence_traceability: 15 points. It maps important claims to pasted
          facts, source URLs, file/page evidence, or observed tool output where
          applicable.
        - actionability: 10 points. It gives concrete next steps, decisions,
          owners, checks, or schedules that the user can execute without another
          planning pass.
        - risk_boundary_safety: 10 points. It flags legal, finance, medical,
          security, privacy, or unknown-evidence boundaries instead of
          over-claiming.
        - meta_skill_fit: 5 points. It shows specialized workflow behavior
          expected for this meta-skill, beyond a generic high-end chat answer.

        The top-level scores MUST equal the sum of the six weighted subscores
        for each candidate. Do not invent an independent overall score.

        Use these cross-cutting checks while assigning the weighted score:
        - endpoint_validity: only compare usable, non-empty answers from healthy endpoints.
          Do not award a win because the other endpoint errored, timed out, or returned
          an empty response; treat that row as inconclusive unless both usable answers exist.
        - correctness_grounding: facts, constraints, citations, commands, and caveats are
          plausible, internally consistent, and not invented.
        - constraint_following: obeys inline-only/no-write/no-fake-execution constraints.
        - fairness_control: do not reward brand assumptions, model reputation, verbosity,
          or unrelated bootstrap/runtime/system commentary. Penalize unrelated bootstrap
          notes or tool/runtime chatter that distracts from the user's deliverable.
        - concision_efficiency: useful density without filler; do not reward verbosity alone.

        Hard caps:
        - timeout, empty response, or endpoint error: max 20 unless the other side also failed
        - answer is mostly off-task: max 30
        - fabricated source/file/tool execution: max 50
        - violates no-write/no-execute constraint: max 70

        Return strict JSON only with this schema:
        {{
          "winner": "opensquilla" | "openclaw" | "tie",
          "scores": {{"opensquilla": 0-100, "openclaw": 0-100}},
          "subscores": {{
            "opensquilla": {{
              "final_artifact_quality": 0-40,
              "task_completion": 0-20,
              "evidence_traceability": 0-15,
              "actionability": 0-10,
              "risk_boundary_safety": 0-10,
              "meta_skill_fit": 0-5
            }},
            "openclaw": {{
              "final_artifact_quality": 0-40,
              "task_completion": 0-20,
              "evidence_traceability": 0-15,
              "actionability": 0-10,
              "risk_boundary_safety": 0-10,
              "meta_skill_fit": 0-5
            }}
          }},
          "confidence": 0.0-1.0,
          "rationale": "one short paragraph",
          "risks": ["short risk or uncertainty"]
        }}
        """
    ).strip()


def parse_judge_response(text: str, model: str) -> JudgeResult:
    data = _load_json_object(text)
    raw_scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    if not raw_scores and {"opensquilla", "openclaw"} <= set(data):
        raw_scores = data
    scores = {
        "opensquilla": int(raw_scores.get("opensquilla", 0)),
        "openclaw": int(raw_scores.get("openclaw", 0)),
    }
    winner = normalized_winner(str(data.get("winner", "")))
    if winner not in {"opensquilla", "openclaw", "tie"}:
        winner = "tie"
    if winner == "tie" and scores["opensquilla"] != scores["openclaw"]:
        winner = "opensquilla" if scores["opensquilla"] > scores["openclaw"] else "openclaw"
    confidence_raw = data.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.0
    risks_raw = data.get("risks") if isinstance(data.get("risks"), list) else []
    risks = [str(item) for item in risks_raw[:5]]
    return JudgeResult(
        winner=winner,
        scores=scores,
        confidence=confidence,
        rationale=str(data.get("rationale", "")).strip(),
        risks=risks,
        raw=data,
        model=model,
    )


def _load_json_object(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    )
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        candidates.append(match.group(0))
    decoder = json.JSONDecoder()
    errors: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
        else:
            if isinstance(data, dict):
                return data
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                data, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    fallback = _load_json_object_from_fields(text)
    if fallback:
        return fallback
    excerpt = text.strip().replace("\n", " ")[:500]
    raise ValueError(
        f"judge response was not parseable JSON: {'; '.join(errors[:3])}; excerpt={excerpt!r}"
    )


def _load_json_object_from_fields(text: str) -> dict[str, Any] | None:
    winner_match = re.search(r'"winner"\s*:\s*"([^"]+)"', text, flags=re.I)
    sq_match = re.search(r'"opensquilla"\s*:\s*([0-9]{1,3})', text, flags=re.I)
    claw_match = re.search(r'"openclaw"\s*:\s*([0-9]{1,3})', text, flags=re.I)
    if not (winner_match and sq_match and claw_match):
        return None
    confidence_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', text, flags=re.I)
    return {
        "winner": winner_match.group(1),
        "scores": {
            "opensquilla": int(sq_match.group(1)),
            "openclaw": int(claw_match.group(1)),
        },
        "confidence": float(confidence_match.group(1)) if confidence_match else 0.0,
        "rationale": "",
        "risks": ["Judge response was recovered from malformed JSON fields."],
    }


def _extract_payload_texts(payload: dict[str, Any], *, include_delta: bool) -> list[str]:
    texts: list[str] = []
    message = payload.get("message")
    if isinstance(message, dict) and message.get("role") == "assistant":
        text = _content_to_text(message.get("content"))
        if text:
            texts.append(text)
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        texts.append(data["text"])
    keys = ("text", "content", "final", "response")
    if include_delta:
        keys = (*keys, "delta")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    return [text.strip() for text in texts if text and text.strip()]


def _is_tool_or_meta_step_event(event: dict[str, Any], payload: dict[str, Any]) -> bool:
    event_name = event.get("event")
    if isinstance(event_name, str):
        lowered = event_name.lower()
        if "tool" in lowered or "meta.step" in lowered or "meta-step" in lowered:
            return True
    for key in ("tool_name", "tool_use_id", "tool_call_id", "toolResult", "tool_result"):
        if payload.get(key):
            return True
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("tool_name", "tool_use_id", "tool_call_id", "toolResult", "tool_result"):
            if data.get(key):
                return True
        role = data.get("role")
        if role in {"tool", "function"}:
            return True
    message = payload.get("message")
    if isinstance(message, dict) and message.get("role") in {"tool", "function"}:
        return True
    return False


def extract_text_from_events(events: list[dict[str, Any]]) -> str:
    terminal_candidates: list[str] = []
    assistant_candidates: list[str] = []
    fallback_candidates: list[str] = []
    delta_candidates: list[str] = []

    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        if not isinstance(payload, dict):
            continue
        event_name = event.get("event")
        is_terminal = event_name == "session.event.done"
        texts = _extract_payload_texts(payload, include_delta=False)
        delta_texts = _extract_payload_texts(payload, include_delta=True)
        if is_terminal:
            terminal_candidates.extend(texts)
            continue
        is_toolish = _is_tool_or_meta_step_event(event, payload)
        message = payload.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant" and not is_toolish:
            assistant_candidates.extend(texts)
            continue
        if not is_toolish:
            fallback_candidates.extend(texts)
            delta_candidates.extend(text for text in delta_texts if text not in texts)

    for candidates in (terminal_candidates, assistant_candidates, fallback_candidates):
        if candidates:
            return candidates[-1].strip()
    if delta_candidates:
        return max(delta_candidates, key=len).strip()
    return ""


def extract_error_from_events(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        if not isinstance(payload, dict):
            continue
        event_name = event.get("event")
        is_error_event = isinstance(event_name, str) and event_name.endswith(".error")
        message = payload.get("message")
        if isinstance(message, dict) and isinstance(message.get("errorMessage"), str):
            return message["errorMessage"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return data["error"]
        if isinstance(data, dict) and data.get("phase") == "error":
            value = data.get("error")
            if isinstance(value, str) and value.strip():
                return value
        if payload.get("state") == "error" or is_error_event:
            for key in ("errorMessage", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return None


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


async def _send_application_pings(ws: Any, interval_s: float = 45.0) -> None:
    """Keep gateway app-level receive loops alive during long benchmark turns."""
    while True:
        await asyncio.sleep(interval_s)
        await ws.send('{"type":"ping"}')


def _slug_part(value: str, max_len: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return (slug or "default")[:max_len]


class OpenSquillaRunner:
    def __init__(
        self,
        url: str,
        token: str | None,
        elevated: str | None = None,
        agent_id: str = "main",
        isolated_agent_per_case: bool = False,
        run_id: str | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.elevated = elevated
        self.agent_id = agent_id
        self.isolated_agent_per_case = isolated_agent_per_case
        self.run_id = _slug_part(run_id or uuid.uuid4().hex[:8])

    def _agent_id_for_case(self, case: ComparisonCase) -> str:
        if not self.isolated_agent_per_case:
            return self.agent_id
        case_part = _slug_part(case.case_id.replace("_", "-"), max_len=32)
        prefix = _slug_part(self.agent_id if self.agent_id != "main" else "meta-compare")
        return _slug_part(f"{prefix}-{self.run_id}-{case_part}", max_len=64)

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
        events: list[dict[str, Any]] = []
        control_events: list[dict[str, Any]] = []
        import websockets

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        async with websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=20,
            additional_headers=headers,
        ) as ws:
            first = json.loads(await ws.recv())
            if first.get("event") != "connect.challenge":
                raise RuntimeError(f"unexpected OpenSquilla handshake: {first}")
            auth_params = {"auth": {"token": self.token}} if self.token else {}
            await self._call(
                ws,
                "connect",
                {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "role": "operator",
                    "scopes": ["operator.admin"],
                    "client": {"name": "meta-skill-comparison"},
                    **auth_params,
                },
                control_events,
            )
            agent_id = self._agent_id_for_case(case)
            if agent_id != "main":
                try:
                    await self._call(
                        ws,
                        "agents.create",
                        {
                            "id": agent_id,
                            "name": f"Meta Compare {case.case_id}",
                            "description": "Isolated agent for one meta-skill comparison case.",
                        },
                        control_events,
                    )
                except RuntimeError as exc:
                    if "agent.exists" not in str(exc):
                        raise
            created = await self._call(
                ws,
                "sessions.create",
                {
                    "agentId": agent_id,
                    "kind": "cli",
                    "displayName": f"meta compare {case.case_id}",
                },
                control_events,
            )
            session_key = str(created["key"])
            await self._call(
                ws,
                "sessions.messages.subscribe",
                {"key": session_key},
                control_events,
            )
            source: dict[str, Any] = {
                "caller_kind": "cli",
                "channel_kind": "cli",
                "channel_id": "cli:meta-skill-comparison",
                "source_kind": "cli",
                "source_name": "meta-skill-comparison",
            }
            if self.elevated in ("on", "bypass", "full"):
                source["elevated"] = self.elevated
            await self._call(
                ws,
                "sessions.send",
                {
                    "key": session_key,
                    "message": benchmark_prompt(case),
                    "attachments": [],
                    "_source": source,
                },
                events,
                session_key=session_key,
            )
            await self._read_stream(ws, events, session_key)

        session_events = _events_for_session(events, session_key)
        text = extract_text_from_events(session_events)
        meta_final_text = _latest_opensquilla_meta_final_text(session_key)
        if meta_final_text:
            text = meta_final_text
        transcript_text = await _wait_for_opensquilla_transcript_text(
            session_key,
            minimum_len=len(text),
        )
        if not meta_final_text and len(transcript_text) > len(text):
            text = transcript_text
        stream_error = extract_error_from_events(session_events)
        score = score_response(text, case)
        provider, model = _provider_model_from_events(session_events)
        return EndpointResult(
            endpoint="opensquilla",
            case_id=case.case_id,
            ok=bool(text) and stream_error is None,
            elapsed_s=0.0,
            response_text=text,
            score=asdict(score),
            error=stream_error,
            session_key=session_key,
            provider=provider,
            model=model,
            event_count=len(session_events),
        )

    async def _call(
        self,
        ws: Any,
        method: str,
        params: dict[str, Any],
        events: list[dict[str, Any]],
        session_key: str | None = None,
    ) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({"type": "req", "id": req_id, "method": method, "params": params}))
        while True:
            frame = json.loads(await ws.recv())
            if frame.get("type") == "event":
                if session_key is None or _event_session_key(frame) == session_key:
                    events.append(frame)
                continue
            if method == "connect" and frame.get("protocol") is not None:
                return frame
            if frame.get("type") == "res" and frame.get("id") == req_id:
                if not frame.get("ok"):
                    raise RuntimeError(f"{method} failed: {frame.get('error')}")
                payload = frame.get("payload")
                return payload if isinstance(payload, dict) else {}

    async def _read_stream(
        self,
        ws: Any,
        events: list[dict[str, Any]],
        session_key: str,
    ) -> None:
        keepalive = asyncio.create_task(_send_application_pings(ws))
        try:
            while True:
                frame = json.loads(await ws.recv())
                if frame.get("type") != "event":
                    continue
                if _event_session_key(frame) != session_key:
                    continue
                events.append(frame)
                if frame.get("event") in ("session.event.done", "session.event.error"):
                    return
        finally:
            keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive


class OpenClawRunner:
    def __init__(
        self,
        url: str,
        token: str,
        idle_timeout_s: float = 90.0,
        state_dir: Path | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.idle_timeout_s = idle_timeout_s
        self.state_dir = state_dir

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
        started_at = time.time()
        prompt = benchmark_prompt(case)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        async with websockets.connect(
            self.url,
            ping_interval=None,
            additional_headers=headers,
        ) as ws:
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
            entry = created.get("entry") if isinstance(created.get("entry"), dict) else {}
            session_file = entry.get("sessionFile")
            await self._call(
                ws,
                "sessions.messages.subscribe",
                {"key": session_key},
                control_events,
            )
            warmup_events: list[dict[str, Any]] = []
            await self._call(
                ws,
                "sessions.send",
                {"key": session_key, "message": OPENCLAW_BASELINE_WARMUP},
                warmup_events,
                session_key=session_key,
            )
            await self._read_openclaw_stream(ws, warmup_events, session_key)
            await self._call(
                ws,
                "sessions.send",
                {"key": session_key, "message": prompt},
                events,
                session_key=session_key,
            )
            await self._read_openclaw_stream(ws, events, session_key)
        session_paths: list[Path] = []
        session_path = _resolve_openclaw_session_path(session_file, self.state_dir)
        if session_path is not None and _is_openclaw_session_jsonl(session_path):
            session_paths.append(session_path)
        if self.state_dir is not None:
            discovered = _discover_openclaw_session_file(
                self.state_dir,
                session_key=session_key,
                prompt=prompt,
                started_at=started_at,
            )
            if discovered is not None and discovered not in session_paths:
                session_paths.append(discovered)
        file_events = await _wait_for_openclaw_session_file_events(
            session_paths,
            session_key=session_key,
            after_prompt=prompt,
            timeout_s=self.idle_timeout_s,
        )
        events.extend(file_events)
        session_events = _events_for_session(events, session_key)
        text = extract_text_from_events(session_events)
        stream_error = extract_error_from_events(session_events)
        score = score_response(text, case)
        provider, model = _provider_model_from_events(session_events)
        return EndpointResult(
            endpoint="openclaw",
            case_id=case.case_id,
            ok=bool(text) and stream_error is None,
            elapsed_s=0.0,
            response_text=text,
            score=asdict(score),
            error=stream_error,
            session_key=session_key,
            provider=provider,
            model=model,
            event_count=len(session_events),
        )

    async def _call(
        self,
        ws: Any,
        method: str,
        params: dict[str, Any],
        events: list[dict[str, Any]],
        session_key: str | None = None,
    ) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({"type": "req", "id": req_id, "method": method, "params": params}))
        while True:
            frame = json.loads(await ws.recv())
            if frame.get("type") == "event":
                if session_key is None or _event_session_key(frame) == session_key:
                    events.append(frame)
                continue
            if frame.get("type") == "res" and frame.get("id") == req_id:
                if not frame.get("ok"):
                    raise RuntimeError(f"{method} failed: {frame.get('error')}")
                payload = frame.get("payload")
                return payload if isinstance(payload, dict) else {}

    async def _read_openclaw_stream(
        self,
        ws: Any,
        events: list[dict[str, Any]],
        session_key: str,
    ) -> None:
        keepalive = asyncio.create_task(_send_application_pings(ws))
        deadline = time.monotonic() + self.idle_timeout_s
        try:
            while True:
                timeout = max(0.1, deadline - time.monotonic())
                try:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                except TimeoutError:
                    return
                if frame.get("type") != "event":
                    continue
                if _event_session_key(frame) != session_key:
                    continue
                events.append(frame)
                if frame.get("event") == "chat":
                    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
                    if payload.get("state") == "final":
                        return
                    if payload.get("state") == "error":
                        return
                if frame.get("event") == "agent":
                    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
                    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                    if data.get("phase") == "error":
                        return
                if frame.get("event") == "session.event.error":
                    return
        finally:
            keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive


class LLMJudge:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def judge(
        self,
        case: ComparisonCase,
        opensquilla: EndpointResult,
        openclaw: EndpointResult,
    ) -> JudgeResult:
        if not self.api_key:
            raise RuntimeError("LLM judge requires OPENROUTER_API_KEY or --judge-api-key")
        import httpx

        prompt = build_judge_prompt(case, opensquilla, openclaw)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict benchmark judge. Return only valid JSON. "
                        "Do not mention hidden chain-of-thought."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost/opensquilla-meta-skill-comparison",
            "X-Title": "OpenSquilla Meta Skill Comparison",
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("judge response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("judge response has empty content")
        return parse_judge_response(content, self.model)


def benchmark_prompt(case: ComparisonCase) -> str:
    return case.prompt


def _event_session_key(event: dict[str, Any]) -> str | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    session_key = payload.get("sessionKey")
    if isinstance(session_key, str):
        return session_key
    session = payload.get("session")
    if isinstance(session, dict) and isinstance(session.get("key"), str):
        return session["key"]
    return None


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


def _events_for_session(events: list[dict[str, Any]], session_key: str) -> list[dict[str, Any]]:
    filtered = [
        event
        for event in events
        if (key := _event_session_key(event)) is None or key == session_key
    ]
    return filtered or events


def _latest_opensquilla_transcript_text(session_key: str) -> str:
    """Return the persisted final assistant text for a local gateway session.

    Some gateway streams emit only the assistant preface before a long-running
    ``meta_invoke`` while the complete final text is persisted to the transcript
    after the DAG finishes. Prefer the persisted transcript when available so
    the benchmark judges the actual user-visible final assistant message.
    """

    if not session_key:
        return ""
    state_db = Path(os.environ.get("OPENSQUILLA_STATE_DB", "/root/.opensquilla/state/sessions.db"))
    if not state_db.exists():
        return ""
    try:
        import sqlite3

        with sqlite3.connect(state_db) as conn:
            rows = conn.execute(
                "SELECT content FROM transcript_entries "
                "WHERE session_key=? AND role='assistant' "
                "ORDER BY id ASC",
                (session_key,),
            ).fetchall()
    except Exception:
        return ""
    texts = [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]
    return texts[-1] if texts else ""


def _latest_opensquilla_meta_final_text(session_key: str) -> str:
    if not session_key:
        return ""
    state_db = Path(os.environ.get("OPENSQUILLA_STATE_DB", "/root/.opensquilla/state/sessions.db"))
    if not state_db.exists():
        return ""
    try:
        import sqlite3

        with sqlite3.connect(state_db) as conn:
            rows = conn.execute(
                "SELECT final_text FROM meta_skill_runs "
                "WHERE session_key=? AND status='ok' "
                "ORDER BY started_at_ms ASC",
                (session_key,),
            ).fetchall()
    except Exception:
        return ""
    texts = [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]
    return texts[-1] if texts else ""


async def _wait_for_opensquilla_transcript_text(
    session_key: str,
    *,
    minimum_len: int,
    timeout_s: float = 5.0,
    interval_s: float = 0.25,
) -> str:
    """Poll briefly for the final assistant transcript after stream completion."""

    deadline = time.monotonic() + timeout_s
    best = ""
    while True:
        text = _latest_opensquilla_transcript_text(session_key)
        if len(text) > len(best):
            best = text
        if len(best) > minimum_len or time.monotonic() >= deadline:
            return best
        await asyncio.sleep(interval_s)


def _openclaw_session_file_events(
    path: Path,
    session_key: str,
    *,
    after_prompt: str | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    prompt_seen = after_prompt is None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message") if isinstance(item, dict) else None
        if item.get("type") == "message" and isinstance(message, dict):
            if not prompt_seen:
                if (
                    message.get("role") == "user"
                    and after_prompt
                    and after_prompt in _content_to_text(message.get("content"))
                ):
                    prompt_seen = True
                continue
            events.append(
                {
                    "type": "event",
                    "event": "session.message",
                    "payload": {"sessionKey": session_key, "message": message},
                }
            )
    return events


async def _wait_for_openclaw_session_file_events(
    paths: list[Path],
    *,
    session_key: str,
    after_prompt: str,
    timeout_s: float = 90.0,
    interval_s: float = 0.5,
    stable_s: float = 5.0,
) -> list[dict[str, Any]]:
    """Poll OpenClaw's JSONL file because the WS stream may end before persistence."""

    deadline = time.monotonic() + timeout_s
    best: list[dict[str, Any]] = []
    best_text = ""
    last_change = time.monotonic()
    while True:
        for path in paths:
            events = _openclaw_session_file_events(
                path,
                session_key,
                after_prompt=after_prompt,
            )
            text = extract_text_from_events(events)
            if text != best_text:
                best = events
                best_text = text
                last_change = time.monotonic()
        now = time.monotonic()
        if best_text and now - last_change >= stable_s:
            return best
        if now >= deadline:
            return best
        await asyncio.sleep(interval_s)


def _resolve_openclaw_session_path(session_file: Any, state_dir: Path | None) -> Path | None:
    if not isinstance(session_file, str) or not session_file.strip():
        return None
    if state_dir is not None and session_file.startswith("$OPENCLAW_STATE_DIR/"):
        return state_dir / session_file.removeprefix("$OPENCLAW_STATE_DIR/")
    path = Path(session_file)
    if path.is_absolute() or state_dir is None:
        return path
    candidate = state_dir / path
    return candidate if candidate.exists() else path


def _is_openclaw_session_jsonl(path: Path) -> bool:
    return path.exists() and path.suffix == ".jsonl" and ".trajectory" not in path.name


def _discover_openclaw_session_file(
    state_dir: Path,
    *,
    session_key: str,
    prompt: str,
    started_at: float,
) -> Path | None:
    sessions_dir = state_dir / "agents" / "main" / "sessions"
    if not sessions_dir.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for path in sessions_dir.glob("*.jsonl"):
        if ".trajectory" in path.name:
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < started_at - 5:
                continue
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        trajectory_path = path.with_name(f"{path.stem}.trajectory.jsonl")
        trajectory_text = ""
        if trajectory_path.exists():
            try:
                trajectory_text = trajectory_path.read_text(encoding="utf-8")
            except OSError:
                trajectory_text = ""
        if (
            prompt in text
            or _openclaw_session_file_contains_prompt(path, prompt)
            or session_key in trajectory_text
        ):
            candidates.append((stat.st_mtime, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _openclaw_session_file_contains_prompt(path: Path, prompt: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message") if isinstance(item, dict) else None
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _content_to_text(message.get("content"))
        if prompt in text:
            return True
    return False


def _event_session_key(event: dict[str, Any]) -> str | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
    if not isinstance(payload, dict):
        return None
    for key_name in ("sessionKey", "session_key", "key"):
        value = payload.get(key_name)
        if isinstance(value, str):
            return value
    session = payload.get("session")
    if isinstance(session, dict):
        value = session.get("key")
        if isinstance(value, str):
            return value
    return None


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


def read_judge_api_key() -> str | None:
    for env_name in ("OPENSQUILLA_JUDGE_API_KEY", "OPENROUTER_API_KEY"):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


async def run_live(args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = _select_cases(args.case, scenario=args.scenario, skill=args.skill)
    if not args.openclaw_config:
        raise SystemExit("Pass --openclaw-config or set OPENCLAW_CONFIG.")
    openclaw_token = read_openclaw_token(Path(args.openclaw_config))
    opensquilla = OpenSquillaRunner(
        args.opensquilla_url,
        args.opensquilla_token,
        elevated=args.opensquilla_elevated,
    )
    openclaw = OpenClawRunner(
        args.openclaw_url,
        openclaw_token,
        args.openclaw_idle_timeout,
        state_dir=Path(args.openclaw_config).parent,
    )
    judge = None
    if args.judge_llm:
        if not args.judge_model:
            raise SystemExit("Pass --judge-model or set OPENSQUILLA_JUDGE_MODEL.")
        judge = LLMJudge(
            model=args.judge_model,
            api_key=args.judge_api_key,
            base_url=args.judge_base_url,
            timeout_s=args.judge_timeout,
        )

    rows: list[dict[str, Any]] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for case in selected:
        print(f"running {case.case_id} ...", flush=True)
        sq_result, claw_result = await asyncio.gather(
            opensquilla.run(case, args.timeout),
            openclaw.run(case, args.timeout),
        )
        row = compare_results(case, sq_result, claw_result)
        if judge is not None:
            try:
                judge_result = await judge_with_retries(judge, case, sq_result, claw_result)
                row = apply_judge_result(row, judge_result, case)
            except Exception as exc:
                row["judge_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        print(
            f"{case.case_id}: opensquilla={sq_result.score['total']} "
            f"openclaw={claw_result.score['total']} winner={row['winner']}",
            flush=True,
        )
        write_reports(rows, stamp=stamp)
    write_reports(rows, stamp=stamp)
    return rows


async def judge_existing(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.judge_jsonl:
        raise SystemExit("Pass --judge-jsonl.")
    if not args.judge_model:
        raise SystemExit("Pass --judge-model or set OPENSQUILLA_JUDGE_MODEL.")
    judge = LLMJudge(
        model=args.judge_model,
        api_key=args.judge_api_key,
        base_url=args.judge_base_url,
        timeout_s=args.judge_timeout,
    )
    rows = [
        json.loads(line)
        for line in Path(args.judge_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    judged_rows: list[dict[str, Any]] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for row in rows:
        case = case_from_row(row)
        opensquilla = endpoint_from_row(row, "opensquilla")
        openclaw = endpoint_from_row(row, "openclaw")
        row.setdefault("baseline_winner", row.get("winner", "tie"))
        row.setdefault("score_basis", "deterministic")
        try:
            judge_result = await judge_with_retries(judge, case, opensquilla, openclaw)
            judged = apply_judge_result(row, judge_result, case)
        except Exception as exc:
            judged = dict(row)
            judged["judge_error"] = f"{type(exc).__name__}: {exc}"
        judged_rows.append(judged)
        print(f"judged {case.case_id}: winner={judged.get('winner')}", flush=True)
        write_reports(judged_rows, stamp=stamp)
    write_reports(judged_rows, stamp=stamp)
    return judged_rows


def compare_results(
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
) -> dict[str, Any]:
    sq_total = int(opensquilla.score["total"])
    claw_total = int(openclaw.score["total"])
    if not opensquilla.ok and openclaw.ok:
        baseline_winner = "openclaw"
    elif opensquilla.ok and not openclaw.ok:
        baseline_winner = "opensquilla"
    elif sq_total > claw_total:
        baseline_winner = "opensquilla"
    elif claw_total > sq_total:
        baseline_winner = "openclaw"
    else:
        baseline_winner = "tie"
    return {
        "case": case_to_dict(case),
        "opensquilla": asdict(opensquilla),
        "openclaw": asdict(openclaw),
        "baseline_winner": baseline_winner,
        "winner": baseline_winner,
        "score_basis": "deterministic",
        "opensquilla_better": baseline_winner == "opensquilla",
        "recommended_optimization": None
        if baseline_winner == "opensquilla"
        else case.optimization_if_not_better,
    }


def apply_judge_result(
    row: dict[str, Any],
    judge_result: JudgeResult,
    case: ComparisonCase,
) -> dict[str, Any]:
    judge_result = normalize_weighted_judge_result(judge_result)
    winner = judge_result.winner
    updated = dict(row)
    updated["judge"] = asdict(judge_result)
    updated["winner"] = winner
    updated["score_basis"] = "llm_judge"
    updated["opensquilla_better"] = winner == "opensquilla"
    updated["recommended_optimization"] = (
        None if winner == "opensquilla" else case.optimization_if_not_better
    )
    updated.pop("judge_error", None)
    return updated


async def judge_with_retries(
    judge: LLMJudge,
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
    *,
    attempts: int = 3,
) -> JudgeResult:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            result = await judge.judge(case, opensquilla, openclaw)
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            continue
        try:
            return normalize_weighted_judge_result(result)
        except ValueError as exc:
            errors.append(f"attempt {attempt}: {exc}")
    raise RuntimeError("; ".join(errors))


def normalize_weighted_judge_result(judge_result: JudgeResult) -> JudgeResult:
    if not judge_result.rationale.strip():
        raise ValueError("judge response missing rationale")
    raw = judge_result.raw if isinstance(judge_result.raw, dict) else {}
    totals = weighted_judge_totals(raw)
    if totals is None:
        raise ValueError("judge response missing complete weighted subscores")
    winner = "tie"
    if totals["opensquilla"] > totals["openclaw"]:
        winner = "opensquilla"
    elif totals["openclaw"] > totals["opensquilla"]:
        winner = "openclaw"
    normalized_raw = dict(raw)
    normalized_raw["scores"] = totals
    normalized_raw["winner"] = winner
    normalized_raw["score_source"] = "weighted_subscores"
    return JudgeResult(
        winner=winner,
        scores=totals,
        confidence=judge_result.confidence,
        rationale=judge_result.rationale,
        risks=judge_result.risks,
        raw=normalized_raw,
        model=judge_result.model,
    )


def weighted_judge_totals(raw: dict[str, Any]) -> dict[str, int] | None:
    subscores = raw.get("subscores") if isinstance(raw.get("subscores"), dict) else {}
    totals: dict[str, int] = {}
    for label in ("opensquilla", "openclaw"):
        candidate = subscores.get(label)
        if not isinstance(candidate, dict):
            return None
        total = 0
        for name, (low, high) in JUDGE_SUBSCORE_RANGES.items():
            if name not in candidate:
                return None
            try:
                value = int(candidate[name])
            except (TypeError, ValueError):
                return None
            if value < low or value > high:
                return None
            total += value
        totals[label] = total
    return totals


def case_from_row(row: dict[str, Any]) -> ComparisonCase:
    case_data = row.get("case") if isinstance(row.get("case"), dict) else {}
    case_id = str(case_data.get("case_id", ""))
    for case in COMPARISON_CASES:
        if case.case_id == case_id:
            return case
    rubric_data = case_data.get("rubric") if isinstance(case_data.get("rubric"), list) else []
    rubric = tuple(
        RubricCriterion(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            patterns=tuple(str(pattern) for pattern in item.get("patterns", ())),
            weight=int(item.get("weight", 1)),
        )
        for item in rubric_data
        if isinstance(item, dict)
    )
    return ComparisonCase(
        case_id=case_id,
        skill_name=str(case_data.get("skill_name", "")),
        prompt=str(case_data.get("prompt", "")),
        expected_advantage=str(case_data.get("expected_advantage", "")),
        optimization_if_not_better=str(case_data.get("optimization_if_not_better", "")),
        scenario=str(case_data.get("scenario", "primary")),
        rubric=rubric,
        failure_modes=tuple(str(item) for item in case_data.get("failure_modes", ())),
    )


def endpoint_from_row(row: dict[str, Any], endpoint: str) -> EndpointResult:
    data = row.get(endpoint) if isinstance(row.get(endpoint), dict) else {}
    return EndpointResult(
        endpoint=endpoint,
        case_id=str(data.get("case_id", row.get("case", {}).get("case_id", ""))),
        ok=bool(data.get("ok")),
        elapsed_s=float(data.get("elapsed_s", 0.0)),
        response_text=str(data.get("response_text", "")),
        score=data.get("score") if isinstance(data.get("score"), dict) else {"total": 0},
        error=str(data["error"]) if data.get("error") is not None else None,
        session_key=str(data["session_key"]) if data.get("session_key") is not None else None,
        model=str(data["model"]) if data.get("model") is not None else None,
        provider=str(data["provider"]) if data.get("provider") is not None else None,
        event_count=int(data.get("event_count", 0)),
    )


def case_to_dict(case: ComparisonCase) -> dict[str, Any]:
    data = asdict(case)
    if not data["rubric"]:
        data["rubric"] = [asdict(item) for item in rubric_for_case(case)]
    return data


def write_reports(rows: list[dict[str, Any]], stamp: str | None = None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if stamp is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
    judged = [row for row in rows if row.get("score_basis") == "llm_judge"]
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
    if judged:
        lines.append(f"Final winner uses LLM judge for {len(judged)}/{total} rows.")
    else:
        lines.append(
            "Final winner uses deterministic rubric scoring; no LLM judge rows are present."
        )
    if failed:
        lines.append(f"Cases with endpoint errors/timeouts: {', '.join(failed)}.")
    else:
        lines.append("No endpoint errors or timeouts were recorded.")
    if claw_wins or ties or failed:
        lines.append("Rows that do not show an OpenSquilla win include an optimization note.")
    else:
        lines.append("All completed cases favored OpenSquilla under this rubric.")
    lines.extend(
        [
            "",
            "## Score Table",
            "",
            "| Case | OpenSquilla | OpenClaw | Baseline | Judge | Winner | Optimization |",
            "| --- | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        opt = row["recommended_optimization"] or ""
        judge = row.get("judge") if isinstance(row.get("judge"), dict) else None
        judge_cell = ""
        if judge:
            scores = judge.get("scores") if isinstance(judge.get("scores"), dict) else {}
            judge_cell = (
                f"{scores.get('opensquilla', '')}-{scores.get('openclaw', '')} "
                f"{judge.get('winner', '')}"
            ).strip()
        lines.append(
            "| {case} | {sq} | {claw} | {baseline} | {judge} | {winner} | {opt} |".format(
                case=row["case"]["case_id"],
                sq=row["opensquilla"]["score"]["total"],
                claw=row["openclaw"]["score"]["total"],
                baseline=row.get("baseline_winner", row.get("winner", "")),
                judge=judge_cell,
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
        scenario = row["case"].get("scenario")
        if scenario:
            lines.append(f"- Scenario: {scenario}")
        rubric = row["case"].get("rubric") or []
        if rubric:
            lines.append(
                "- Rubric: "
                + ", ".join(
                    f"{item['name']}({item.get('weight', 1)})"
                    for item in rubric
                    if isinstance(item, dict)
                )
            )
        failure_modes = row["case"].get("failure_modes") or []
        if failure_modes:
            lines.append("- Failure modes: " + "; ".join(failure_modes))
        if row["recommended_optimization"]:
            lines.append(f"- Optimize: {row['recommended_optimization']}")
        lines.append(f"- Score basis: {row.get('score_basis', 'deterministic')}")
        if row.get("baseline_winner") and row.get("baseline_winner") != row.get("winner"):
            lines.append(f"- Baseline winner: {row['baseline_winner']}")
        judge = row.get("judge") if isinstance(row.get("judge"), dict) else None
        if judge:
            scores = judge.get("scores") if isinstance(judge.get("scores"), dict) else {}
            risks = judge.get("risks") if isinstance(judge.get("risks"), list) else []
            lines.append(
                (
                    "- Judge: winner={winner}, scores={sq}-{claw}, "
                    "confidence={confidence}, model={model}"
                ).format(
                    winner=judge.get("winner"),
                    sq=scores.get("opensquilla"),
                    claw=scores.get("openclaw"),
                    confidence=judge.get("confidence"),
                    model=judge.get("model"),
                )
            )
            if judge.get("rationale"):
                lines.append(f"- Judge rationale: {judge['rationale']}")
            if risks:
                lines.append("- Judge risks: " + "; ".join(str(item) for item in risks))
        if row.get("judge_error"):
            lines.append(f"- Judge error: {row['judge_error']}")
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


def _select_cases(
    case_arg: str,
    *,
    scenario: str | None = None,
    skill: str | None = None,
) -> list[ComparisonCase]:
    if case_arg == "all":
        selected = COMPARISON_CASES
    else:
        selected = [case for case in COMPARISON_CASES if case.case_id == case_arg]
        if not selected:
            valid = ", ".join(case.case_id for case in COMPARISON_CASES)
            raise SystemExit(f"Unknown case {case_arg!r}. Valid: {valid}")
    if scenario:
        selected = [case for case in selected if case.scenario == scenario]
    if skill:
        selected = [case for case in selected if case.skill_name == skill]
    if not selected:
        raise SystemExit("No comparison cases matched the requested filters.")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Run both gateways.")
    parser.add_argument(
        "--judge-jsonl",
        help="Judge an existing comparison JSONL without rerunning both gateways.",
    )
    parser.add_argument("--case", default="all", help="Case id or 'all'.")
    parser.add_argument(
        "--scenario",
        choices=["primary", "degraded", "boundary"],
        help="Optional scenario filter for case='all'.",
    )
    parser.add_argument("--skill", help="Optional meta-skill name filter for case='all'.")
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
    parser.add_argument(
        "--judge-llm",
        action="store_true",
        help="Use an LLM judge for the final winner after deterministic scoring.",
    )
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("OPENSQUILLA_JUDGE_MODEL"),
        help="OpenRouter model id for --judge-llm.",
    )
    parser.add_argument("--judge-api-key", default=read_judge_api_key())
    parser.add_argument(
        "--judge-base-url",
        default=os.environ.get("OPENSQUILLA_JUDGE_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    parser.add_argument("--judge-timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.judge_jsonl:
        asyncio.run(judge_existing(args))
        return
    if not args.run_live:
        for case in _select_cases(args.case, scenario=args.scenario, skill=args.skill):
            print(json.dumps(case_to_dict(case), indent=2))
        return
    asyncio.run(run_live(args))


if __name__ == "__main__":
    main()
