# Selection-Gated Forking For Budgeted Agentic Runtime Optimization

Date: 2026-06-07

Status: research proposal for review

## Decision Needed

OpenSquilla maintainers should decide whether to accept this as a research
direction for a first offline experiment. The recommended decision is to approve
Phase 1 only: a documentation-and-harness prototype that replays fixed task
packets against named configurations and produces reviewable evidence bundles.

Do not approve autonomous self-modification, automatic branch promotion, or
production routing changes from this paper alone. Those require later pull
requests with tests, reviewer sign-off, and explicit maintainer approval.

## Abstract

This paper proposes a bounded evolutionary protocol for improving an agentic
runtime such as OpenSquilla. The core mechanism is paired forking: two or more
near-identical candidate systems receive the same goal, environment packet,
budget, constraints, and evaluation harness, then compete for promotion based on
measured product gain. Winning changes may be promoted as a branch, or
transplanted as a reusable module when the benefit is local to a subsystem.

The proposal treats "fitness" as a deterministic value signal tied to
OpenSquilla's product goal: higher task success and grounded action at lower
cost, lower state debt, and no loss of safety, legality, auditability, or
operator control. It borrows the structure of evolutionary algorithms,
sequential experimental design, and autonomic computing, but it is not a claim
that software systems literally obey biological evolution or thermodynamics.
Those are design analogies; the operational object is an auditable optimization
loop.

## Motivation

OpenSquilla already has product surfaces that make this idea plausible:

- SquillaRouter chooses model tiers to improve cost per useful turn.
- Tool compression preserves large raw results while projecting compact
  model-visible previews.
- Durable sessions, cost accounting, diagnostics, replay, approvals, skills,
  subagents, memory, and scheduled work create the trace substrate needed for
  controlled experiments.

The missing research question is whether a runtime can improve itself through
bounded, reviewable, budget-aware competition between variants without becoming
unbounded, self-selecting, unsafe, or expensive.

The proposed answer is not "let the agent freely rewrite itself." The proposed
answer is a disciplined evolutionary harness:

1. Define a product goal and measurement window.
2. Fork controlled candidate variants.
3. Feed each fork the same task diet and budget.
4. Measure realized gain, debt, and safety.
5. Promote only changes that pass hard gates.
6. Archive non-winners as an expanding comparator set.

## Options Considered

| Option | Description | Strengths | Weaknesses | Recommendation |
| --- | --- | --- | --- | --- |
| Static manual tuning | Maintainers inspect traces and manually tune router, compression, memory, or approval behavior. | Lowest process overhead; familiar review path. | Hard to compare alternatives fairly; weak accumulation of failed experiments; reviewer memory becomes the system of record. | Keep as baseline and fallback. |
| Single-candidate eval | One proposed change runs against a fixed benchmark and is accepted or rejected. | Simple to implement; easy to explain in pull requests. | Does not expose opportunity cost versus another plausible candidate; can overfit to the selected change. | Use for small fixes, not this research track. |
| Selection-gated paired forking | Two or more controlled candidates receive the same packet, budget, and eval, then compete for promotion, transplant, archive, or retirement. | Best fit for measuring cost-per-success, state debt, and reusable knowledge under comparable conditions. | More orchestration overhead; requires careful reviewer independence and holdout control. | Recommended first research direction, limited to offline harness. |
| Open-ended self-improvement | The runtime chooses goals, rewrites itself, and promotes changes autonomously. | Maximizes autonomy in theory. | Fails safety, audit, budget, and branch-authority gates; invites metric gaming and state debt. | Reject. |

The recommendation is paired forking because it is the smallest option that
tests the core hypothesis while preserving human branch authority and public
contributor safety.

## Definitions

### Environment Packet

The environment packet is the bounded input state a fork is allowed to see for a
cycle:

- task goal and acceptance criteria
- current repo state or session state
- allowed tools and denied tools
- cost, token, wall-clock, and tool-call budgets
- prior accepted knowledge, if any
- safety, legal, privacy, and operator constraints
- evaluation harness and blinded holdout tasks

No fork may add hidden information to its own packet. Extra context is a budgeted
resource, not a free advantage.

### Dietary Budget

The dietary budget is the maximum context and action substrate a fork may ingest
or spend during a cycle:

- input tokens
- output tokens
- tool calls
- wall-clock time
- provider cost
- memory reads
- repository files opened
- human interventions

The budget is deliberately framed as a diet because more input is not always
better. Unbounded ingestion can reduce fitness by increasing cost, latency,
attack surface, and state debt.

### Metabolizable Signal

A metabolizable signal is input that can be converted into measurable product
gain inside the current cycle. A signal is not metabolizable if it is too vague,
too stale, unactionable, duplicative, unverifiable, unsafe, or too expensive to
process relative to expected gain.

Examples:

- A failing deterministic test with a minimal reproduction is highly
  metabolizable.
- A huge log dump with no error anchor is weakly metabolizable until compressed
  or indexed.
- A strategy note with no measurement plan is not promotable until it becomes a
  hypothesis and eval.

### State Debt

State debt is persistent complexity created by a change that future cycles must
carry. It includes:

- added prompts, code paths, config flags, skills, memory records, schemas, or
  docs that require upkeep
- hidden coupling between modules
- brittle test fixtures
- behavior that only works because of unrecorded operator knowledge
- saved knowledge that is broad, stale, duplicated, or not tied to evidence

State debt is allowed only when expected future dividend exceeds expected upkeep.
Unpaid debt reduces the candidate's fitness score.

### Branch Status

Branch status is the lifecycle stage of a candidate:

- `seed`: idea captured but not yet testable
- `fork`: isolated candidate running against a cycle
- `contender`: candidate has a complete evidence bundle
- `transplant`: local module or pattern extracted from a candidate
- `promoted`: merged into the main development line
- `archive`: preserved comparator, not governing current behavior
- `retired`: rejected due to low gain, high debt, or gate failure

## Research Questions

1. Can paired candidate forks improve cost per successful task faster than a
   single manually tuned baseline?
2. Does a dietary budget improve signal selection and reduce state debt?
3. Can fork competition accumulate reusable knowledge without unbounded memory
   growth?
4. Can module transplants capture local wins without importing unrelated debt
   from a losing branch?
5. Can hard gates prevent Goodhart-style optimization where candidates exploit
   the metric instead of improving the product?

## Hypotheses

### H1: Paired Forking Improves Cost Per Success

Given identical task packets and budgets, a fork-selection protocol will produce
a lower cost per successful task than a single static policy over repeated
cycles.

Primary metric:

```text
cost_per_success = total_cycle_cost / successful_tasks
```

Promotion condition:

```text
candidate_cost_per_success <= baseline_cost_per_success * 0.90
```

The 10 percent threshold is intentionally conservative for a first experiment.
It can be adjusted after enough observations establish variance.

### H2: Dietary Budgets Improve Grounded Action

Candidates with explicit token, tool, and evidence budgets will show a higher
grounded-action ratio than candidates allowed to ingest context opportunistically.

Primary metric:

```text
grounded_action_ratio = grounded_actions / total_actions
```

A grounded action must have:

- triggering user intent or system goal
- cited source, file, tool result, or observed state
- confidence level or uncertainty note
- expected effect
- rollback or stop condition when side effects exist

### H3: Signal-Gated Memory Accumulates Useful Knowledge

Memory entries admitted only after evidence, reuse target, and expiry review will
improve future task success without increasing irrelevant recall.

Primary metrics:

```text
memory_reuse_rate = used_memory_items / retrieved_memory_items
recall_precision = relevant_retrieved_items / retrieved_memory_items
```

Gate:

```text
accept_memory_item only if evidence_ref and reuse_case and expiry_or_review_date exist
```

### H4: Module Transplant Beats Whole-Branch Promotion For Local Wins

When a candidate wins because of one subsystem improvement, extracting that
subsystem as a transplant will produce lower state debt than merging the whole
branch.

Primary metric:

```text
transplant_value = local_gain - added_state_debt - integration_cost
```

Example modules:

- router policy
- tool-result compressor
- retrieval filter
- approval gate
- eval harness
- prompt section
- skill
- diagnostics report

### H5: Uncontrolled Review Reduces Self-Selection Bias

At least one blinded or adversarial review pass will catch failures that
self-scored candidates miss.

Primary metric:

```text
review_escape_rate = reviewer_found_blockers / self_reported_passes
```

Promotion requires review to be outside the candidate fork's control. The fork
may prepare evidence, but it cannot choose its own holdout tasks or final score.

## Fitness Function

The first protocol should use an interpretable weighted score, not an opaque
model:

```text
fitness =
  0.30 * task_success_delta
+ 0.20 * grounded_action_delta
+ 0.15 * cost_efficiency_delta
+ 0.10 * latency_delta
+ 0.10 * reusable_knowledge_delta
+ 0.10 * operator_load_delta
+ 0.05 * rollback_readiness
- 0.25 * state_debt_delta
- 1.00 * hard_gate_failure
```

Where:

- positive deltas mean improvement over baseline
- negative deltas mean regression
- hard gate failure forces rejection regardless of score
- weights are versioned experimental parameters

The score must be calculated from stored traces, not candidate self-description.

## Hard Gates

A candidate cannot be promoted if any gate fails:

- secrets, credentials, payment, admin, or broad access requires human approval
- destructive external action requires human approval
- public network exposure must preserve auth and network boundary controls
- regulated legal, medical, financial, or security decisions cannot be delegated
  as final autonomous decisions
- default PR checks must remain offline, deterministic, credential-free, and
  safe for forks
- no hidden tests may be rewritten by the candidate under evaluation
- no candidate may suppress audit logs, cost records, or denial ledgers
- no change may reduce existing approval, sandbox, trace, or rollback controls
  without an explicit maintainer decision

## Inference Gate

An inference may affect an action only when it passes this record shape:

```yaml
inference_record:
  trigger: user_intent | scheduled_goal | failing_check | operator_command
  claim: short factual claim or decision
  evidence_ref: file, tool result, test id, issue, trace, or benchmark id
  uncertainty: low | medium | high
  action_enabled: true | false
  expected_gain: measurable expected effect
  risk: safety, cost, privacy, product, or none
  rollback: command, revert path, or stop condition
```

This prevents a candidate from converting vague reasoning into side effects.

## Experimental Protocol

### Cycle 0: Baseline

1. Select a product goal, such as reducing cost per successful long-running repo
   task while preserving quality.
2. Capture baseline runs from the current OpenSquilla configuration.
3. Record success rate, cost, tokens, latency, tool calls, user interventions,
   safety blocks, and state debt.
4. Freeze the evaluation packet and holdout tasks.

### Cycle 1: Paired Fork

Create two candidates from the same baseline:

- Candidate A: router-policy or context-budget change.
- Candidate B: tool-compression or retrieval-filter change.

Each candidate receives the same task packet, dietary budget, and constraints.
Only one intentional variable should differ per candidate.

### Cycle 2: Independent Work

Each candidate runs without seeing the other candidate's trace until both finish.
Each produces:

- patch or configuration diff
- evidence bundle
- test results
- cost record
- state debt estimate
- rollback plan
- transplantable module summary

### Cycle 3: Review And Scoring

A reviewer scores both candidates against the same rubric. The reviewer must use
trace evidence, not persuasive prose.

Required reviewer checks:

- Does the candidate satisfy the original goal?
- Did it stay inside budget?
- Are improvements reproducible?
- Did it touch forbidden surfaces?
- Did it increase state debt?
- Is there a smaller transplant than whole-branch promotion?
- Did it exploit the benchmark instead of improving the product?

### Cycle 4: Promotion, Transplant, Or Archive

Outcomes:

- Promote the whole candidate if it wins broadly and has low debt.
- Transplant the winning module if the gain is localized.
- Archive non-winners as comparators with failure reasons.
- Retire candidates that fail gates.

Every cycle leaves an artifact, evidence, state update, and resume point.

## Minimum Detectable Signal

Promotion should wait until observed gain clears noise:

```text
minimum_detectable_gain = max(absolute_floor, variance_adjusted_floor)
```

Suggested first values:

- absolute cost reduction floor: 10 percent
- task success regression tolerance: 0 percent for critical tasks
- grounded action regression tolerance: 0 percent
- latency regression tolerance: 15 percent unless cost gain is large
- sample size floor: 20 tasks or 5 full replay sessions, whichever is more
  appropriate for the workflow

If sample size is too small, the candidate may become a `contender`, but should
not be promoted.

## Debt-To-Dividend Gate

Each change must justify upkeep:

```text
expected_dividend =
  expected_future_cost_saved
+ expected_future_success_gain
+ expected_future_operator_time_saved

expected_upkeep =
  maintenance_cost
+ cognitive_load
+ test_cost
+ migration_cost
+ failure_recovery_cost
```

Promotion requires:

```text
expected_dividend > expected_upkeep * safety_margin
```

Suggested first safety margin:

```text
safety_margin = 1.5
```

High-debt changes can still be accepted when they unlock a strategic capability,
but that must be a maintainer decision, not an automatic score result.

## Knowledge Accumulation

The protocol should maintain four ledgers:

1. Signal ledger: what was observed and why it mattered.
2. Candidate ledger: what changed in each fork.
3. Evidence ledger: tests, traces, costs, and review findings.
4. Transplant ledger: reusable modules extracted from promoted or losing forks.

Accepted knowledge must be narrow and actionable:

```yaml
knowledge_item:
  claim: one operational lesson
  evidence: trace, test, benchmark, or review id
  applies_to: exact subsystem or workflow
  reuse_when: trigger condition
  do_not_reuse_when: exclusion condition
  review_after: date or version
```

This keeps memory from becoming a junk drawer.

## OpenSquilla Implementation Sketch

The first implementation should be documentation and harness-first, not
self-modifying runtime behavior.

### Phase 1: Offline Harness

- Add a `fork_experiments` plan schema.
- Add a runner that replays fixed task packets against named configurations.
- Store traces, costs, and results under an experiment output directory.
- Require reviewer output before any promotion recommendation.
- Keep all default checks offline and credential-free.

### Phase 2: Product-Surface Experiments

Candidate variables can target:

- SquillaRouter routing thresholds or fallback policy
- tool-compression projection size
- memory retrieval filters
- compaction trigger policy
- approval prompt wording
- diagnostics and replay summaries
- skill loading thresholds

Each experiment changes one variable at a time.

### Phase 3: Controlled Transplants

When a fork wins, extract the smallest reusable artifact:

- code diff
- config profile
- skill
- prompt block
- eval fixture
- docs pattern
- diagnostic report template

The transplant receives its own tests and rollback note.

### Phase 4: Human-Gated Promotion

Promotion to `dev` or release branches remains a human-reviewed repository
event. The system may recommend branch status, but it does not grant itself main
branch authority.

## Execution Ownership

The first experiment needs explicit role separation so candidate systems cannot
choose their own evidence, score, or promotion status.

| Role | Owner placeholder | Responsibilities | Required artifact | Stop condition |
| --- | --- | --- | --- | --- |
| Maintainer sponsor | `OpenSquilla maintainer` | Approves the experiment scope, hard gates, branch target, and whether a candidate may become a PR. | Experiment approval note or issue comment. | Scope touches secrets, payment, destructive actions, public exposure, or production routing. |
| Harness owner | `runtime/evals contributor` | Implements the offline replay runner, schema, trace capture, and deterministic result summary. | `fork_experiments` schema, runner, and focused tests. | Runner needs live provider credentials or nondeterministic network access for default checks. |
| Candidate owner A | `candidate contributor A` | Proposes one bounded variable change and produces evidence for that fork. | Candidate diff plus evidence bundle. | Candidate changes more than one variable or alters evaluator code. |
| Candidate owner B | `candidate contributor B` | Proposes the paired bounded variable change and produces evidence for that fork. | Candidate diff plus evidence bundle. | Candidate sees the other candidate's trace before both complete. |
| Reviewer | `independent reviewer` | Scores both evidence bundles, checks hard gates, and recommends promote, transplant, archive, or retire. | Review rubric with trace-backed scores. | Reviewer cannot access traces, cost records, rollback notes, or holdout results. |
| Release gatekeeper | `maintainer with merge authority` | Decides whether a recommended transplant or candidate becomes a normal pull request. | PR decision and rollback note. | Any 0 score in the review rubric or unresolved hard gate. |

For a first cycle, one person may fill multiple implementation roles only if the
reviewer remains independent from candidate scoring and final branch authority.

## Review Rubric

Reviewers should score each candidate from 0 to 2 on each dimension:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Goal fit | misses goal | partial | satisfies goal |
| Evidence | self-report only | partial trace | reproducible trace |
| Cost | worse | neutral | lower cost per success |
| Grounding | vague actions | partial citations | every action grounded |
| Safety | gate failure | uncertain | gates preserved |
| State debt | high | acceptable | low or reduced |
| Reuse | none | local | transplantable |
| Rollback | absent | manual | tested or obvious |

Promotion requires no 0 scores and an average score of at least 1.5.

## Threats To Validity

- Benchmark overfitting: candidates may optimize for the visible test set.
- Hidden debt: future maintenance cost may not appear in early cycles.
- Reviewer variance: human reviewers may score differently.
- Metric capture: a weighted score may miss product judgment.
- Context inequality: one fork may receive richer accidental context.
- Tool nondeterminism: external services and provider outputs may drift.
- False thermodynamic analogy: entropy language can become misleading if treated
  as proof instead of metaphor.

Mitigations:

- sealed holdout tasks
- replayable traces
- deterministic public tests
- one-variable candidate changes
- blinded review where practical
- explicit state debt ledger
- periodic metric review

## Expected Contributions

If validated, this protocol gives OpenSquilla:

- a disciplined way to compare agent improvements under budget
- a reusable vocabulary for candidate forks, transplants, debt, and dividends
- a promotion path that preserves human authority
- an evaluation frame for memory, routing, compression, and skills
- a defense against unbounded self-improvement claims

## First Review Questions

1. Is the fitness function aligned with OpenSquilla's product goal of same
   budget, more capability, and better results?
2. Which first candidate pair is most useful: router thresholds, tool
   compression, memory retrieval, or compaction policy?
3. Are the hard gates strict enough for public contributors?
4. Should state debt be scored manually, or should the first harness derive a
   proxy from changed files, new flags, new tests, and docs burden?
5. What is the smallest first experiment that can produce a useful decision in
   one development cycle?

## References

- John H. Holland, *Adaptation in Natural and Artificial Systems*, University of
  Michigan Press, 1975.
- Herbert Robbins, "Some Aspects of the Sequential Design of Experiments,"
  *Bulletin of the American Mathematical Society*, 1952.
- J. O. Kephart and D. M. Chess, "The Vision of Autonomic Computing,"
  *Computer*, 36(1), 41-50, 2003. DOI: 10.1109/MC.2003.1160055.
- Charles Goodhart, "Problems of Monetary Management: The U.K. Experience,"
  1975.
- OpenSquilla repository documentation: `README.md`, `README.product.md`,
  `docs/diagnostics-and-replay.md`, `docs/tools-and-sandbox.md`, and
  `docs/usage-and-cost.md`.
