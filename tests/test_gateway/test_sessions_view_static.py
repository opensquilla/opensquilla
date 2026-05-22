from pathlib import Path

SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")


def test_single_session_delete_checks_backend_partial_failure_response() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")
    start = source.index("function _deleteSession(key)")
    end = source.index("  async function _openNewSessionModal()", start)
    body = source[start:end]

    assert "const res = await _rpc.call('sessions.delete', { key });" in body
    assert "res.errors" in body
    assert "res.deleted" in body
    assert "deleted.includes(key)" in body
    assert "typeof first === 'string'" in body
    assert "Session deleted" in body
    assert "Delete failed" in body
    assert body.index("res.errors") < body.index("Session deleted")
