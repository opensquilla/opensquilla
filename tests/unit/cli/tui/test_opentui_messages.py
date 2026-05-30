from __future__ import annotations

import pytest

from opensquilla.cli.tui.opentui.messages import (
    HostInputCancel,
    HostInputEof,
    HostInputSubmit,
    HostReady,
    HostResize,
    HostToPythonMessageError,
    RouterPluginState,
    host_message_from_json,
    python_message_to_json,
)


def test_python_message_to_json_serializes_router_update() -> None:
    payload = python_message_to_json(
        "router.update",
        RouterPluginState(
            model="gpt-5.5",
            route="T3 | 91%",
            saving="42% | -$0.021",
            context="128k | 37%",
            style="normal",
        ),
    )

    assert payload.endswith("\n")
    assert '"type":"router.update"' in payload
    assert '"model":"gpt-5.5"' in payload
    assert '"route":"T3 | 91%"' in payload


def test_host_message_from_json_parses_ready_and_submit() -> None:
    assert host_message_from_json('{"type":"ready"}') == HostReady()
    assert host_message_from_json(
        '{"type":"input.submit","text":"中文 prompt"}'
    ) == HostInputSubmit(text="中文 prompt")


def test_host_message_from_json_parses_control_messages() -> None:
    assert host_message_from_json('{"type":"input.cancel"}') == HostInputCancel()
    assert host_message_from_json('{"type":"input.eof"}') == HostInputEof()
    assert host_message_from_json('{"type":"resize","width":120,"height":36}') == (
        HostResize(width=120, height=36)
    )


def test_host_message_rejects_malformed_control_payloads() -> None:
    with pytest.raises(HostToPythonMessageError, match="input.submit.text"):
        host_message_from_json('{"type":"input.submit"}')

    with pytest.raises(HostToPythonMessageError, match="resize.width"):
        host_message_from_json('{"type":"resize","height":36}')

    with pytest.raises(HostToPythonMessageError, match="Unknown OpenTUI host"):
        host_message_from_json('{"type":"surprise"}')
