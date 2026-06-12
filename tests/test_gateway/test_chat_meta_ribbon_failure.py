"""失败 chip 的动作行渲染 + show-detail 行为 — 通过最小 JSDOM 等价模拟。

由于仓库无 JS 测试 runner，这里采用与现有 test_gateway_static_skills_view.py
相同的"读取 + assert 文本契约"策略；行为细节由 E2E 覆盖。
"""

from pathlib import Path

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_action_row_renders_three_buttons():
    text = _read_text(RIBBON_JS)
    # renderActions 必须存在 3 个动作按钮
    assert 'data-action="retry-run"' in text
    assert 'data-action="switch-skill"' in text
    assert 'data-action="show-detail"' in text
    assert "rescue.actions" in text
    assert "retry-step" in text
    assert "install-dependency" in text


def test_action_row_only_when_failed_step_present():
    text = _read_text(RIBBON_JS)
    assert "shouldShowActions" in text
    # The boolean is gated by terminal failed outcome, not by a recovered failover.
    assert "runOutcome === 'failed'" in text
    assert "'failed'" in text


def test_fail_summary_shows_error_truncated():
    text = _read_text(RIBBON_JS)
    # 错误文本走 truncate(errText, 80)
    assert "truncate(errText, 80)" in text


def test_substitute_glyph_survives_later_success_state():
    text = _read_text(RIBBON_JS)
    assert "function stepGlyph" in text
    assert "step.substituteFor ? STATE_GLYPH.substituted" in text


def test_complete_run_reconciles_terminal_step_lists():
    text = _read_text(RIBBON_JS)
    body = text[text.index("function completeRun"):text.index("function renderRibbon")]
    for field in ("completed_steps", "failed_steps", "recovered_steps", "skipped_steps"):
        assert field in body
    assert "step.state = 'substituted'" in body
    assert "step.state = 'succeeded'" in body
    assert "step.state = 'skipped'" in body
    assert "step.state = 'failed'" in body
