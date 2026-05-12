from __future__ import annotations

from pathlib import Path

LOGS_JS = Path("src/opensquilla/gateway/static/js/views/logs.js")
CONFIG_JS = Path("src/opensquilla/gateway/static/js/views/config.js")
CONFIG_EXAMPLE = Path("opensquilla.toml.example")


def test_logs_view_describes_configurable_debug_logging() -> None:
    source = LOGS_JS.read_text(encoding="utf-8")

    assert "Gateway file logging is configurable" in source
    assert "logs.status" in source
    assert "Raw turn-call capture is enabled by" in source
    assert "opensquilla diagnostics on --raw" in source
    assert "OPENSQUILLA_LOG_DIR" in source
    assert "OPENSQUILLA_TURN_CALL_LOG=1" in source


def test_config_view_explains_debug_file_logging_fields() -> None:
    source = CONFIG_JS.read_text(encoding="utf-8")

    assert "'debug'" in source
    assert "Security-sensitive developer mode" in source
    assert "'diagnostics_enabled'" in source
    assert "Default standard diagnostics mode" in source
    assert "'log_file_enabled'" in source
    assert "'log_level'" in source
    assert "'log_file_max_bytes'" in source
    assert "'log_file_backup_count'" in source


def test_example_config_lists_debug_file_logging_controls() -> None:
    source = CONFIG_EXAMPLE.read_text(encoding="utf-8")

    assert "log_file_enabled" in source
    assert "log_level" in source
    assert "log_file_max_bytes" in source
    assert "log_file_backup_count" in source
    assert "diagnostics_enabled enables standard diagnostics" in source
    assert "OPENSQUILLA_TURN_CALL_LOG=1" in source
