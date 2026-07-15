from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_current_user_docs_promote_bare_chat_to_auto_tui() -> None:
    current_docs = {
        path: _read(path)
        for path in (
            "README.md",
            "README.zh-Hans.md",
            "docs/quickstart.md",
            "docs/tui.md",
            "docs/cli.md",
            "docs/features/tui-frontend.md",
            "docs/features/tui-product-contract.md",
            "docs/tui-real-terminal-harness.md",
        )
    }

    assert "`opensquilla chat` uses `auto`" in _squash(
        current_docs["README.md"].lower()
    )
    assert "裸命令 `opensquilla chat` 使用 `auto`" in _squash(
        current_docs["README.zh-Hans.md"]
    )
    assert "The omitted `--ui` policy is `auto`." in _squash(current_docs["docs/cli.md"])
    assert "omitted `--ui` means `auto`" in _squash(
        current_docs["docs/features/tui-frontend.md"]
    )
    assert "Omitting `--ui` is equivalent to `auto`." in _squash(
        current_docs["docs/features/tui-product-contract.md"]
    )
    assert "launches bare `opensquilla chat --standalone`" in _squash(
        current_docs["docs/tui-real-terminal-harness.md"]
    )

    stale_rollout_copy = (
        "bare `opensquilla chat` remains",
        "keeps bare `opensquilla chat`",
        "seven-day observation",
        "next rollout release",
        "RC default and minimal rescue",
    )
    for path, text in current_docs.items():
        for stale in stale_rollout_copy:
            assert stale not in text, (path, stale)


def test_current_docs_describe_one_supported_full_screen_tui() -> None:
    product_contract = _squash(_read("docs/features/tui-product-contract.md"))
    harness = _squash(_read("docs/tui-real-terminal-harness.md"))

    assert "alternate-screen OpenTUI is the default terminal product" in product_contract
    assert "supported full-screen renderer" in harness
