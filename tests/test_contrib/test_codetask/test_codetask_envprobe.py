"""Unit tests for opensquilla.contrib.codetask.envprobe."""

from opensquilla.contrib.codetask import envprobe


def _make_repo(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def test_python_uv_project(tmp_path):
    repo = _make_repo(
        tmp_path,
        {"pyproject.toml": "[project]", "uv.lock": "", ".github/workflows/ci.yml": "on: push"},
    )
    p = envprobe.probe(repo)
    assert "Python" in p.languages
    assert "uv" in p.package_managers
    assert ".github/workflows/ci.yml" in p.ci_files
    hints = p.as_hints()
    assert "Python" in hints
    assert "CI config" in hints


def test_node_pnpm_project(tmp_path):
    repo = _make_repo(tmp_path, {"package.json": "{}", "pnpm-lock.yaml": ""})
    p = envprobe.probe(repo)
    assert "JavaScript/TypeScript" in p.languages
    assert "pnpm" in p.package_managers


def test_go_project(tmp_path):
    repo = _make_repo(tmp_path, {"go.mod": "module x", "Makefile": ""})
    p = envprobe.probe(repo)
    assert "Go" in p.languages
    assert "Makefile" in p.notable


def test_empty_repo_only_host_os_hint(tmp_path):
    p = envprobe.probe(tmp_path)
    hints = p.as_hints()
    # An empty repo still gets the always-on Host OS line (intentional),
    # but no language / package-manager / CI hints.
    assert "Host OS:" in hints
    assert "Language(s):" not in hints
