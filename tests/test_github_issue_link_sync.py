from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

DUMMY_MERGED_DEV_PR = 9001
DUMMY_CLOSED_PR = 9002
DUMMY_OPEN_PR = 9003
DUMMY_MERGED_MAIN_PR = 9004
DUMMY_MERGED_DEV_PR_URL = "https://example.invalid/pulls/9001"
DUMMY_CLOSED_PR_URL = "https://example.invalid/pulls/9002"
DUMMY_OPEN_PR_URL = "https://example.invalid/pulls/9003"
DUMMY_MERGED_MAIN_PR_URL = "https://example.invalid/pulls/9004"


def _load_sync_module():
    script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "issue_link_sync.py"
    spec = importlib.util.spec_from_file_location("issue_link_sync", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingClient:
    def __init__(
        self,
        comments: list[dict[str, Any]] | None = None,
        other_open_linked_issues: set[int] | None = None,
    ) -> None:
        self.comments = comments or []
        self.other_open_linked_issues = other_open_linked_issues or set()
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

    def has_other_open_linked_pull_request(self, issue_number: int, pr_number: int) -> bool:
        self.calls.append(("has_other_open_linked_pull_request", issue_number, pr_number))
        return issue_number in self.other_open_linked_issues


class PaginatedGitHubClient:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self._repository = "opensquilla/opensquilla"
        self.paths: list[str] = []

    def request_json(self, method: str, path: str, **_kwargs: Any) -> list[dict[str, Any]]:
        assert method == "GET"
        self.paths.append(path)
        return self.pages.pop(0)

    def list_open_pull_requests(self) -> list[dict[str, Any]]:
        pulls = self.request_json("GET", "/pulls?state=open&per_page=100&page=1")
        assert isinstance(pulls, list)
        return pulls


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
                "Refs https://github.com/opensquilla/opensquilla/pull/9999",
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
                "number": DUMMY_MERGED_DEV_PR,
                "merged": True,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "dev"},
                "html_url": DUMMY_MERGED_DEV_PR_URL,
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
            pr_number=DUMMY_MERGED_DEV_PR,
            pr_url=DUMMY_MERGED_DEV_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=200,
            kind="remove_linked_pr",
            pr_number=DUMMY_MERGED_DEV_PR,
            pr_url=DUMMY_MERGED_DEV_PR_URL,
        ),
    )


def test_plan_open_or_updated_pr_adds_linked_pr_label_to_all_linked_issues() -> None:
    sync = _load_sync_module()

    for action_name in ["opened", "reopened", "edited"]:
        actions = sync.plan_issue_sync_actions(
            {
                "action": action_name,
                "pull_request": {
                    "number": DUMMY_OPEN_PR,
                    "state": "open",
                    "merged": False,
                    "body": "Fixes #100\nRefs #200",
                    "base": {"ref": "dev"},
                    "html_url": DUMMY_OPEN_PR_URL,
                },
                "repository": {
                    "full_name": "opensquilla/opensquilla",
                },
            }
        )

        assert actions == (
            sync.IssueSyncAction(
                issue_number=100,
                kind="linked_pr_open",
                pr_number=DUMMY_OPEN_PR,
                pr_url=DUMMY_OPEN_PR_URL,
            ),
            sync.IssueSyncAction(
                issue_number=200,
                kind="linked_pr_open",
                pr_number=DUMMY_OPEN_PR,
                pr_url=DUMMY_OPEN_PR_URL,
            ),
        )


def test_plan_edited_open_pr_removes_links_deleted_from_body() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "edited",
            "changes": {
                "body": {
                    "from": "Fixes #100\nRefs #200",
                },
            },
            "pull_request": {
                "number": DUMMY_OPEN_PR,
                "state": "open",
                "merged": False,
                "body": "Refs #200",
                "base": {"ref": "dev"},
                "html_url": DUMMY_OPEN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=200,
            kind="linked_pr_open",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=100,
            kind="remove_linked_pr",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
    )


def test_plan_edited_closed_pr_does_not_readd_open_pr_label() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "edited",
            "pull_request": {
                "number": DUMMY_OPEN_PR,
                "state": "closed",
                "merged": True,
                "body": "Fixes #100",
                "base": {"ref": "dev"},
                "html_url": DUMMY_OPEN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == ()


def test_plan_edited_pr_retargeted_from_final_base_removes_linked_labels() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "edited",
            "changes": {
                "base": {
                    "ref": {
                        "from": "dev",
                    },
                },
                "body": {
                    "from": "Fixes #100",
                },
            },
            "pull_request": {
                "number": DUMMY_OPEN_PR,
                "state": "open",
                "merged": False,
                "body": "Refs #200",
                "base": {"ref": "sandbox-optimization"},
                "html_url": DUMMY_OPEN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=200,
            kind="remove_linked_pr",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=100,
            kind="remove_linked_pr",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
    )


def test_plan_edited_pr_retargeted_from_final_base_to_unknown_base_removes_linked_labels() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "edited",
            "changes": {
                "base": {
                    "ref": {
                        "from": "dev",
                    },
                },
                "body": {
                    "from": "Fixes #100",
                },
            },
            "pull_request": {
                "number": DUMMY_OPEN_PR,
                "state": "open",
                "merged": False,
                "body": "Refs #200",
                "base": {"ref": "feature/shared-work"},
                "html_url": DUMMY_OPEN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=200,
            kind="remove_linked_pr",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=100,
            kind="remove_linked_pr",
            pr_number=DUMMY_OPEN_PR,
            pr_url=DUMMY_OPEN_PR_URL,
        ),
    )


def test_plan_open_staging_pr_does_not_add_linked_pr_label() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "opened",
            "pull_request": {
                "number": DUMMY_OPEN_PR,
                "state": "open",
                "merged": False,
                "body": "Fixes #100",
                "base": {"ref": "sandbox-optimization"},
                "html_url": DUMMY_OPEN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == ()


def test_plan_closed_non_final_pr_does_not_remove_linked_pr_label() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "closed",
            "pull_request": {
                "number": DUMMY_CLOSED_PR,
                "merged": False,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "feature/shared-work"},
                "html_url": DUMMY_CLOSED_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == ()


def test_plan_merged_main_pr_releases_closing_issues_and_removes_open_labels() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "closed",
            "pull_request": {
                "number": DUMMY_MERGED_MAIN_PR,
                "merged": True,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "main"},
                "html_url": DUMMY_MERGED_MAIN_PR_URL,
            },
            "repository": {
                "full_name": "opensquilla/opensquilla",
            },
        }
    )

    assert actions == (
        sync.IssueSyncAction(
            issue_number=100,
            kind="merged_to_main",
            pr_number=DUMMY_MERGED_MAIN_PR,
            pr_url=DUMMY_MERGED_MAIN_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=200,
            kind="remove_linked_pr",
            pr_number=DUMMY_MERGED_MAIN_PR,
            pr_url=DUMMY_MERGED_MAIN_PR_URL,
        ),
    )


def test_plan_closed_unmerged_pr_removes_linked_pr_label_from_all_linked_issues() -> None:
    sync = _load_sync_module()

    actions = sync.plan_issue_sync_actions(
        {
            "action": "closed",
            "pull_request": {
                "number": DUMMY_CLOSED_PR,
                "merged": False,
                "body": "Fixes #100\nRefs #200",
                "base": {"ref": "dev"},
                "html_url": DUMMY_CLOSED_PR_URL,
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
            pr_number=DUMMY_CLOSED_PR,
            pr_url=DUMMY_CLOSED_PR_URL,
        ),
        sync.IssueSyncAction(
            issue_number=200,
            kind="closed_unmerged",
            pr_number=DUMMY_CLOSED_PR,
            pr_url=DUMMY_CLOSED_PR_URL,
        ),
    )


def test_comment_marker_is_pr_scoped_for_idempotent_merged_to_dev_comments() -> None:
    sync = _load_sync_module()

    marker = sync.comment_marker(kind="merged_to_dev", pr_number=DUMMY_MERGED_DEV_PR)

    assert marker == "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9001 -->"
    assert sync.has_marker([{"body": f"{marker}\nThis is already posted."}], marker)
    assert not sync.has_marker(
        [{"body": "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9000 -->"}],
        marker,
    )


def test_apply_merged_dev_action_labels_removes_open_pr_label_and_comments_once() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="merged_to_dev",
        pr_number=DUMMY_MERGED_DEV_PR,
        pr_url=DUMMY_MERGED_DEV_PR_URL,
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [
        ("add_labels", 100, ("merged-to-dev", "needs-verification")),
        ("has_other_open_linked_pull_request", 100, DUMMY_MERGED_DEV_PR),
        ("remove_label", 100, "has-linked-pr"),
        ("list_comments", 100),
        (
            "create_comment",
            100,
            "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9001 -->\n"
            "The linked fix for this issue has merged to `dev` via #9001 "
            f"({DUMMY_MERGED_DEV_PR_URL}). "
            "Keeping it open for verification before release.",
        ),
    ]

    marker = sync.comment_marker(kind="merged_to_dev", pr_number=DUMMY_MERGED_DEV_PR)
    client = RecordingClient(comments=[{"body": marker}])

    sync.apply_action(client, action)

    assert client.calls == [
        ("add_labels", 100, ("merged-to-dev", "needs-verification")),
        ("has_other_open_linked_pull_request", 100, DUMMY_MERGED_DEV_PR),
        ("remove_label", 100, "has-linked-pr"),
        ("list_comments", 100),
    ]


def test_apply_merged_dev_action_keeps_open_pr_label_when_another_pr_remains() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="merged_to_dev",
        pr_number=DUMMY_MERGED_DEV_PR,
        pr_url=DUMMY_MERGED_DEV_PR_URL,
    )
    client = RecordingClient(other_open_linked_issues={100})

    sync.apply_action(client, action)

    assert client.calls == [
        ("add_labels", 100, ("merged-to-dev", "needs-verification")),
        ("has_other_open_linked_pull_request", 100, DUMMY_MERGED_DEV_PR),
        ("list_comments", 100),
        (
            "create_comment",
            100,
            "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9001 -->\n"
            "The linked fix for this issue has merged to `dev` via #9001 "
            f"({DUMMY_MERGED_DEV_PR_URL}). "
            "Keeping it open for verification before release.",
        ),
    ]


def test_apply_open_linked_pr_action_adds_open_pr_label() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="linked_pr_open",
        pr_number=DUMMY_OPEN_PR,
        pr_url=DUMMY_OPEN_PR_URL,
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [("add_labels", 100, ("has-linked-pr",))]


def test_apply_remove_linked_pr_action_only_removes_open_pr_label() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=200,
        kind="remove_linked_pr",
        pr_number=DUMMY_MERGED_MAIN_PR,
        pr_url=DUMMY_MERGED_MAIN_PR_URL,
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [
        ("has_other_open_linked_pull_request", 200, DUMMY_MERGED_MAIN_PR),
        ("remove_label", 200, "has-linked-pr"),
    ]


def test_apply_closed_unmerged_action_only_removes_open_pr_label() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=200,
        kind="closed_unmerged",
        pr_number=DUMMY_CLOSED_PR,
        pr_url=DUMMY_CLOSED_PR_URL,
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [
        ("has_other_open_linked_pull_request", 200, DUMMY_CLOSED_PR),
        ("remove_label", 200, "has-linked-pr"),
    ]


def test_apply_remove_action_keeps_label_when_another_open_pr_links_issue() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=200,
        kind="closed_unmerged",
        pr_number=DUMMY_CLOSED_PR,
        pr_url=DUMMY_CLOSED_PR_URL,
    )
    client = RecordingClient(other_open_linked_issues={200})

    sync.apply_action(client, action)

    assert client.calls == [
        ("has_other_open_linked_pull_request", 200, DUMMY_CLOSED_PR),
    ]


def test_apply_merged_main_action_clears_dev_verification_labels() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="merged_to_main",
        pr_number=DUMMY_MERGED_MAIN_PR,
        pr_url=DUMMY_MERGED_MAIN_PR_URL,
    )
    client = RecordingClient()

    sync.apply_action(client, action)

    assert client.calls == [
        ("has_other_open_linked_pull_request", 100, DUMMY_MERGED_MAIN_PR),
        ("remove_label", 100, "has-linked-pr"),
        ("remove_label", 100, "merged-to-dev"),
        ("remove_label", 100, "needs-verification"),
    ]


def test_apply_merged_main_action_keeps_open_label_when_another_pr_remains() -> None:
    sync = _load_sync_module()
    action = sync.IssueSyncAction(
        issue_number=100,
        kind="merged_to_main",
        pr_number=DUMMY_MERGED_MAIN_PR,
        pr_url=DUMMY_MERGED_MAIN_PR_URL,
    )
    client = RecordingClient(other_open_linked_issues={100})

    sync.apply_action(client, action)

    assert client.calls == [
        ("has_other_open_linked_pull_request", 100, DUMMY_MERGED_MAIN_PR),
        ("remove_label", 100, "merged-to-dev"),
        ("remove_label", 100, "needs-verification"),
    ]


def test_github_client_detects_other_open_pull_requests_linking_issue() -> None:
    sync = _load_sync_module()
    client = PaginatedGitHubClient(
        [
            [
                {"number": DUMMY_OPEN_PR, "body": "Fixes #100"},
                {
                    "number": DUMMY_CLOSED_PR,
                    "body": "Refs #200",
                    "base": {"ref": "dev"},
                },
            ],
        ]
    )

    assert sync.GitHubClient.has_other_open_linked_pull_request(
        client,
        issue_number=200,
        pr_number=DUMMY_OPEN_PR,
    )
    assert client.paths == ["/pulls?state=open&per_page=100&page=1"]


def test_github_client_ignores_non_final_open_pull_requests_when_preserving_labels() -> None:
    sync = _load_sync_module()
    client = PaginatedGitHubClient(
        [
            [
                {
                    "number": DUMMY_OPEN_PR,
                    "body": "Refs #200",
                    "base": {"ref": "sandbox-optimization"},
                },
            ],
        ]
    )

    assert not sync.GitHubClient.has_other_open_linked_pull_request(
        client,
        issue_number=200,
        pr_number=DUMMY_CLOSED_PR,
    )
    assert client.paths == ["/pulls?state=open&per_page=100&page=1"]


def test_list_comments_reads_all_pages_before_idempotency_check() -> None:
    sync = _load_sync_module()
    client = PaginatedGitHubClient(
        [
            [{"body": f"old comment {index}"} for index in range(100)],
            [{"body": "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9001 -->"}],
        ]
    )

    comments = sync.GitHubClient.list_comments(client, 100)

    assert sync.has_marker(
        comments,
        "<!-- opensquilla-issue-link-sync:merged-to-dev:pr-9001 -->",
    )
    assert client.paths == [
        "/issues/100/comments?per_page=100&page=1",
        "/issues/100/comments?per_page=100&page=2",
    ]
