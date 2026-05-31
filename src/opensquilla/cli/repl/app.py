"""Compatibility alias for the TUI-owned terminal application driver."""

from __future__ import annotations

import sys

from opensquilla.cli.tui import app as _target

sys.modules[__name__] = _target
