"""Theme catalog and the ``/theme`` command for the OpenTUI footer host.

The themes themselves live in the JS host (``package/src/theme.mjs``). This module
only mirrors the theme NAMES so the CLI can list/validate them and drive live
switching by sending a ``theme.set`` IPC message through the OpenTUI output handle.
The name list is kept in sync with ``theme.mjs`` by a conformance test.
"""

from __future__ import annotations

# Must equal the keys of PALETTES in
# src/opensquilla/cli/tui/opentui/package/src/theme.mjs (enforced by
# tests/unit/cli/tui/test_opentui_themes.py::test_theme_names_match_js_registry).
THEME_NAMES: tuple[str, ...] = (
    "opensquilla-dark",
    "opensquilla-light",
    "midnight",
    "ember",
    "slate",
    "high-contrast",
    "nord",
    "mono",
)
DEFAULT_THEME = "opensquilla-dark"
THEME_ENV_VAR = "OPENSQUILLA_TUI_THEME"


async def handle_theme_command(cmd: str, tui_output: object | None) -> None:
    """Handle ``/theme`` and ``/theme <name>`` (OpenTUI only).

    ``/theme <name>`` switches directly; bare ``/theme`` (or an unknown name)
    opens the interactive picker in the host (arrow-key live preview). Both are
    driven over the host output handle, so the host renders a panel rather than
    dumping a list into the scrollback. On the native backend (no
    ``send_message``) it explains that themes apply to the OpenTUI backend.
    """
    send_message = getattr(tui_output, "send_message", None)
    # The plugin wrapper always exposes a callable send_message that silently
    # no-ops on the native backend, so callable() alone can't distinguish an
    # IPC-capable OpenTUI surface from a native terminal. Prefer the wrapper's
    # explicit capability flag; fall back to callable() for an unwrapped handle.
    supports = getattr(tui_output, "supports_send_message", None)
    if supports is None:
        supports = callable(send_message)
    if not supports or not callable(send_message):
        from opensquilla.cli.ui import console  # noqa: PLC0415 - keep module import-light

        console.print(
            "[yellow]Themes apply to the OpenTUI backend "
            "(set OPENSQUILLA_TUI_BACKEND=opentui).[/yellow]"
        )
        return

    parts = cmd.split()
    if len(parts) >= 2:
        name = parts[1].strip().lower()
        if name in THEME_NAMES:
            await send_message("theme.set", {"name": name})
            return

    # No name, or an unknown one: open the interactive picker in the host.
    await send_message("theme.pick", {})
