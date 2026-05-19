"""Router-accuracy fixtures for ``llm_classify`` meta-skills.

Each module under this package contributes a per-router fixture set:
list of :class:`RouterCase` records mapping a representative user
message to its expected ``output_choices`` label, with language and
note tags for slicing.

The fixtures are consumed by two harnesses:

* ``test_meta_router_accuracy.py`` — **offline** sanity gate. Uses a
  deterministic mock ``LLMChat`` that returns ``case.expected_choice``
  verbatim, verifies the routing pipeline (prompt build → LLM call →
  ``_coerce_to_choice`` normalisation → step output) propagates the
  label correctly. Also asserts every fixture's expected_choice is one
  of the bundled skill's actual ``output_choices`` (typo prevention).

* ``test_meta_router_live.py`` — **live** accuracy measurement. Marked
  ``@pytest.mark.llm_router_acc``, runs the same fixtures against a
  real provider (Claude / GPT / Kimi / DeepSeek) and reports per-model
  accuracy. Maintainer-only, never on the default PR path. (D.2 work,
  not yet implemented.)

Adding a new router skill:

1. Create ``tests/test_skills/router_fixtures/<skill_name>.py`` with a
   module-level ``SKILL_NAME``, ``OUTPUT_CHOICES``, and ``CASES``.
2. Import its ``CASES`` here and append to :data:`ALL_CASES`.
3. The offline harness picks up the new cases automatically via the
   parametrise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouterCase:
    """One labelled routing example.

    Attributes:
        skill:            Bundled meta-skill name (e.g. ``meta-migration-assistant``).
        user_message:     The verbatim user input fed to the classifier.
        expected_choice:  The label the classifier should produce (must
                          appear in the skill's ``output_choices``).
        lang:             ``en`` / ``zh`` / ``mixed`` — for slicing per
                          language family in accuracy reports.
        note:             Short human label used as the pytest test id.
    """

    skill: str
    user_message: str
    expected_choice: str
    lang: str
    note: str


# Deferred import: child modules import ``RouterCase`` from this package
# so we must define it before they load.
from router_fixtures import knowledge_base_bootstrap, migration_assistant  # noqa: E402

ALL_CASES: list[RouterCase] = [
    *migration_assistant.CASES,
    *knowledge_base_bootstrap.CASES,
]


__all__ = ["ALL_CASES", "RouterCase", "knowledge_base_bootstrap", "migration_assistant"]
