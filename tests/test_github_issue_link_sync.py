from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_sync_module():
    script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "issue_link_sync.py"
    spec = importlib.util.spec_from_file_location("issue_link_sync", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingClient:
    def __init__(self, comments: list[dict[str, Any]] | None = None) -> None:
        self.comments = comments or []
        self.calls: list[tuple[Any, ...]] = []

    def add_labels(self, issue_number: int, labels: list[str]) -> None:
        self.calls.append(("add_labels", issue_number, tuple(labels)))

    def remove_label(self, issue_number: int, label: str) -> None:
        self.calls.append(("remove_label", issue_number, label))

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        self.calls.append(("list_comments", issue_number))
        return self.comments

    def create_comment(self, issue_number: int, body: str) -> None:
        self.calls.append(("create_comment", issue_number, body))


class PaginatedGitHubClient:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.paths: list[str] = []

    def request_json(self, method: str, path: str) -> list[dict[str, Any]]:
        assert method == "GET"
        self.paths.append(path)
        return self.pages.pop(0)


def test_parse_linked_issues_splits_closing_and_reference_keywords() -> None:
    sync = _load_sync_module()

    parsed = sync.parse_linked_issues(
        "\n".join(
            [
                "Fixes #100",
                "Closes: opensquilla/opensquilla#101",
                "resolves https://github.com/opensquilla/opensquilla/issues/102",
                "Refs #200",
                "References opensquilla/opensquilla#201",
                "Fixes other/project#999",
            ]
        ),
        owner="opensquilla",
        repo="opensquilla",
    )

    assert parsed.closing == (100, 101, 102)
    assert parsed.references == (200, 201)
    assert parsed.all == (100, 101, 102, 200, 201)


def test_parse_linked_issues_deduplicates_and_ignores_pr_style_urls() -> None:
    sync = _load_sync_module()

    parsed = sync.parse_linked_issues(
        "\n".join(
            [
                "Fixes #100",
                "fixes #100",
                "Refs https://github.com/opensquilla/opensquilla/pull/203",
                "Fixes https://github.com/opensquilla/opensquilla/issues/101",
            ]
        ),
        owner="opensquilla",
        repo="opensquilla",
    )

    assert parsed.closing == (100, 101)
    assert parsed.references == ()
    assert parsed.all == (100, 101)


def test_plan_merged_dev_pr_updates_only_closing_issues() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "closed",
            "pull_request": {
                "number": 203,
                "merged": True,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "dev"},
                "html_url": "https://github.com/opensquilla/opensquilla/pull/203",
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=100,
            kind="merged_to_dev",
            pr_number=203,
            pr_url="https://github.com/opensquilla/opensquilla/pull/203",
        ),
    )


def test_plan_closed_unmerged_pr_removes_linked_pr_label_from_all_linked_issues() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "closed",
            "pull_request": {
                "number": 204,
                "merged": False,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "dev"},
                "html_url": "https://github.com/opensquilla/opensquilla/pull/204",
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=100,
            kind="closed_unmerged",
            pr_number=204,
            pr_url="https://github.com/opensquilla/opensquilla/pull/204",
        ),
        sync.IssueSyncAction(
            issue_number=200,
            kind="closed_unmerged",
            pr_number=204,
            pr_url="https://github.com/opensquilla/opensquilla/pull/204",
        ),
    )


def test_comment_marker_is_pr_scoped_for_idempotent_merged_to_dev_comments() -> None:
    sync = _load_sync_module()

    marker = sync.comment_marker(kind="merged_to_dev", pr_number=203)

    assert marker == "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-203 -->"
    assert sync.has_marker([{"body": f"{marker}\nThis is already posted."}], marker)
    assert not sync.has_marker(
        [{"body": "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-202 -->"}],
        marker,
    )


def test_apply_merged_dev_action_labels_removes_open_pr_label_and_comments_once() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="merged_to_dev",
        pr_number=203,
        pr_url="https://github.com/opensquilla/opensquilla/pull/203",
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [
        ("add_labels", 100, ("merged-to-dev", "needs-verification")),
        ("remove_label", 100, "has-linked-pr"),
        ("list_comments", 100),
        (
            "create_comment",
            100,
            "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-203 -->\n"
            "The linked fix for this issue has merged to `dev` via #203 "
            "(https://github.com/opensquilla/opensquilla/pull/203). "
            "Keeping it open for verification before release.",
        ),
    ]

    marker = sync.comment_marker(kind="merged_to_dev", pr_number=203)
    client = RecordingClient(comments=[{"body": marker}])

    sync.apply_action(client, action)

    assert client.calls == [
        ("add_labels", 100, ("merged-to-dev", "needs-verification")),
        ("remove_label", 100, "has-linked-pr"),
        ("list_comments", 100),
    ]


def test_apply_closed_unmerged_action_only_removes_open_pr_label() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=200,
        kind="closed_unmerged",
        pr_number=204,
        pr_url="https://github.com/opensquilla/opensquilla/pull/204",
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [("remove_label", 200, "has-linked-pr")]


def test_list_comments_reads_all_pages_before_idempotency_check() -> None:
    sync = _load_sync_module()
    client = PaginatedGitHubClient(
        [
            [{"body": f"old comment {index}"} for index in range(100)],
            [{"body": "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-203 -->"}],
        ]
    )

    comments = sync.GitHubClient.list_comments(client, 100)

    assert sync.has_marker(
        comments,
        "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-203 -->",
    )
    assert client.paths == [
        "/issues/100/comments?per_page=100&page=1",
        "/issues/100/comments?per_page=100&page=2",
    ]
