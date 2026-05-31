from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PYTEST_STATE_ROOT = Path(tempfile.gettempdir()) / f"opensquilla-pytest-{os.getpid()}"

os.environ.setdefault("OPENSQUILLA_STATE_DIR", str(_PYTEST_STATE_ROOT / "state"))
os.environ.setdefault("OPENSQUILLA_LOG_DIR", str(_PYTEST_STATE_ROOT / "logs"))
os.environ.setdefault("OPENSQUILLA_TURN_CALL_LOG", "0")
