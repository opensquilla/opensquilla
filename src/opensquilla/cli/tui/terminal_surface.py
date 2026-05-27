"""Compatibility alias for the terminal surface adapter."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.terminal import surface as _target

sys.modules[__name__] = _target
