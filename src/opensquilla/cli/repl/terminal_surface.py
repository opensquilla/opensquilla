"""Compatibility alias for the TUI-owned terminal surface."""

from __future__ import annotations

import sys

from opensquilla.cli.tui import terminal_surface as _target

sys.modules[__name__] = _target
