"""Compatibility alias for the TUI-owned terminal signal handlers."""

from __future__ import annotations

import sys

from opensquilla.cli.tui import signal_handlers as _target

sys.modules[__name__] = _target
