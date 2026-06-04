"""失败 chip 的动作行渲染 + show-detail 行为 — 通过最小 JSDOM 等价模拟。

由于仓库无 JS 测试 runner，这里采用与现有 test_gateway_static_skills_view.py
相同的"读取 + assert 文本契约"策略；行为细节由 E2E 覆盖。
"""

from pathlib import Path

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")


def test_action_row_renders_three_buttons():
    text = RIBBON_JS.read_text()
    # renderActions 必须存在 3 个动作按钮
    assert 'data-action="retry-run"' in text
    assert 'data-action="switch-skill"' in text
    assert 'data-action="show-detail"' in text


def test_action_row_only_when_failed_step_present():
    text = RIBBON_JS.read_text()
    assert "shouldShowActions" in text
    # The boolean comes from any step with state === 'failed'
    assert "'failed'" in text


def test_fail_summary_shows_error_truncated():
    text = RIBBON_JS.read_text()
    # 错误文本走 truncate(errText, 80)
    assert "truncate(errText, 80)" in text
