"""Unit tests for opensquilla.contrib.codetask.inputs."""

import pytest

from opensquilla.contrib.codetask import inputs
from opensquilla.contrib.codetask.inputs import InputError, TaskSpec, resolve_task


class TestResolveMutualExclusion:
    def test_none_given(self):
        with pytest.raises(InputError, match="No task"):
            resolve_task()

    def test_two_given(self):
        with pytest.raises(InputError, match="only one"):
            resolve_task(task_text="x", issue_number=1)


class TestInlineAndFile:
    def test_inline(self):
        spec = resolve_task(task_text="Add CSV BOM support so Excel opens it")
        assert spec.source == "inline"
        assert spec.title.startswith("Add CSV BOM")
        assert spec.slug

    def test_inline_empty(self):
        with pytest.raises(InputError, match="empty"):
            resolve_task(task_text="   ")

    def test_task_file(self, tmp_path):
        f = tmp_path / "req.md"
        f.write_text("# Big feature\n\nDetails here.")
        spec = resolve_task(task_file=str(f))
        assert spec.source == "file"
        assert "Big feature" in spec.title

    def test_task_file_missing(self, tmp_path):
        with pytest.raises(InputError, match="not found"):
            resolve_task(task_file=str(tmp_path / "nope.md"))


class TestIssuePreflight:
    def test_gh_missing_raises_hint(self, monkeypatch):
        monkeypatch.setattr(inputs, "gh_available", lambda: False)
        with pytest.raises(InputError, match="GitHub CLI"):
            resolve_task(issue_number=123)


class TestRenderTaskMd:
    def test_frontmatter_and_body(self):
        spec = TaskSpec(source="inline", title="Fix it", body="The bug is here.", slug="fix-it")
        md = render_task_md_helper(spec)
        assert "source: inline" in md
        assert "# Fix it" in md
        assert "The bug is here." in md

    def test_comments_truncation(self):
        spec = TaskSpec(
            source="github-issue",
            title="Big",
            body="body",
            slug="big",
            comments=["x" * 20000 for _ in range(5)],
        )
        md = render_task_md_helper(spec)
        assert spec.truncated is True
        assert "truncated" in md


def render_task_md_helper(spec):
    from opensquilla.contrib.codetask.inputs import render_task_md

    return render_task_md(spec, repo="org/proj", base_ref="main", commit="abc1234")
