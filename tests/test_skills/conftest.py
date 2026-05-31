"""Test-package setup for ``tests/test_skills``.

Adds this directory to ``sys.path`` so adjacent helper packages (e.g.
``router_fixtures``) can be imported by test modules without dotted
``tests.test_skills`` prefixes — the tree is not a Python package
(no ``__init__.py`` chain) and pytest's automatic rootdir handling
only makes the project root importable, not the test subdirectories.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
