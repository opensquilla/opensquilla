"""Compatibility alias for the TUI-owned terminal chat adapter."""

from __future__ import annotations

import sys

from opensquilla.cli.tui import terminal_chat_adapter as _target

sys.modules[__name__] = _target
