"""Compatibility alias for the TUI-owned terminal bridge."""

from __future__ import annotations

import sys

from opensquilla.cli.tui import terminal_bridge as _target

sys.modules[__name__] = _target
