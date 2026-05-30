# Meta-Skill Input Fixtures

This directory contains small, deterministic inputs for manually or
programmatically exercising the bundled high-value meta-skills.

## Fixture Map

- `pdf_intelligence/router-evaluation-summary.pdf` - valid local PDF for
  `meta-pdf-intelligence`.
- `pdf_intelligence/question.txt` - prompt that should use the readable PDF
  path and avoid clarification.
- `travel_planner/complete_request.txt` - complete itinerary request that
  should not trigger `trip_clarify`.
- `travel_planner/missing_destination_request.txt` - intentionally incomplete
  itinerary request that should trigger `trip_clarify`.
- `skill_creator/request.txt` - bounded request for `meta-skill-creator`.
- `migration_assistant/cjs-to-esm-package/` - tiny CommonJS package fixture for
  a CommonJS to native ESM migration checklist.
- `migration_assistant/request.txt` - migration prompt referencing that fixture.
- `web_research_to_report/decision_memo_request.txt` - source-backed decision
  memo request with enough context to proceed.
- `web_research_to_report/broad_request.txt` - intentionally broad report
  request that should trigger `report_clarify`.

All prompts use repository-relative paths so they can be pasted into a local
gateway or test harness from the repository root.
