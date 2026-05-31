"""Compatibility alias for terminal signal handlers."""

from __future__ import annotations

import sys

from opensquilla.cli.tui.terminal import signals as _target

sys.modules[__name__] = _target
