"""Guard the lazy-loading discipline of the swebench contrib package.

The SWE-bench harness is an optional feature: importing opensquilla must
not import it, and importing the harness's light modules must not pull in
the heavy optional dependencies (datasets).
"""

import subprocess
import sys


def _run_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_opensquilla_import_does_not_load_swebench():
    result = _run_python(
        "import sys\n"
        "import opensquilla\n"
        "assert 'opensquilla.contrib.swebench' not in sys.modules, "
        "'startup path must not import the swebench harness'\n"
    )
    assert result.returncode == 0, result.stderr


def test_light_modules_do_not_import_datasets():
    result = _run_python(
        "import sys\n"
        "import opensquilla.contrib.swebench\n"
        "import opensquilla.contrib.swebench.config\n"
        "import opensquilla.contrib.swebench.patch\n"
        "import opensquilla.contrib.swebench.prediction\n"
        "import opensquilla.contrib.swebench.prompt\n"
        "import opensquilla.contrib.swebench.workspace\n"
        "import opensquilla.contrib.swebench.agent\n"
        "import opensquilla.contrib.swebench.types\n"
        "assert 'datasets' not in sys.modules, "
        "'light modules must not import the datasets package'\n"
    )
    assert result.returncode == 0, result.stderr
