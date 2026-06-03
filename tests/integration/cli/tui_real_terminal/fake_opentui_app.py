from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tui_real_terminal.replay import replay_architecture_prompt
else:
    from replay import replay_architecture_prompt

from opensquilla.cli.chat.turn import UsageSummary  # type: ignore[import-untyped]
from opensquilla.cli.tui.opentui.renderer import (
    OpenTuiStreamRenderer,  # type: ignore[import-untyped]
)
from opensquilla.cli.tui.opentui.runtime import (  # type: ignore[import-untyped]
    get_tui_output,
    run_opentui_chat_runtime,
)
from opensquilla.engine.commands import Surface  # type: ignore[import-untyped]


def _app_log_path() -> Path:
    return Path(os.environ["OPENSQUILLA_TUI_FAKE_APP_LOG"])


def _write_log(event: str, payload: dict[str, Any] | None = None) -> None:
    path = _app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, "payload": payload or {}}, sort_keys=True) + "\n")


async def _render_response(
    scope: dict[str, Any],
    user_input: str,
    scenario_id: str,
) -> bool:
    if user_input.strip() in {"/exit", "exit"}:
        _write_log("exit")
        return False

    output = get_tui_output(scope)
    if output is None:
        raise RuntimeError("opentui output handle was not exposed")

    renderer = OpenTuiStreamRenderer(title="squilla", output_handle=output)
    usage = UsageSummary(model="fake-terminal", input_tokens=1, output_tokens=2)
    _write_log("dispatch", {"input": user_input, "scenario_id": scenario_id})
    if scenario_id == "long_streaming":
        for index in range(80):
            await renderer.aappend_text(f"stream-token-{index:03d} ")
            if index % 20 == 0:
                await asyncio.sleep(0)
    elif scenario_id == "complex_ui_state":
        _set_toolbar(output, "router_hud", "route standard -> fake-terminal 99% save 42%")
        _set_toolbar(output, "router_hud_style", "normal")
        _invalidate(output)
        await renderer.astatus("router route standard -> fake-terminal 99% save 42%")
        # Mirror the real turn shape so the harness exercises all three block
        # kinds:
        #   1. reasoning — the model's extended-thinking PROCESS, collapsed to a
        #      transient "Thinking…" marker, its verbatim text never shown.
        await renderer.aappend_reasoning(
            "reasoning-process-should-stay-hidden "
            + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 6
        )
        #   2. assistant text the model speaks before a tool call — streams into
        #      a purple intermediate narration block.
        await renderer.aappend_text(
            "intermediate-before-tool narration "
            + "0123456789" * 10
            + "\nsecond-intermediate-line tail",
            presentation="intermediate",
        )
        await renderer.atool_start("fake_tool", {"path": "fixture.txt"}, "tool-1")
        await renderer.atool_finished("tool-1", success=True, elapsed=0.01)
        await renderer.astatus("approval requested: allow fake_tool fixture.txt")
        #   3. final answer — the cyan answer card.
        await renderer.aappend_text(
            "complex-state-complete tool-card history projection",
            presentation="answer",
        )
    elif scenario_id == "architecture_prompt":
        usage = await replay_architecture_prompt(renderer, output)
    elif scenario_id == "terminal_changes":
        await renderer.aappend_text(
            "terminal-change-response CJK混合ASCII multiline-paste ctrl-c-recovery "
            "wide-and-narrow-layout"
        )
    else:
        await renderer.aappend_text(f"fake-response:{user_input}")
    await renderer.afinalize(usage)
    _write_log("turn_complete", {"input": user_input})
    return True


def _set_toolbar(output: Any, key: str, value: object | None) -> None:
    setter = getattr(output, "set_toolbar", None)
    if callable(setter):
        setter(key, value)


def _invalidate(output: Any) -> None:
    invalidate = getattr(output, "invalidate", None)
    if callable(invalidate):
        invalidate()


async def _run() -> None:
    scenario_id = os.environ.get("OPENSQUILLA_TUI_FAKE_SCENARIO", "launch_input_loop")
    scope: dict[str, Any] = {
        "model": "fake-terminal",
        "session_key": f"fake:{scenario_id}",
    }
    _write_log("ready", {"scenario_id": scenario_id})
    await run_opentui_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=lambda user_input: _render_response(scope, user_input, scenario_id),
        queue_max_size=4,
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
