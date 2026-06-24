from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES_ROW = ROOT / "opensquilla-webui/src/components/chat/SourcesRow.vue"
CHAT_TYPES = ROOT / "opensquilla-webui/src/types/chat.ts"
RENDERED_MESSAGES = ROOT / "opensquilla-webui/src/composables/chat/useChatRenderedMessages.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sources_row_prefers_tool_call_sources_before_result_json() -> None:
    source = _read(SOURCES_ROW)

    call_sources_index = source.index("const directSources")
    record_sources_index = source.index("const recordSources")
    results_index = source.index("const results =")

    assert "extractSources(call.sources, out, seen)" in source
    assert "extractSources(record.sources, out, seen)" in source
    assert call_sources_index < record_sources_index < results_index


def test_chat_tool_call_type_and_history_normalizer_preserve_sources() -> None:
    types_source = _read(CHAT_TYPES)
    rendered_source = _read(RENDERED_MESSAGES)

    assert "sources?: unknown" in types_source
    raw_tool_call_payload_source = types_source[
        types_source.index("export interface RawToolCallPayload") :
    ]
    assert "sources?: unknown" in raw_tool_call_payload_source
    assert "sources: item.sources" in rendered_source
    assert "if (tc.sources !== undefined) item.sources = tc.sources" in rendered_source
