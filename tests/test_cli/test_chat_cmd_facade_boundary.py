from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.cli import (
    chat_approval_prompts,
    chat_cmd,
    chat_standalone_transcript_rewrite,
)

ROOT = Path(__file__).resolve().parents[2]
CHAT_CMD = ROOT / "src" / "opensquilla" / "cli" / "chat_cmd.py"


def _defined_functions() -> set[str]:
    tree = ast.parse(CHAT_CMD.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_chat_cmd_reexports_approval_prompt_boundary_helpers() -> None:
    assert chat_cmd._maybe_handle_approval is chat_approval_prompts.maybe_handle_approval
    assert chat_cmd._local_approval_resolver is chat_approval_prompts.local_approval_resolver
    assert "_maybe_handle_approval" not in _defined_functions()
    assert "_local_approval_resolver" not in _defined_functions()


def test_chat_cmd_reexports_standalone_transcript_rewrite_helpers() -> None:
    assert (
        chat_cmd._read_standalone_transcript
        is chat_standalone_transcript_rewrite.read_standalone_transcript
    )
    assert (
        chat_cmd._flush_before_standalone_rewrite
        is chat_standalone_transcript_rewrite.flush_before_standalone_rewrite
    )
    assert "_read_standalone_transcript" not in _defined_functions()
    assert "_flush_before_standalone_rewrite" not in _defined_functions()
