from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RPC_SESSIONS = ROOT / "src/opensquilla/gateway/rpc_sessions.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_from(tree: ast.Module) -> set[tuple[str, str]]:
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def test_rpc_sessions_facade_only_registers_session_handlers() -> None:
    tree = _tree(RPC_SESSIONS)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    constants = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    imports = _imports_from(tree)

    disallowed_helpers = {
        "_optional_stream_seq",
        "_buffer_session_event",
        "_resolve_attachments",
        "_validate_attachments",
        "_require_key",
        "_context_window_tokens",
        "_effective_compaction_model",
        "_resolve_compaction_provider",
        "_model_value",
        "_agent_registry_model",
        "_agent_registry_has",
        "_session_turn_model",
        "_list_task_rows",
        "_list_task_rows_by_session",
        "_create_session_key",
        "_resolve_session_node",
        "_emit_to_subscribers",
        "_increment_and_emit_epoch",
    }
    disallowed_constants = {
        "_ALLOWED_MEDIA_TYPES",
        "_MAX_ATTACHMENT_BYTES",
        "_MAX_STAGED_PDF_BYTES",
        "_MAX_TEXT_ATTACHMENT_BYTES",
        "_MAX_TOTAL_ATTACHMENT_BYTES",
        "_MAX_ATTACHMENTS",
        "_attachment_media_type",
        "_normalize_attachments",
        "_sniff_mime_from_bytes",
        "_drain_task_runtime_for_reset",
    }
    disallowed_imports = {
        ("opensquilla.gateway", "rpc_session_send_inputs"),
        ("opensquilla.gateway.rpc_compaction_inputs", "context_window_tokens"),
        ("opensquilla.gateway.rpc_compaction_inputs", "effective_compaction_model"),
        ("opensquilla.gateway.rpc_compaction_inputs", "resolve_compaction_provider"),
        ("opensquilla.gateway.rpc_session_send_inputs", "resolve_session_attachments"),
        ("opensquilla.gateway.rpc_session_send_inputs", "validate_session_attachments"),
    }

    assert disallowed_helpers.isdisjoint(functions)
    assert disallowed_constants.isdisjoint(constants)
    assert disallowed_imports.isdisjoint(imports)
    assert all(name.startswith("_handle_sessions_") for name in functions)
