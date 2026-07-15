# DRACO B2 / OpenSquilla G12 Alignment

`B2` loads [`configs/benchmarks/draco_b2_g12.json`](../../configs/benchmarks/draco_b2_g12.json)
by default. The file reproduces the scored OpenSquilla `G12` run from source commit
`153e5ff267950b0e285efcdb180cea8724c0471d`.

## Effective baseline

| Setting | B2 / reference G12 |
| --- | --- |
| Proposers | DeepSeek V4 Pro, GLM 5.2, Kimi K2.7 Code, Qwen 3.7 Max |
| Aggregator | GLM 5.2 |
| Thinking | `xhigh`, `xhigh`, `max`, `xhigh`; aggregator `xhigh` |
| Completion cap | 16,384 tokens per member |
| Temperature | 0.0 per member |
| Tool permissions | proposers disabled; aggregator enabled |
| Local tools | Brave `web_search` plus `web_fetch` |
| Proposer completion rule | wait for all four; one success is enough to aggregate |
| Timeouts | task 3600s; proposer 907.5s; aggregator 2662.5s; margin 30s |
| Runner | Agent loop, 12 iterations, global concurrency 2 |
| Judge | Gemini 3.1 Pro Preview, 3 repeats, concurrency 6, 3 attempts |
| Generation retries | 3 attempts, 2s initial backoff |

The proposers do not execute research tools in the reference experiment. The aggregator
receives `web_search` and `web_fetch`; a tool request is surfaced to the outer Agent loop,
which executes it and calls the ensemble again with the result.

## Differences fixed from the earlier B2 run

The July 15 B2 result was not execution-equivalent to G12 even though its model names matched:

| Setting | Earlier B2 | Reference G12 / aligned B2 |
| --- | --- | --- |
| Single-model routing before ensemble | enabled | skipped |
| Successful proposers required | 3 | 1 |
| Proposer completion | 3 successes plus 30s grace | wait for all 4 |
| Proposer timeout | 300s | 907.5s |
| Aggregator timeout | 480s | 2662.5s |
| Kimi native thinking request | degraded from `max` | preserved as `max` |

These are behavioral differences, not reporting-only changes. In particular, the earlier B2
trace contains three-candidate aggregation calls when a slower proposer did not finish inside
the quorum window; G12's implementation used `asyncio.gather` and waited for every proposer.

## Overrides

Resolution order is deterministic:

1. Base JSON (`--experiment-config`, or the bundled file)
2. Each repeated `--experiment-config-override` JSON, in command-line order
3. Each repeated `--experiment-config-set dotted.path=JSON_VALUE`, in command-line order

Examples:

```bash
--experiment-config-override configs/benchmarks/my-b2-overlay.json
--experiment-config-set runner.concurrency=4
--experiment-config-set ensemble.proposers.2.max_tokens=8192
```

`OPENSQUILLA_DRACO_EXPERIMENT_CONFIG` can supply the base JSON path. Unknown JSON fields,
unknown dotted paths, inconsistent timeout budgets, and accidental thinking downgrades fail
before any model request. To deliberately test lower thinking, first set
`generation.require_highest_thinking=false` and then override the member setting.

For B2 model calls, `ensemble.proposers[*]` and `ensemble.aggregator` are the authoritative
member settings: their `max_tokens` and `thinking` values override the shared generation
defaults, and a non-null member `temperature` does the same. The shared
`generation.thinking_budget_tokens` and retry settings still apply to every member. Change a
specific B2 model through its `ensemble` path; the effective artifact and routing trace record
the resolved per-member values.

## Run artifacts

Every B2 output directory contains:

- `*.experiment-config.base.json`: parsed base input
- `*.experiment-config.override-NN.json`: every file overlay, when supplied
- `*.experiment-config.inline-overrides.json`: inline overrides, when supplied
- `*.experiment-config.effective.json`: fully merged and validated runtime configuration
- `*.experiment-config.resolution.json`: source paths, SHA-256 hashes, precedence, and input check

The manifest references all of these files and includes the requested CLI values, effective
values, reference source commit, and DRACO mini input hash verification.

## Reproduction boundary

The runner locks the benchmark input, model lineup, generation settings, tool policy, quorum,
timeouts, runner, retry, and judge settings that affected G12. Credentials remain external and
are never written to the JSON artifacts. Sandbox posture and provider transport come from the
selected OpenSquilla TOML config; the reference and current comparison both use the same config.

Exact score equality still cannot be guaranteed. OpenRouter aliases can resolve to a different
dated backend snapshot, provider-side serving behavior can change, and running a different mix
of experiment groups changes concurrent provider load. The manifest and request trace preserve
the resolved model names returned by the provider so that drift is visible after a run.
