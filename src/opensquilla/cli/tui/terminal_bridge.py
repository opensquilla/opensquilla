"""Compatibility alias for terminal chat bridge."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.adapters import terminal_bridge as _target

sys.modules[__name__] = _target
