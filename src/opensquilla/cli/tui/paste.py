"""Compatibility alias for terminal paste helpers."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.terminal import paste as _target

sys.modules[__name__] = _target
