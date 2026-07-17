"""The layering constraint that decides where the profile validator lives.

``self_learning`` must not import from ``opensquilla.provider``. This is not
housekeeping: it is the whole reason ``validate_user_profile`` sits in
``ranking_router.py``, next to the vocabularies it enforces, and is called from
the engine seam that already imports both sides.

Without a test the constraint is a docstring. Someone adds one import to
"simplify", nothing fails, and the justification for the split placement
evaporates — at which point moving the validator back into ``profile.py`` looks
like a cleanup rather than a layering break. The edge count is the thing that
has to fail, because by the time the placement looks arbitrary the argument for
it is already gone.

Imports are read from the AST rather than grepped: ``profile.py``'s module
docstring names ``opensquilla.provider`` to explain this rule, and a textual
search cannot tell that apart from an actual import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import opensquilla.squilla_router.self_learning as self_learning_pkg

_FORBIDDEN = "opensquilla.provider"
_PACKAGE_ROOT = Path(self_learning_pkg.__file__).parent


def _imported_modules(source: str) -> set[str]:
    """Every module named by an import in ``source``.

    ``from x import y`` contributes ``x``; ``import x.y`` contributes ``x.y``.
    Relative imports have no module path to compare and are in-package by
    definition, so they cannot reach ``provider``.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_self_learning_never_imports_provider() -> None:
    offenders: list[str] = []
    files = sorted(_PACKAGE_ROOT.rglob("*.py"))
    assert files, "found no modules to check — the glob is wrong, not the layer"

    for path in files:
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if module == _FORBIDDEN or module.startswith(f"{_FORBIDDEN}."):
                offenders.append(f"{path.relative_to(_PACKAGE_ROOT)} -> {module}")

    assert offenders == [], (
        "self_learning must not import from opensquilla.provider. This edge is "
        "why validate_user_profile lives in ranking_router.py rather than in "
        "profile.py; adding it makes that placement look arbitrary.\n"
        + "\n".join(offenders)
    )
