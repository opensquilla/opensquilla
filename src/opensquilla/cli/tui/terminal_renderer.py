"""Compatibility alias for the terminal renderer."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.terminal import renderer as _target

sys.modules[__name__] = _target
