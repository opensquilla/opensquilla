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
- `code_review_dirty_repo/` - tiny repository baseline plus `patch.diff` for
  `meta-codereview-current-diff`.
- `kid_project/complete_safe_request.txt` - complete safe request for
  `meta-kid-project-planner`.
- `kid_project/unsafe_request.txt` - unsafe request that should be redirected
  by `meta-kid-project-planner`.
- `auto_propose/decision_log_seed.jsonl` - low-risk repeated chain seed for
  `meta-skill-creator` unattended proposal validation.
- `meta_validation_cases.json` - validation matrix covering activation,
  negative activation, bundled meta-skills, creator, auto-propose, and live
  creator judge bundles.

All prompts use repository-relative paths so they can be pasted into a local
gateway or test harness from the repository root.
