#!/usr/bin/env python3
"""Require a human review for risky pull requests."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any, NamedTuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MAX_UNREVIEWED_CHANGED_FILES = 30
MAX_UNREVIEWED_LINE_DELTA = 1000
TRUSTED_REVIEWER_ASSOCIATIONS = frozenset({"MEMBER", "OWNER"})

RISK_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CI",
        (
            ".github/workflows/**",
            ".github/scripts/**",
            ".github/actions/**",
            ".github/dependabot.yml",
        ),
    ),
    (
        "release",
        (
            ".github/workflows/wheelhouse-release.yml",
            ".github/workflows/live-release-e2e.yml",
            "scripts/build_wheelhouse_zip.py",
            "scripts/install_source.sh",
            "scripts/install_source.ps1",
            "install.sh",
            "install.ps1",
            "start.sh",
            "start.ps1",
            "README.release.md",
            "RELEASES.md",
            "docs/releases/**",
        ),
    ),
    (
        "security",
        (
            "SECURITY.md",
            "src/opensquilla/sandbox/**",
            "src/opensquilla/safety/**",
            "src/opensquilla/tools/builtin/code_exec.py",
            "src/opensquilla/tools/builtin/filesystem.py",
            "src/opensquilla/tools/builtin/git.py",
            "src/opensquilla/tools/builtin/shell.py",
            "src/opensquilla/tools/builtin/shell_policy.py",
            "src/opensquilla/tools/path_*.py",
            "src/opensquilla/tools/policy/**",
            "src/opensquilla/tools/policy*.py",
            "src/opensquilla/tools/write_policy.py",
            "src/opensquilla/skills/hub/installer.py",
            "tests/test_security/**",
            "tests/test_sandbox/**",
            "tests/test_tools/test_*policy*.py",
            "tests/test_tools/test_path_*.py",
            "tests/test_tools/test_shell_*.py",
        ),
    ),
    (
        "provider",
        (
            "src/opensquilla/provider/**",
            "src/opensquilla/search/providers/**",
            "src/opensquilla/onboarding/provider_specs.py",
            "src/opensquilla/cli/providers_cmd.py",
            "tests/test_provider*.py",
            "tests/test_provider/**",
            "tests/test_search/test_*provider.py",
            "tests/test_onboarding/test_provider_specs.py",
            "docs/providers-and-models.md",
            "docs/features/bocha-search-provider-design.md",
        ),
    ),
    (
        "desktop",
        (
            "desktop/**",
            "tests/test_desktop/**",
        ),
    ),
)


class PullRequestContext(NamedTuple):
    number: int
    author_login: str
    author_association: str
    additions: int
    deletions: int
    changed_files_count: int
    files: tuple[str, ...]

    @property
    def line_delta(self) -> int:
        return self.additions + self.deletions


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _error(title: str, message: str) -> None:
    print(f"::error title={_annotation_escape(title)}::{_annotation_escape(message)}")


def _load_event(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as event_file:
        return json.load(event_file)


def _repo_from_event(event: dict[str, Any]) -> str:
    repository = event.get("repository") or {}
    full_name = str(repository.get("full_name") or "")
    if full_name:
        return full_name
    return os.environ.get("GITHUB_REPOSITORY", "")


def _request_json(repo: str, token: str, path: str) -> Any:
    request = Request(
        f"https://api.github.com/repos/{repo}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API GET {path} failed: {exc.code} {body}") from exc
    return json.loads(raw.decode("utf-8")) if raw else None


def _fetch_paginated(repo: str, token: str, path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        page_items = _request_json(repo, token, f"{path}{separator}per_page=100&page={page}")
        if not isinstance(page_items, list) or not page_items:
            return items
        items.extend(page_items)
        if len(page_items) < 100:
            return items
        page += 1


def _changed_files_from_env() -> tuple[str, ...] | None:
    path = os.environ.get("PR_CHANGED_FILES_PATH")
    if not path:
        return None
    return tuple(
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _reviews_from_env() -> list[dict[str, Any]] | None:
    path = os.environ.get("PR_REVIEWS_PATH")
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("PR_REVIEWS_PATH must contain a JSON array")
    return data


def _github_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _load_pr_context(event: dict[str, Any]) -> PullRequestContext | None:
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return None

    files = _changed_files_from_env()
    repo = _repo_from_event(event)
    token = _github_token()
    if files is None:
        if not repo or not token:
            raise RuntimeError(
                "GITHUB_REPOSITORY and GITHUB_TOKEN/GH_TOKEN are required to load PR files."
            )
        files = tuple(
            str(item.get("filename") or "")
            for item in _fetch_paginated(repo, token, f"/pulls/{int(pr['number'])}/files")
            if item.get("filename")
        )

    user = pr.get("user") or {}
    return PullRequestContext(
        number=int(pr["number"]),
        author_login=str(user.get("login") or ""),
        author_association=str(pr.get("author_association") or "").upper(),
        additions=int(pr.get("additions") or 0),
        deletions=int(pr.get("deletions") or 0),
        changed_files_count=int(pr.get("changed_files") or len(files)),
        files=files,
    )


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def review_requirement_reasons(context: PullRequestContext) -> list[str]:
    reasons: list[str] = []

    if context.changed_files_count > MAX_UNREVIEWED_CHANGED_FILES:
        reasons.append(
            f"{context.changed_files_count} changed files "
            f"(>{MAX_UNREVIEWED_CHANGED_FILES})"
        )

    if context.line_delta > MAX_UNREVIEWED_LINE_DELTA:
        reasons.append(f"{context.line_delta} changed lines (>{MAX_UNREVIEWED_LINE_DELTA})")

    for category, patterns in RISK_PATTERNS:
        matched = next((path for path in context.files if _matches_any(path, patterns)), None)
        if matched is not None:
            reasons.append(f"{category} surface changed ({matched})")

    return reasons


def active_approvers(reviews: list[dict[str, Any]], *, author_login: str) -> tuple[str, ...]:
    decisive_states = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
    latest_by_user: dict[str, dict[str, Any]] = {}
    for index, review in enumerate(reviews):
        user = review.get("user") or {}
        login = str(user.get("login") or "")
        if not login or login == author_login:
            continue
        association = str(review.get("author_association") or "").upper()
        if association not in TRUSTED_REVIEWER_ASSOCIATIONS:
            continue
        if str(review.get("state") or "").upper() not in decisive_states:
            continue
        review_with_index = dict(review)
        review_with_index["_index"] = index
        previous = latest_by_user.get(login)
        if previous is None:
            latest_by_user[login] = review_with_index
            continue
        previous_key = (str(previous.get("submitted_at") or ""), int(previous.get("_index") or 0))
        current_key = (
            str(review_with_index.get("submitted_at") or ""),
            int(review_with_index.get("_index") or 0),
        )
        if current_key >= previous_key:
            latest_by_user[login] = review_with_index

    return tuple(
        sorted(
            login
            for login, review in latest_by_user.items()
            if str(review.get("state") or "").upper() == "APPROVED"
        )
    )


def _load_reviews(event: dict[str, Any], pr_number: int) -> list[dict[str, Any]]:
    reviews = _reviews_from_env()
    if reviews is not None:
        return reviews

    repo = _repo_from_event(event)
    token = _github_token()
    if not repo or not token:
        raise RuntimeError(
            "GITHUB_REPOSITORY and GITHUB_TOKEN/GH_TOKEN are required to load PR reviews."
        )
    return _fetch_paginated(repo, token, f"/pulls/{pr_number}/reviews")


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        _error("Missing PR event", "GITHUB_EVENT_PATH is required for review governance.")
        return 1

    try:
        event = _load_event(event_path)
        context = _load_pr_context(event)
        if context is None:
            print("Review gate only applies to pull requests.")
            return 0

        reasons = review_requirement_reasons(context)
        if not reasons:
            print("Risk-based review is not required for this pull request.")
            return 0

        reviews = _load_reviews(event, context.number)
        approvers = active_approvers(reviews, author_login=context.author_login)
        if approvers:
            print(
                "Risk-based review requirement satisfied by: "
                + ", ".join(approvers)
                + "."
            )
            return 0

        _error(
            "Review required",
            "This pull request needs at least one non-author organization member "
            "approval because: "
            + "; ".join(reasons)
            + ".",
        )
        return 1
    except Exception as exc:
        _error("Review gate failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
