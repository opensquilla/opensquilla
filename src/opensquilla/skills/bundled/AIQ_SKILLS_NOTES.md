# AIQ bundled skills — INTERNAL ONLY

These 16 `aiq-*` skills are ported from the AIQ agent's skill library at
`aiq/skills/` (AIQ Markets, proprietary-internal). **Never publish this branch
or these directories** — provenance is `origin: internal / license: proprietary /
maintained_by: AIQ Markets`; they are not MIT/clawhub content.

All names are prefixed `aiq-` to avoid collisions with existing bundled skills.

## Source mapping

| Bundled skill | Source (aiq/skills/) | Extra files carried |
| --- | --- | --- |
| aiq-act-dont-gate | act-dont-gate/SKILL.md | — |
| aiq-aggregation-correctness | aggregation-correctness/SKILL.md | — |
| aiq-benchmark-methodology | benchmark-methodology/SKILL.md | — |
| aiq-bond-ladder-construction | bond-ladder-construction/SKILL.md | — |
| aiq-bond-trade-stats | bond-trade-stats/SKILL.md | scripts/compute.py, references/methodology.md |
| aiq-charting-and-visualization | charting-and-visualization/SKILL.md | — |
| aiq-compliance-and-refusals | compliance-and-refusals/SKILL.md | — |
| aiq-entity-resolution | entity-resolution/SKILL.md | — |
| aiq-handling-empty-data | handling-empty-data/SKILL.md | — |
| aiq-liquidation-horizon | liquidation-horizon/SKILL.md | scripts/days.py, references/notes.md |
| aiq-negation-and-exclusion | negation-and-exclusion/SKILL.md | — |
| aiq-new-issuance-queries | new-issuance-queries/SKILL.md | — |
| aiq-portfolio-concentration | portfolio-concentration/SKILL.md | scripts/hhi.py, references/hhi.md |
| aiq-rankings-and-leaderboards | rankings-and-leaderboards/SKILL.md | — |
| aiq-rendering-tables | rendering-tables/SKILL.md | — |
| aiq-transaction-cost-analysis | transaction-cost-analysis/SKILL.md | — |

## Porting adjustments (bodies otherwise verbatim)

- The three executable skills (bond-trade-stats, liquidation-horizon,
  portfolio-concentration) referenced the AIQ harness call
  `run_skill_script(name=..., script=..., input_json=...)`, which does not exist
  under OpenSquilla. Rewritten to run the bundled script directly
  (`python3 scripts/<script>.py input.json`, or JSON on stdin; result JSON on
  stdout). Scripts are pure-stdlib and behaviourally unchanged; the only
  edits are mechanical `ruff check` fixes (import-block spacing, dropping the
  redundant `"r"` open mode) so `ruff check src` stays clean.
- Cross-skill references were renamed to the `aiq-` names
  (act-dont-gate → aiq-act-dont-gate in bond-ladder-construction and
  charting-and-visualization; entity-resolution → aiq-entity-resolution in
  transaction-cost-analysis).
- Descriptions keep the original text plus an appended trigger sentence
  (OpenSquilla's injector/retriever indexes `description`, not `triggers`).
- The domain tool surface referenced in bodies (`securities_search`,
  `prints_search`, `analytics_vwap`, `movers_search`, `mktx_cpp_movers`,
  `search_tools`/`call_tool` for long-tail tools, …) is the AIQ Markets tool
  set; these skills are only meaningful in a session where those tools are
  mounted.
