"""Routing fixtures for ``meta-knowledge-base-bootstrap``.

The classifier picks the primary source type of the user's input:
``URL`` (webpage), ``PDF`` (.pdf path/URL), ``GIT`` (repo) or ``TEXT``
(everything else).

The boundary cases worth attention:

* A GitHub URL — classified ``GIT``, NOT ``URL``, by the skill's rule.
* A URL ending in ``.pdf`` — classified ``PDF``.
* A bare topic with no link — ``TEXT``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from router_fixtures import RouterCase


SKILL_NAME = "meta-knowledge-base-bootstrap"

OUTPUT_CHOICES = ("URL", "PDF", "GIT", "TEXT")


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
    # URL
    _case(
        "ingest https://example.com/article/12345 into my notes",
        "URL", "en", "url-https",
    ),
    _case(
        "https://blog.openai.com/some-post 总结一下",
        "URL", "mixed", "url-with-chinese-prompt",
    ),

    # PDF
    _case(
        "please summarise https://arxiv.org/pdf/2402.12345.pdf",
        "PDF", "en", "pdf-arxiv",
    ),
    _case(
        "处理这个 PDF: ~/papers/transformers.pdf",
        "PDF", "zh", "pdf-local-path",
    ),

    # GIT
    _case(
        "clone github.com/openai/whisper and index its README",
        "GIT", "en", "git-github",
    ),
    _case("看一下 gitlab.com/some/project 的代码", "GIT", "zh", "git-gitlab"),
    _case(
        "ingest the repo at ~/projects/my-repo (it has a .git folder)",
        "GIT", "en", "git-local-path",
    ),

    # TEXT (catch-all)
    _case(
        "explain transformer attention mechanisms",
        "TEXT", "en", "text-bare-topic-en",
    ),
    _case("帮我整理 RAG 系统的相关知识", "TEXT", "zh", "text-bare-topic-zh"),
    _case(
        "what are the trade-offs between Postgres and MongoDB",
        "TEXT", "en", "text-question",
    ),
]


__all__ = ["CASES", "OUTPUT_CHOICES", "SKILL_NAME"]
