"""meta-ribbon.js DOM 渲染契约（静态 / 基于读文件 + 简易 string assert）。

完整 DOM 行为由 E2E browser 测试覆盖；本测试锁结构与字符串。
"""

from pathlib import Path

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")
RIBBON_CSS = Path("src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css")
CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
INDEX_HTML = Path("src/opensquilla/gateway/templates/index.html")


def test_ribbon_module_exists():
    assert RIBBON_JS.exists()
    text = RIBBON_JS.read_text()
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert f"function {name}" in text, f"missing function {name}"


def test_ribbon_exposes_window_global():
    text = RIBBON_JS.read_text()
    assert "root.MetaRibbon" in text or "window.MetaRibbon" in text
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert name in text, f"window.MetaRibbon missing {name}"


def test_ribbon_glyph_table_covers_all_states():
    text = RIBBON_JS.read_text()
    for state in ("pending", "running", "succeeded", "failed", "skipped", "substituted"):
        assert f"{state}:" in text, f"STATE_GLYPH missing {state}"


def test_ribbon_css_has_chip_state_classes():
    text = RIBBON_CSS.read_text()
    for cls in ("chip.pending", "chip.running", "chip.succeeded",
                "chip.failed", "chip.skipped", "chip.substituted"):
        assert cls in text, f"CSS missing {cls}"


def test_index_html_loads_ribbon_before_chat():
    text = INDEX_HTML.read_text()
    ribbon_pos = text.find("chat/meta-ribbon.js")
    chat_pos = text.find("views/chat.js")
    assert ribbon_pos != -1, "meta-ribbon.js not included"
    assert chat_pos != -1, "chat.js not included"
    assert ribbon_pos < chat_pos, "meta-ribbon.js must load before chat.js"


def test_index_html_loads_ribbon_css():
    text = INDEX_HTML.read_text()
    assert "chat-meta-ribbon.css" in text


def test_chat_js_references_window_metaribbon():
    text = CHAT_JS.read_text()
    assert "window.MetaRibbon" in text
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert name in text, f"chat.js missing {name} reference"


def test_chat_js_dispatches_meta_events():
    text = CHAT_JS.read_text()
    assert "session.event.meta_run_announced" in text
    assert "session.event.meta_step_state" in text
    assert "session.event.meta_run_completed" in text


def test_chat_js_handles_ribbon_action_events():
    text = CHAT_JS.read_text()
    assert "meta-ribbon-action" in text
    for action in ("retry-run", "switch-skill", "show-detail"):
        assert action in text, f"chat.js missing action {action}"
