#!/usr/bin/env python3
"""Warn when a pull request body misses OpenSquilla governance fields."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import NamedTuple


class RequiredField(NamedTuple):
    name: str
    pattern: re.Pattern[str]


REQUIRED_FIELDS = (
    RequiredField("Scope boundary", re.compile(r"(?im)^\s*Scope boundary\s*:")),
    RequiredField("Base branch", re.compile(r"(?im)^\s*Base branch\s*:")),
    RequiredField("Main exception", re.compile(r"(?im)^\s*Main exception\s*:")),
    RequiredField("Linked issue", re.compile(r"(?im)^\s*Linked issue\s*:")),
    RequiredField("Release note", re.compile(r"(?im)^\s*Release note\s*:")),
    RequiredField("Tests", re.compile(r"(?im)^\s*(?:#+\s*)?Tests\s*:?\s*$")),
    RequiredField("Maintainer live check", re.compile(r"(?im)^\s*Maintainer live check\s*:")),
    RequiredField("Third-party origin", re.compile(r"(?im)^\s*Third-party origin\s*:")),
)


def missing_fields(body: str | None) -> list[str]:
    text = body or ""
    return [field.name for field in REQUIRED_FIELDS if field.pattern.search(text) is None]


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _warning(title: str, message: str) -> None:
    print(f"::warning title={_annotation_escape(title)}::{_annotation_escape(message)}")


def _is_strict() -> bool:
    return os.environ.get("PR_BODY_LINT_STRICT", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _load_pr_body(event_path: str) -> str | None:
    with Path(event_path).open(encoding="utf-8") as event_file:
        event = json.load(event_file)
    return (event.get("pull_request") or {}).get("body")


def main() -> int:
    strict = _is_strict()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        _warning("Missing PR event", "GITHUB_EVENT_PATH is not set; skipping PR body lint.")
        return 1 if strict else 0

    try:
        body = _load_pr_body(event_path)
    except (OSError, json.JSONDecodeError) as exc:
        _warning("Unreadable PR event", f"Unable to read pull request event: {exc}")
        return 1 if strict else 0

    missing = missing_fields(body)
    if not missing:
        print("PR body includes required governance fields.")
        return 0

    for field in missing:
        _warning(
            "Missing PR template field",
            f"Add the `{field}:` field to make review intent explicit.",
        )

    print(
        "PR body lint is warning-only. Maintainers may harden it by setting "
        "PR_BODY_LINT_STRICT=1 after existing pull requests are migrated."
    )
    return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
