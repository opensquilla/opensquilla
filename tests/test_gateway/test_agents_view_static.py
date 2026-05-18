"""Static smoke tests for the WebUI agents view + new UI primitives."""

from pathlib import Path

AGENTS_JS = Path("src/opensquilla/gateway/static/js/views/agents.js")
AGENTS_CSS = Path("src/opensquilla/gateway/static/css/views/agents.css")
SESSIONS_JS = Path("src/opensquilla/gateway/static/js/views/sessions.js")
SESSIONS_CSS = Path("src/opensquilla/gateway/static/css/views/sessions.css")
COMPONENTS_JS = Path("src/opensquilla/gateway/static/js/components.js")
COMPONENTS_CSS = Path("src/opensquilla/gateway/static/css/components.css")


def test_agents_view_keeps_inline_create_form_and_drawer_for_view_edit() -> None:
    source = AGENTS_JS.read_text(encoding="utf-8")

    # Lightweight inline create form is the only create entry point.
    assert 'id="agent-add-form"' in source
    assert "_onInlineAdd" in source
    assert "_rpc.call('agents.create'" in source

    # View / edit goes through the drawer; create does NOT.
    assert "_openAgentDrawer" in source
    assert "UI.drawer(" in source
    assert "data-edit-agent" in source
    assert "data-customize-agent" in source

    # No native confirm() dialogs (custom modal stand-in instead).
    assert "confirm(" not in source

    # Brain section was removed from the drawer (no Model / System prompt edit).
    assert "data-bind=\"systemPrompt\"" not in source
    assert "data-bind=\"model\"" not in source

    # Update RPC still wired for the remaining editable fields.
    assert "_rpc.call('agents.update'" in source
    assert "_rpc.call('agents.delete'" in source

    # Builtin agents render Customize… (which pre-fills the inline form).
    assert "Customize" in source


def test_agents_view_css_has_inline_form_and_drawer_styles() -> None:
    css = AGENTS_CSS.read_text(encoding="utf-8")

    # Inline create form selectors are present.
    assert ".ag-create" in css
    assert ".ag-create__form" in css

    # Drawer selectors used by view/edit are present.
    assert ".ag-drawer__sections" in css
    assert ".ag-drawer__section" in css

    # Dead "live preview" rules were pruned.
    assert ".ag-drawer__preview" not in css
    assert ".ag-drawer__layout" not in css


def test_sessions_view_uses_combobox_and_admin_agent_create_rpc() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")

    assert "UI.combobox(" in source
    assert "_rpc.call('agents.create'" in source
    assert "_rpc.call('sessions.create'" in source
    assert "createAgentIfMissing" not in source
    # Inline error rendering keeps the modal open on RPC failure.
    assert "data-ns-error" in source
    # Optional Model input was removed — sessions inherit the agent default.
    assert 'id="ns-model"' not in source
    # Orphan-agent badge wiring.
    assert "_agentSubline" in source
    assert "_agentsById" in source
    assert "Orphaned" in source


def test_sessions_view_css_has_orphan_chip_styles() -> None:
    css = SESSIONS_CSS.read_text(encoding="utf-8")
    assert ".chip-warn" in css
    assert ".sess-key__sub" in css
    assert ".sess-key__agent--orphan" in css


def test_sessions_table_keeps_table_cells_structural() -> None:
    source = SESSIONS_JS.read_text(encoding="utf-8")
    css = SESSIONS_CSS.read_text(encoding="utf-8")

    assert '<td class="sess-table__cell--key">' in source
    assert '<div class="sess-table__key-content">' in source
    key_cell_start = css.index(".sess-table__cell--key {")
    key_cell_rule = css[key_cell_start : css.index("}", key_cell_start)]
    assert "display:" not in key_cell_rule
    assert ".sess-table__key-content" in css
    assert "display: flex" in css[css.index(".sess-table__key-content") :]


def test_components_js_exposes_drawer_and_combobox() -> None:
    source = COMPONENTS_JS.read_text(encoding="utf-8")

    # Public exports on UI singleton.
    assert "drawer," in source and "combobox," in source

    # Promise-based drawer + beforeClose hook.
    assert "beforeClose" in source
    assert "result =" in source or "result:" in source

    # Combobox create-on-miss API surface.
    assert "allowCreate" in source
    assert "onCreate" in source
    assert "removeEventListener('mousedown'" in source
    # Keyboard nav is wired (basic substring smoke).
    assert "ArrowDown" in source and "ArrowUp" in source


def test_components_css_has_drawer_and_combobox_styles() -> None:
    css = COMPONENTS_CSS.read_text(encoding="utf-8")

    # Drawer scaffolding.
    assert ".drawer-backdrop" in css
    assert ".drawer__head" in css
    assert ".drawer__body" in css
    assert ".drawer__foot" in css

    # Combobox scaffolding.
    assert ".ui-combo" in css
    assert ".ui-combo__list" in css
    assert ".ui-combo__option--create" in css
