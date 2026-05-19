"""Routing fixtures for ``meta-migration-assistant``.

The classifier emits one of 6 labels for the migration kind. Each
fixture here is a representative user-message → expected-label pair
that a competent LLM should classify correctly.

Coverage spans:

* Direct technology mentions (Python 2/3, Vue 2/3, React class, OpenAI
  v0/v1, CJS/ESM).
* Chinese-language paraphrases of the same requests.
* Indirect mentions where the migration kind is implied by symbol
  names (``ChatCompletion.create`` → OPENAI_V0_TO_V1, ``require()`` /
  ``module.exports`` → CJS_TO_ESM, etc.).
* Catch-all (OTHER) for migrations outside the closed set.

Adding cases: pick examples that are unambiguous to a human reader.
Genuinely ambiguous prompts belong in a separate "adversarial" pool
once live accuracy measurement (D.2) is online.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from router_fixtures import RouterCase


SKILL_NAME = "meta-migration-assistant"

OUTPUT_CHOICES = (
    "PY2_TO_PY3",
    "VUE2_TO_VUE3",
    "REACT_CLASS_TO_HOOKS",
    "OPENAI_V0_TO_V1",
    "CJS_TO_ESM",
    "OTHER",
)


def _case(message: str, expected: str, lang: str, note: str) -> RouterCase:
    from router_fixtures import RouterCase

    return RouterCase(
        skill=SKILL_NAME,
        user_message=message,
        expected_choice=expected,
        lang=lang,
        note=note,
    )


CASES = [
    # Direct English mentions
    _case(
        "help me migrate this codebase from Python 2 to Python 3",
        "PY2_TO_PY3", "en", "py23-direct",
    ),
    _case(
        "upgrade our Vue 2 app to Vue 3 with the composition API",
        "VUE2_TO_VUE3", "en", "vue23-direct",
    ),
    _case(
        "convert this React class component into hooks",
        "REACT_CLASS_TO_HOOKS", "en", "react-hooks-direct",
    ),
    _case(
        "migrate from openai v0 ChatCompletion.create to v1",
        "OPENAI_V0_TO_V1", "en", "openai-direct",
    ),
    _case(
        "port this Node module from CommonJS require to ESM import",
        "CJS_TO_ESM", "en", "cjs-esm-direct",
    ),

    # Chinese
    _case("帮我把这个项目从 Python 2 升级到 Python 3", "PY2_TO_PY3", "zh", "py23-chinese"),
    _case("Vue 2 升级 Vue 3 的指南", "VUE2_TO_VUE3", "zh", "vue23-chinese"),
    _case(
        "把这个 React 类组件改成 hooks 写法",
        "REACT_CLASS_TO_HOOKS", "zh", "react-hooks-chinese",
    ),
    _case("openai SDK 从 v0 升级到 v1", "OPENAI_V0_TO_V1", "zh", "openai-chinese"),
    _case("从 CommonJS 迁移到 ESM", "CJS_TO_ESM", "zh", "cjs-esm-chinese"),

    # Indirect — migration kind inferred from symbol/code references
    _case(
        "our code still calls openai.ChatCompletion.create, need to update",
        "OPENAI_V0_TO_V1", "en", "openai-symbol-hint",
    ),
    _case(
        "replace all require() with import statements",
        "CJS_TO_ESM", "en", "cjs-esm-symbol-hint",
    ),
    _case(
        "rewrite componentDidMount/componentWillUnmount to useEffect",
        "REACT_CLASS_TO_HOOKS", "en", "react-lifecycle-hint",
    ),

    # Catch-all (OTHER)
    _case("migrate from MySQL 5.7 to MySQL 8.0", "OTHER", "en", "other-db-version"),
    _case("我想从 Postgres 迁移到 MongoDB", "OTHER", "zh", "other-cross-db"),
    _case("upgrade our Java 8 codebase to Java 17", "OTHER", "en", "other-java-version"),
]


__all__ = ["CASES", "OUTPUT_CHOICES", "SKILL_NAME"]
