---
name: meta-skill-smoke-test
description: "Run G3 (positive smoke) and G4 (negative smoke) gates against a candidate meta-skill SKILL.md. Cross-vendor: fixture-generation LLM != classifier LLM. Used by meta-skill-creator and standalone for any meta-skill prompt-stability regression."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
---

# Meta-Skill Smoke Test

When invoked as a `kind: agent, skill: meta-skill-smoke-test` step, this sub-agent:

1. Receives `skill_md`, `fixture_gen_model`, `classifier_model` from the parent step's `with:`
2. Calls `simulate_meta_resolution` with a positive fixture (LLM-generated using `fixture_gen_model`)
3. Calls `simulate_meta_resolution` with a negative fixture (LLM-generated, cross-domain)
4. Returns `{"G3": {...}, "G4": {...}}` JSON

If `OPENROUTER_API_KEY` is absent OR either `fixture_gen_model`/`classifier_model` is unconfigured, the sub-agent falls back to the deterministic fixture generator and pins `classifier_model="stub"`. In both cases the smoke step still emits G3/G4 records, but with a `degraded: true` flag.

## Fallback

If the sub-agent fails entirely, output `{"G3": {"passed": false, "reason": "smoke unavailable"}, "G4": {"passed": false, "reason": "smoke unavailable"}}`.
