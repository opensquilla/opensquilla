from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_gate_module():
    script = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "scripts"
        / "validate_pr_review_gate.py"
    )
    spec = importlib.util.spec_from_file_location("validate_pr_review_gate", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_gate_requires_review_for_large_and_risky_pr() -> None:
    gate = _load_gate_module()

    reasons = gate.review_requirement_reasons(
        gate.PullRequestContext(
            number=123,
            author_login="external-dev",
            author_association="CONTRIBUTOR",
            additions=900,
            deletions=101,
            changed_files_count=31,
            files=(
                ".github/workflows/ci.yml",
                "desktop/electron/src/main.ts",
                "src/opensquilla/provider/openai.py",
                "src/opensquilla/sandbox/policy.py",
                "scripts/build_wheelhouse_zip.py",
            ),
        )
    )

    assert "31 changed files (>30)" in reasons
    assert "1001 changed lines (>1000)" in reasons
    assert "CI surface changed (.github/workflows/ci.yml)" in reasons
    assert "desktop surface changed (desktop/electron/src/main.ts)" in reasons
    assert "provider surface changed (src/opensquilla/provider/openai.py)" in reasons
    assert "security surface changed (src/opensquilla/sandbox/policy.py)" in reasons
    assert "release surface changed (scripts/build_wheelhouse_zip.py)" in reasons


def test_review_gate_does_not_require_review_for_small_low_risk_pr() -> None:
    gate = _load_gate_module()

    for association in ["OWNER", "FIRST_TIME_CONTRIBUTOR"]:
        reasons = gate.review_requirement_reasons(
            gate.PullRequestContext(
                number=124,
                author_login="contributor",
                author_association=association,
                additions=40,
                deletions=5,
                changed_files_count=2,
                files=("README.md", "docs/features/skills.md"),
            )
        )

        assert reasons == []


def test_review_gate_counts_latest_non_author_organization_member_approval_only() -> None:
    gate = _load_gate_module()

    reviews = [
        {
            "state": "APPROVED",
            "submitted_at": "2026-06-30T01:00:00Z",
            "author_association": "MEMBER",
            "user": {"login": "reviewer-a"},
        },
        {
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-06-30T02:00:00Z",
            "author_association": "MEMBER",
            "user": {"login": "reviewer-a"},
        },
        {
            "state": "APPROVED",
            "submitted_at": "2026-06-30T02:30:00Z",
            "author_association": "CONTRIBUTOR",
            "user": {"login": "external-reviewer"},
        },
        {
            "state": "APPROVED",
            "submitted_at": "2026-06-30T03:00:00Z",
            "author_association": "OWNER",
            "user": {"login": "reviewer-b"},
        },
        {
            "state": "COMMENTED",
            "submitted_at": "2026-06-30T03:30:00Z",
            "author_association": "OWNER",
            "user": {"login": "reviewer-b"},
        },
        {
            "state": "APPROVED",
            "submitted_at": "2026-06-30T04:00:00Z",
            "author_association": "OWNER",
            "user": {"login": "author"},
        },
    ]

    assert gate.active_approvers(reviews, author_login="author") == ("reviewer-b",)


def test_review_gate_rejects_external_approval_for_risky_pr(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    files_path = tmp_path / "files.txt"
    reviews_path = tmp_path / "reviews.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "opensquilla/opensquilla"},
                "pull_request": {
                    "number": 127,
                    "user": {"login": "external-dev"},
                    "author_association": "FIRST_TIME_CONTRIBUTOR",
                    "additions": 5,
                    "deletions": 0,
                    "changed_files": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    files_path.write_text("src/opensquilla/provider/openai.py\n", encoding="utf-8")
    reviews_path.write_text(
        json.dumps(
            [
                {
                    "state": "APPROVED",
                    "submitted_at": "2026-06-30T01:00:00Z",
                    "author_association": "CONTRIBUTOR",
                    "user": {"login": "external-reviewer"},
                }
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_PATH": event_path.as_posix(),
            "PR_CHANGED_FILES_PATH": files_path.as_posix(),
            "PR_REVIEWS_PATH": reviews_path.as_posix(),
        }
    )
    result = subprocess.run(
        [sys.executable, ".github/scripts/validate_pr_review_gate.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "non-author organization member approval" in result.stdout


def test_review_gate_accepts_organization_member_approval_for_risky_pr(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    files_path = tmp_path / "files.txt"
    reviews_path = tmp_path / "reviews.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "opensquilla/opensquilla"},
                "pull_request": {
                    "number": 128,
                    "user": {"login": "external-dev"},
                    "author_association": "FIRST_TIME_CONTRIBUTOR",
                    "additions": 5,
                    "deletions": 0,
                    "changed_files": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    files_path.write_text("src/opensquilla/provider/openai.py\n", encoding="utf-8")
    reviews_path.write_text(
        json.dumps(
            [
                {
                    "state": "APPROVED",
                    "submitted_at": "2026-06-30T01:00:00Z",
                    "author_association": "MEMBER",
                    "user": {"login": "org-member"},
                }
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_PATH": event_path.as_posix(),
            "PR_CHANGED_FILES_PATH": files_path.as_posix(),
            "PR_REVIEWS_PATH": reviews_path.as_posix(),
        }
    )
    result = subprocess.run(
        [sys.executable, ".github/scripts/validate_pr_review_gate.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "satisfied by: org-member" in result.stdout


def test_review_gate_allows_small_external_pr_from_local_event(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    files_path = tmp_path / "files.txt"
    reviews_path = tmp_path / "reviews.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "opensquilla/opensquilla"},
                "pull_request": {
                    "number": 125,
                    "user": {"login": "external-dev"},
                    "author_association": "FIRST_TIME_CONTRIBUTOR",
                    "additions": 5,
                    "deletions": 0,
                    "changed_files": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    files_path.write_text("README.md\n", encoding="utf-8")
    reviews_path.write_text("[]", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_PATH": event_path.as_posix(),
            "PR_CHANGED_FILES_PATH": files_path.as_posix(),
            "PR_REVIEWS_PATH": reviews_path.as_posix(),
        }
    )
    result = subprocess.run(
        [sys.executable, ".github/scripts/validate_pr_review_gate.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Risk-based review is not required" in result.stdout


def test_review_gate_fails_risky_unapproved_pr_from_local_event(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    files_path = tmp_path / "files.txt"
    reviews_path = tmp_path / "reviews.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "opensquilla/opensquilla"},
                "pull_request": {
                    "number": 126,
                    "user": {"login": "external-dev"},
                    "author_association": "FIRST_TIME_CONTRIBUTOR",
                    "additions": 5,
                    "deletions": 0,
                    "changed_files": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    files_path.write_text("src/opensquilla/provider/openai.py\n", encoding="utf-8")
    reviews_path.write_text("[]", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_PATH": event_path.as_posix(),
            "PR_CHANGED_FILES_PATH": files_path.as_posix(),
            "PR_REVIEWS_PATH": reviews_path.as_posix(),
        }
    )
    result = subprocess.run(
        [sys.executable, ".github/scripts/validate_pr_review_gate.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "::error title=Review required::" in result.stdout
    assert "non-author organization member approval" in result.stdout
    assert "provider surface changed (src/opensquilla/provider/openai.py)" in result.stdout
