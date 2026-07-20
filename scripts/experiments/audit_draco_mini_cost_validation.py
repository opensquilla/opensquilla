#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EXPECTED_MODELS = (
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.7-code",
    "qwen/qwen3.7-max",
)

EXPECTED_PROPOSERS = list(EXPECTED_MODELS)
EXPECTED_AGGREGATOR = "z-ai/glm-5.2"
EXPECTED_JUDGE = "google/gemini-3.1-pro-preview"


def number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def iter_usage_calls(usage: Any, *, phase: str) -> Iterable[dict[str, Any]]:
    if not isinstance(usage, dict):
        return
    breakdown = usage.get("model_usage_breakdown")
    if isinstance(breakdown, list) and breakdown:
        for item in breakdown:
            if isinstance(item, dict):
                yield {**item, "phase": phase}
        return
    if usage.get("model"):
        yield {
            "phase": phase,
            "role": phase,
            "provider": "openrouter",
            **usage,
        }


def generation_usages(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
    execution = row.get("execution")
    attempts = execution.get("generation_attempts") if isinstance(execution, dict) else None
    emitted = False
    if isinstance(attempts, list):
        for attempt in attempts:
            run = attempt.get("run") if isinstance(attempt, dict) else None
            usage = run.get("usage") if isinstance(run, dict) else None
            if isinstance(usage, dict):
                emitted = True
                yield usage
    if not emitted and isinstance(row.get("usage"), dict):
        yield row["usage"]


def judge_usages(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
    judge = row.get("judge")
    if not isinstance(judge, dict):
        return
    judgments = judge.get("criterion_judgments")
    if not isinstance(judgments, list):
        return
    for judgment in judgments:
        if not isinstance(judgment, dict):
            continue
        attempts = judgment.get("judge_attempts")
        if isinstance(attempts, list) and attempts:
            for attempt in attempts:
                run = attempt.get("run") if isinstance(attempt, dict) else None
                usage = run.get("usage") if isinstance(run, dict) else None
                if isinstance(usage, dict):
                    yield usage
        else:
            run = judgment.get("judge_run")
            usage = run.get("usage") if isinstance(run, dict) else None
            if isinstance(usage, dict):
                yield usage


def aggregate(calls: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "billable_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "billed_cost_usd": 0.0,
            "positive_cost_calls": 0,
            "zero_cost_calls": 0,
            "nonbillable_zero_usage_calls": 0,
            "unbilled_usage_calls": 0,
            "anomalous_zero_cost_calls": 0,
            "positive_provider_billed_calls": 0,
            "cost_sources": Counter(),
            "roles": Counter(),
        }
    )
    for call in calls:
        model = str(call.get("model") or "<unknown>")
        row = stats[model]
        row["calls"] += 1
        token_values = {
            key: int(number(call.get(key)))
            for key in (
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cached_tokens",
                "cache_write_tokens",
            )
        }
        for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
            row[key] += token_values[key]
        cost = number(call.get("billed_cost"))
        cost_source = str(call.get("cost_source") or "none")
        has_usage = any(value > 0 for value in token_values.values())
        nonbillable_placeholder = cost <= 0 and not has_usage and cost_source == "none"
        row["billed_cost_usd"] += cost
        row["positive_cost_calls"] += int(cost > 0)
        row["zero_cost_calls"] += int(cost <= 0)
        row["billable_calls"] += int(not nonbillable_placeholder)
        row["nonbillable_zero_usage_calls"] += int(nonbillable_placeholder)
        row["unbilled_usage_calls"] += int(cost <= 0 and has_usage)
        row["anomalous_zero_cost_calls"] += int(cost <= 0 and not nonbillable_placeholder)
        row["positive_provider_billed_calls"] += int(
            cost > 0 and cost_source == "provider_billed"
        )
        row["cost_sources"][cost_source] += 1
        row["roles"][str(call.get("role") or call.get("phase") or "unknown")] += 1
    clean: dict[str, dict[str, Any]] = {}
    for model, row in sorted(stats.items()):
        clean[model] = {
            **row,
            "billed_cost_usd": round(row["billed_cost_usd"], 9),
            "cost_sources": dict(sorted(row["cost_sources"].items())),
            "roles": dict(sorted(row["roles"].items())),
        }
    return clean


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON on line {line_number}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def markdown(report: dict[str, Any]) -> str:
    config = report.get("configuration_summary") or {}
    runner = config.get("runner") or {}
    judge = config.get("judge") or {}
    proposer_names = ", ".join(config.get("proposers") or EXPECTED_PROPOSERS)
    lines = [
        "# DRACO Ensemble Summary — B2 新 Key 完整配置重跑",
        "",
        f"Raw JSONL: `{report['source_jsonl']}`",
        f"Trace JSONL: `{report.get('trace_jsonl')}`",
        f"Effective config: `{report['effective_config']}`",
        f"Strict audit: `{report.get('output_json', 'cost-audit.json')}`",
        "",
        "## 1. 实验结论",
        "",
        f"- 严格审计：**{'通过' if report['pass'] else '未通过'}**",
        "- 实验组：`B2`",
        f"- 任务覆盖：{report['unique_tasks']}/{report['expected_tasks']}",
        f"- 成功任务：{report['completed_tasks']}/{report['expected_tasks']}",
        f"- 重复任务：{report['duplicate_tasks']}",
        f"- 未知用量记录：{report['usage_unknown_count']}",
        f"- 总实付成本：${report['total_billed_cost_usd']:.9f}",
        "",
        "## 2. 实验配置",
        "",
        "- 任务集：DRACO mini（10 题）",
        "- 运行组：B2（4 proposer + 1 aggregator）",
        f"- Proposer：{proposer_names}",
        f"- Aggregator：{config.get('aggregator') or EXPECTED_AGGREGATOR}",
        f"- Judge：{judge.get('model') or EXPECTED_JUDGE}（repeats={judge.get('repeats')}）",
        f"- 工具模式：`{config.get('tool_mode')}`",
        f"- Runner：`{runner.get('mode')}`",
        f"- Agent 最大迭代：{runner.get('agent_max_iterations')}",
        f"- 并发：{runner.get('concurrency')}",
        "",
        "## 3. 实验成绩",
        "",
    ]
    metrics = report.get("metrics")
    if metrics:
        lines.extend(
            [
                (
                    "| Group | Rows | Done | Avg Quality | AvgQ Scored | Avg Pass | "
                    "Judge Err | Avg Gen $ | Avg Visible | Avg Reason | Avg Tokens | "
                    "Avg Tools | Tool % | Avg Steps | Avg LLM Req | p50 ms | p95 ms |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
                ),
                (
                    f"| B2 | {metrics['rows']} | {metrics['completed']} | "
                    f"{metrics['avg_quality']:.2f} | {metrics['avg_quality_scored']:.2f} | "
                    f"{metrics['avg_pass_rate']:.2f}% | {metrics['judge_errors']} | "
                    f"{metrics['avg_cost_usd']:.9f} | {metrics['avg_visible_tokens']:.1f} | "
                    f"{metrics['avg_reasoning_tokens']:.1f} | {metrics['avg_total_tokens']:.1f} | "
                    f"{metrics['avg_tool_calls']:.1f} | {metrics['tool_call_rate_pct']:.1f}% | "
                    f"{metrics['avg_trajectory_steps']:.1f} | {metrics['avg_llm_requests']:.1f} | "
                    f"{metrics['latency_p50_ms']:.0f} | {metrics['latency_p95_ms']:.0f} |"
                ),
                "",
                f"- 评分覆盖率：{metrics['score_coverage_pct']:.2f}%",
                f"- 生成延迟 P50/P95：{metrics['latency_p50_ms'] / 1000:.2f} / "
                f"{metrics['latency_p95_ms'] / 1000:.2f} 秒",
            ]
        )
    else:
        lines.append("未提供汇总指标文件。")
    lines.extend([
        "",
        "## 4. 成本汇总",
        "",
        f"- 生成阶段实付成本：${report['generation_billed_cost_usd']:.9f}",
        f"- 平均每题生成成本（不含 Judge）：${report['average_generation_cost_per_task_usd']:.9f}",
        f"- Judge 实付成本：${report['judge_billed_cost_usd']:.9f}",
        f"- 平均每题 Judge 成本：${report['average_judge_cost_per_task_usd']:.9f}",
        f"- 平均每题总成本：${report['average_total_cost_per_task_usd']:.9f}",
        f"- Judge 成本占比：{report['judge_cost_share_pct']:.2f}%",
    ])
    if report.get("account_usage_delta_usd") is not None:
        lines.extend(
            [
                f"- OpenRouter 账户用量增量：${report['account_usage_delta_usd']:.9f}",
                f"- 账单对账差额：${report['account_cost_difference_usd']:.9f}",
                f"- OpenRouter BYOK 用量增量：${report['account_byok_usage_delta_usd']:.9f}",
            ]
        )
    lines.extend([
        "",
        "## 5. Agent Loop 执行证据",
        "",
        (
            f"- 每轮结构：{report['ensemble_calls_per_iteration']} 次模型调用"
            "（4 proposer + 1 aggregator）"
        ),
        (
            f"- 总生成模型请求：{report['generation_call_count']} 次；平均每题："
            f"{report['average_llm_requests_per_task']:.1f} 次"
        ),
        f"- 平均 ensemble 轮数：{report['average_ensemble_iterations_per_task']:.1f} 轮/题",
        f"- 进入第 2 轮及以上的任务：{report['multi_iteration_tasks']}/{report['expected_tasks']}",
        (
            f"- 单题轮数范围：{report['min_ensemble_iterations']}–"
            f"{report['max_ensemble_iterations']} 轮"
        ),
        (
            f"- 工具调用：总计 {report['total_tool_calls']} 次，平均 "
            f"{report['average_tool_calls_per_task']:.1f} 次/题"
        ),
        "",
        (
            "| Task ID | LLM 请求 | Ensemble 轮数 | 工具调用 | 质量分 | "
            "生成成本（不含 Judge） | 总耗时（秒） |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for task in report["task_summaries"]:
        lines.append(
            f"| `{task['task_id']}` | {task['llm_request_count']} | "
            f"{task['ensemble_iterations']:.0f} | {task['tool_call_count']} | "
            f"{task['quality_total']:.2f} | ${task['generation_cost_usd']:.9f} | "
            f"{task['total_elapsed_ms'] / 1000:.2f} |"
        )
    lines.extend([
        "",
        "## 6. 生成阶段按模型统计",
        "",
        (
            "| 模型 | 记录 | 计费调用 | 正费用 | 零用量占位 | 未计费 Tokens 调用 | "
            "输入 Tokens | 输出 Tokens | 推理 Tokens | 实付成本 | cost_source | 结论 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    model_checks = report["model_checks"]
    for model, stats in report["generation_models"].items():
        source = ", ".join(f"{k}:{v}" for k, v in stats["cost_sources"].items())
        verdict = "通过" if model_checks.get(model, {}).get("pass") else "未通过"
        lines.append(
            f"| `{model}` | {stats['calls']} | {stats['billable_calls']} | "
            f"{stats['positive_cost_calls']} | {stats['nonbillable_zero_usage_calls']} | "
            f"{stats['unbilled_usage_calls']} | {stats['input_tokens']} | "
            f"{stats['output_tokens']} | {stats['reasoning_tokens']} | "
            f"${stats['billed_cost_usd']:.9f} | {source} | {verdict} |"
        )
    lines.extend(["", "## 7. Judge 阶段按模型统计", ""])
    if report["judge_models"]:
        lines.extend(
            [
                "| 模型 | 调用 | 正费用 | 零费用 | 实付成本 | cost_source |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for model, stats in report["judge_models"].items():
            source = ", ".join(f"{k}:{v}" for k, v in stats["cost_sources"].items())
            lines.append(
                f"| `{model}` | {stats['calls']} | {stats['positive_cost_calls']} | "
                f"{stats['zero_cost_calls']} | ${stats['billed_cost_usd']:.9f} | {source} |"
            )
    else:
        lines.append("未发现 Judge 用量记录。")
    lines.extend(
        [
            "",
            f"- 唯一评分 criterion：{report['judge_unique_criterion_count']} 个",
            (
                f"- repeats={report['judge_repeats']} 展开后的基础调用："
                f"{report['judge_baseline_call_count']} 次"
            ),
            f"- 解析失败/空结果触发的额外重试：{report['judge_retry_call_count']} 次",
            "- Judge 调用按 criterion × repeat 计数，不是同一请求重复累计。",
        ]
    )
    lines.extend(["", "## 8. 严格校验", ""])
    for check in report["checks"]:
        lines.append(f"- {'✅' if check['pass'] else '❌'} {check['name']}: {check['detail']}")
    lines.extend(
        [
            "",
            "## 9. 口径说明",
            "",
            (
                "- `非计费零用量占位` 指 Tokens 全为 0、费用为 0、"
                "`cost_source=none` 的内部占位记录；它没有形成 OpenRouter 计费调用。"
            ),
            "- 严格校验只允许上述占位为零费用；任何含 Tokens 但费用为 0 的调用都会判定为失败。",
            "- 总成本同时与 OpenRouter Key 账户用量增量对账；差额必须在配置容差内。",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_jsonl", type=Path)
    parser.add_argument("--expected-tasks", type=int, default=10)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--account-usage-delta-usd", type=float)
    parser.add_argument("--account-byok-usage-delta-usd", type=float)
    parser.add_argument("--account-cost-tolerance-usd", type=float, default=0.000001)
    parser.add_argument("--expected-input-jsonl", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--effective-config", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--expected-agent-max-iterations", type=int, default=1)
    parser.add_argument("--expected-concurrency", type=int, default=5)
    parser.add_argument("--expected-judge-repeats", type=int, default=1)
    parser.add_argument("--expected-judge-concurrency", type=int, default=3)
    parser.add_argument("--expected-tool-mode", default="provider_only")
    parser.add_argument("--reference-effective-config", type=Path)
    parser.add_argument("--account-before", type=Path)
    parser.add_argument("--account-after", type=Path)
    args = parser.parse_args()

    account_before = None
    account_after = None
    if args.account_before or args.account_after:
        if not args.account_before or not args.account_after:
            parser.error("--account-before and --account-after must be provided together")
        account_before = json.loads(args.account_before.read_text(encoding="utf-8"))
        account_after = json.loads(args.account_after.read_text(encoding="utf-8"))
        args.account_usage_delta_usd = number(account_after.get("usage")) - number(
            account_before.get("usage")
        )
        args.account_byok_usage_delta_usd = number(
            account_after.get("byok_usage")
        ) - number(account_before.get("byok_usage"))

    rows = load_rows(args.result_jsonl)
    b2_rows = [row for row in rows if row.get("group") == "B2"]
    task_ids = [str(row.get("task_id") or "") for row in b2_rows]
    task_counts = Counter(task_ids)
    duplicates = sum(count - 1 for count in task_counts.values() if count > 1)
    completed = sum(bool(row.get("final_text")) and not row.get("error") for row in b2_rows)
    usage_unknown = sum(int(number(row.get("usage_unknown_count"))) for row in b2_rows)
    expected_task_ids: set[str] | None = None
    expected_prompts: dict[str, str] = {}
    if args.expected_input_jsonl:
        expected_rows = load_rows(args.expected_input_jsonl)
        for row in expected_rows:
            task_id = str(row.get("task_id") or row.get("id") or "")
            if task_id:
                expected_prompts[task_id] = str(
                    row.get("prompt") if row.get("prompt") is not None else row.get("problem") or ""
                )
        expected_task_ids = set(expected_prompts)
        expected_task_ids.discard("")
    actual_task_ids = set(task_counts)
    missing_task_ids = sorted((expected_task_ids or set()) - actual_task_ids)
    unexpected_task_ids = sorted(actual_task_ids - (expected_task_ids or actual_task_ids))
    prompt_mismatch_task_ids = []
    if expected_prompts:
        for row in b2_rows:
            task_id = str(row.get("task_id") or "")
            expected_prompt = expected_prompts.get(task_id)
            if expected_prompt is None:
                continue
            expected_sha256 = hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest()
            if (
                str(row.get("prompt") or "") != expected_prompt
                or str(row.get("prompt_sha256") or "") != expected_sha256
            ):
                prompt_mismatch_task_ids.append(task_id)
        prompt_mismatch_task_ids.sort()

    generation_calls = []
    judge_calls = []
    judge_judgment_count = 0
    for row in b2_rows:
        for usage in generation_usages(row):
            generation_calls.extend(iter_usage_calls(usage, phase="generation"))
        judge = row.get("judge")
        if isinstance(judge, dict) and isinstance(judge.get("criterion_judgments"), list):
            judge_judgment_count += len(judge["criterion_judgments"])
        for usage in judge_usages(row):
            judge_calls.extend(iter_usage_calls(usage, phase="judge"))

    generation_models = aggregate(generation_calls)
    judge_models = aggregate(judge_calls)
    model_checks = {}
    checks = [
        {
            "name": "仅运行 B2",
            "pass": len(b2_rows) == len(rows),
            "detail": f"B2 rows={len(b2_rows)}, all rows={len(rows)}",
        },
        {
            "name": "DRACO mini 任务覆盖",
            "pass": len(task_counts) == args.expected_tasks,
            "detail": f"unique={len(task_counts)}, expected={args.expected_tasks}",
        },
        {
            "name": "所有任务成功",
            "pass": completed == args.expected_tasks,
            "detail": f"completed={completed}, expected={args.expected_tasks}",
        },
        {
            "name": "无重复任务",
            "pass": duplicates == 0,
            "detail": f"duplicates={duplicates}",
        },
        {
            "name": "无未知用量",
            "pass": usage_unknown == 0,
            "detail": f"usage_unknown_count={usage_unknown}",
        },
    ]
    if expected_task_ids is not None:
        checks.append(
            {
                "name": "任务 ID 与 DRACO mini 输入完全一致",
                "pass": not missing_task_ids and not unexpected_task_ids,
                "detail": (
                    f"expected={len(expected_task_ids)}, actual={len(actual_task_ids)}, "
                    f"missing={len(missing_task_ids)}, unexpected={len(unexpected_task_ids)}"
                ),
            }
        )
        checks.append(
            {
                "name": "任务 Prompt 与 DRACO mini 输入及 SHA 完全一致",
                "pass": not prompt_mismatch_task_ids,
                "detail": f"mismatches={len(prompt_mismatch_task_ids)}",
            }
        )

    manifest = None
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        manifest_pass = bool(
            manifest.get("status") == "complete"
            and manifest.get("groups") == ["B2"]
            and int(number(manifest.get("rows_written"))) == args.expected_tasks
            and int(number(manifest.get("task_count"))) == args.expected_tasks
        )
        checks.append(
            {
                "name": "Manifest 完整",
                "pass": manifest_pass,
                "detail": (
                    f"status={manifest.get('status')}, groups={manifest.get('groups')}, "
                    f"rows_written={manifest.get('rows_written')}, "
                    f"task_count={manifest.get('task_count')}"
                ),
            }
        )

    effective_config = None
    configuration_summary = None
    if args.effective_config:
        effective_config = json.loads(args.effective_config.read_text(encoding="utf-8"))
        ensemble = effective_config.get("ensemble") or {}
        runner = effective_config.get("runner") or {}
        judge = effective_config.get("judge") or {}
        tools = effective_config.get("tools") or {}
        proposers = [
            str(item.get("model"))
            for item in ensemble.get("proposers", [])
            if isinstance(item, dict)
        ]
        aggregator = (ensemble.get("aggregator") or {}).get("model")
        configuration_summary = {
            "profile_id": effective_config.get("profile_id"),
            "group": effective_config.get("group"),
            "proposers": proposers,
            "aggregator": aggregator,
            "runner": runner,
            "judge": judge,
            "tool_mode": tools.get("mode"),
        }
        config_pass = bool(
            effective_config.get("profile_id") == "opensquilla_g12_20260630"
            and effective_config.get("group") == "B2"
            and proposers == EXPECTED_PROPOSERS
            and aggregator == EXPECTED_AGGREGATOR
            and runner.get("mode") == "agent_loop"
            and int(number(runner.get("agent_max_iterations")))
            == args.expected_agent_max_iterations
            and int(number(runner.get("concurrency"))) == args.expected_concurrency
            and judge.get("model") == EXPECTED_JUDGE
            and int(number(judge.get("repeats"))) == args.expected_judge_repeats
            and int(number(judge.get("concurrency"))) == args.expected_judge_concurrency
            and tools.get("mode") == args.expected_tool_mode
        )
        checks.append(
            {
                "name": "模型映射与运行配置正确",
                "pass": config_pass,
                "detail": (
                    f"profile={effective_config.get('profile_id')}, "
                    f"proposers={proposers}, aggregator={aggregator}, "
                    f"runner={runner.get('mode')}/max_iter={runner.get('agent_max_iterations')}"
                    f"/concurrency={runner.get('concurrency')}, "
                    f"judge={judge.get('model')}/repeats={judge.get('repeats')}"
                    f"/concurrency={judge.get('concurrency')}, "
                    f"tool_mode={tools.get('mode')}"
                ),
            }
        )

        if args.reference_effective_config:
            reference_effective_config = json.loads(
                args.reference_effective_config.read_text(encoding="utf-8")
            )
            exact_config_match = effective_config == reference_effective_config
            differing_top_level_keys = sorted(
                key
                for key in set(effective_config) | set(reference_effective_config)
                if effective_config.get(key) != reference_effective_config.get(key)
            )
            checks.append(
                {
                    "name": "有效配置与 routing-full B2 完全一致",
                    "pass": exact_config_match,
                    "detail": (
                        "exact_match=true"
                        if exact_config_match
                        else f"differing_top_level_keys={differing_top_level_keys}"
                    ),
                }
            )

    metrics = None
    if args.summary:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        metrics = ((summary.get("groups") or {}).get("B2") or {})
        summary_pass = bool(
            int(number(metrics.get("rows"))) == args.expected_tasks
            and int(number(metrics.get("completed"))) == args.expected_tasks
            and int(number(metrics.get("scored_rows"))) == args.expected_tasks
            and number(metrics.get("score_coverage_pct")) == 100.0
            and int(number(metrics.get("judge_errors"))) == 0
        )
        checks.append(
            {
                "name": "评分汇总完整",
                "pass": summary_pass,
                "detail": (
                    f"rows={metrics.get('rows')}, completed={metrics.get('completed')}, "
                    f"scored={metrics.get('scored_rows')}, "
                    f"coverage={metrics.get('score_coverage_pct')}%, "
                    f"judge_errors={metrics.get('judge_errors')}"
                ),
            }
        )
    for model in EXPECTED_MODELS:
        stats = generation_models.get(model)
        passed = bool(
            stats
            and stats["calls"] > 0
            and stats["billable_calls"] > 0
            and stats["unbilled_usage_calls"] == 0
            and stats["anomalous_zero_cost_calls"] == 0
            and stats["positive_cost_calls"] == stats["billable_calls"]
            and stats["positive_provider_billed_calls"] == stats["billable_calls"]
        )
        detail = "missing"
        if stats:
            detail = (
                f"calls={stats['calls']}, positive={stats['positive_cost_calls']}, "
                f"billable={stats['billable_calls']}, "
                f"zero_usage_placeholders={stats['nonbillable_zero_usage_calls']}, "
                f"unbilled_usage={stats['unbilled_usage_calls']}, "
                f"sources={stats['cost_sources']}, "
                f"cost=${stats['billed_cost_usd']:.9f}"
            )
        model_checks[model] = {"pass": passed, "detail": detail}
        checks.append({"name": f"{model} 费用完整", "pass": passed, "detail": detail})

    generation_cost = round(
        sum(item["billed_cost_usd"] for item in generation_models.values()), 9
    )
    judge_cost = round(
        sum(item["billed_cost_usd"] for item in judge_models.values()), 9
    )
    total_cost = round(generation_cost + judge_cost, 9)
    ensemble_calls_per_iteration = len(EXPECTED_PROPOSERS) + 1
    task_summaries = []
    for row in b2_rows:
        llm_request_count = int(number(row.get("llm_request_count")))
        task_summaries.append(
            {
                "task_id": str(row.get("task_id") or ""),
                "llm_request_count": llm_request_count,
                "ensemble_iterations": (
                    llm_request_count / ensemble_calls_per_iteration
                    if ensemble_calls_per_iteration
                    else 0.0
                ),
                "tool_call_count": int(number(row.get("total_tool_call_count"))),
                "quality_total": number(row.get("quality_total")),
                "generation_cost_usd": number(
                    row.get("generation_attempt_total_billed_cost")
                ),
                "total_elapsed_ms": int(number(row.get("total_elapsed_ms"))),
            }
        )
    task_summaries.sort(key=lambda item: item["task_id"])
    iteration_counts = [item["ensemble_iterations"] for item in task_summaries]
    judge_repeats = int(number((configuration_summary or {}).get("judge", {}).get("repeats")))
    judge_unique_criterion_count = (
        judge_judgment_count // judge_repeats if judge_repeats else judge_judgment_count
    )
    judge_baseline_call_count = judge_judgment_count
    account_difference = None
    if args.account_usage_delta_usd is not None:
        account_difference = round(total_cost - args.account_usage_delta_usd, 9)
        checks.append(
            {
                "name": "OpenRouter 账户成本对账",
                "pass": abs(account_difference) <= args.account_cost_tolerance_usd,
                "detail": (
                    f"recorded=${total_cost:.9f}, "
                    f"account_delta=${args.account_usage_delta_usd:.9f}, "
                    f"difference=${account_difference:.9f}, "
                    f"tolerance=${args.account_cost_tolerance_usd:.9f}"
                ),
            }
        )
    if args.account_byok_usage_delta_usd is not None:
        checks.append(
            {
                "name": "OpenRouter BYOK 用量为零",
                "pass": abs(args.account_byok_usage_delta_usd) <= args.account_cost_tolerance_usd,
                "detail": f"byok_usage_delta=${args.account_byok_usage_delta_usd:.9f}",
            }
        )

    report = {
        "pass": all(check["pass"] for check in checks),
        "source_jsonl": str(args.result_jsonl),
        "expected_tasks": args.expected_tasks,
        "rows": len(rows),
        "unique_tasks": len(task_counts),
        "completed_tasks": completed,
        "duplicate_tasks": duplicates,
        "usage_unknown_count": usage_unknown,
        "expected_input_jsonl": (
            str(args.expected_input_jsonl) if args.expected_input_jsonl else None
        ),
        "missing_task_ids": missing_task_ids,
        "unexpected_task_ids": unexpected_task_ids,
        "prompt_mismatch_task_ids": prompt_mismatch_task_ids,
        "manifest": str(args.manifest) if args.manifest else None,
        "effective_config": str(args.effective_config) if args.effective_config else None,
        "reference_effective_config": (
            str(args.reference_effective_config)
            if args.reference_effective_config
            else None
        ),
        "configuration_summary": configuration_summary,
        "summary": str(args.summary) if args.summary else None,
        "metrics": metrics,
        "generation_call_count": len(generation_calls),
        "judge_call_count": len(judge_calls),
        "judge_judgment_count": judge_judgment_count,
        "judge_unique_criterion_count": judge_unique_criterion_count,
        "judge_repeats": judge_repeats,
        "judge_baseline_call_count": judge_baseline_call_count,
        "judge_retry_call_count": max(0, len(judge_calls) - judge_baseline_call_count),
        "generation_billed_cost_usd": generation_cost,
        "judge_billed_cost_usd": judge_cost,
        "total_billed_cost_usd": total_cost,
        "average_generation_cost_per_task_usd": round(
            generation_cost / args.expected_tasks, 9
        ),
        "average_judge_cost_per_task_usd": round(
            judge_cost / args.expected_tasks, 9
        ),
        "average_total_cost_per_task_usd": round(total_cost / args.expected_tasks, 9),
        "ensemble_calls_per_iteration": ensemble_calls_per_iteration,
        "average_llm_requests_per_task": round(
            len(generation_calls) / args.expected_tasks, 6
        ),
        "average_ensemble_iterations_per_task": round(
            len(generation_calls) / ensemble_calls_per_iteration / args.expected_tasks, 6
        ),
        "min_ensemble_iterations": min(iteration_counts, default=0.0),
        "max_ensemble_iterations": max(iteration_counts, default=0.0),
        "multi_iteration_tasks": sum(value > 1 for value in iteration_counts),
        "total_tool_calls": sum(item["tool_call_count"] for item in task_summaries),
        "average_tool_calls_per_task": round(
            sum(item["tool_call_count"] for item in task_summaries)
            / args.expected_tasks,
            6,
        ),
        "task_summaries": task_summaries,
        "judge_cost_share_pct": round(100.0 * judge_cost / total_cost, 6) if total_cost else 0.0,
        "account_usage_delta_usd": args.account_usage_delta_usd,
        "account_byok_usage_delta_usd": args.account_byok_usage_delta_usd,
        "account_cost_difference_usd": account_difference,
        "account_cost_tolerance_usd": args.account_cost_tolerance_usd,
        "account_before": str(args.account_before) if args.account_before else None,
        "account_after": str(args.account_after) if args.account_after else None,
        "generation_models": generation_models,
        "judge_models": judge_models,
        "model_checks": model_checks,
        "checks": checks,
    }

    output_json = args.output_json or args.result_jsonl.with_name("cost-audit.json")
    output_md = args.output_md or args.result_jsonl.with_name("EXPERIMENT_RESULTS.md")
    report["output_json"] = str(output_json)
    report["output_md"] = str(output_md)
    trace_candidates = sorted(args.result_jsonl.parent.glob("*.trace.jsonl"))
    report["trace_jsonl"] = str(trace_candidates[0]) if trace_candidates else None
    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_md.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
