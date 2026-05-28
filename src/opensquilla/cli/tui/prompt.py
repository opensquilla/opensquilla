"""Compatibility alias for the terminal prompt adapter."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.terminal import prompt as _target

sys.modules[__name__] = _target
