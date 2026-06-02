from __future__ import annotations

import pytest

from opensquilla.sandbox.domain_validation import (
    DomainDecision,
    normalize_domain,
    validate_domain_pattern,
)
from opensquilla.sandbox.package_bundles import (
    PACKAGE_BUNDLES,
    expand_package_bundle,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://PyPI.org/simple", "pypi.org"),
        ("registry.npmjs.org/", "registry.npmjs.org"),
        ("*.PythonHosted.org", "*.pythonhosted.org"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "127.0.0.1",
        "10.0.0.2",
        "169.254.169.254",
        "[::1]",
        "*.com",
        "*",
        "",
    ],
)
def test_validate_domain_pattern_blocks_unsafe_patterns(raw: str) -> None:
    decision = validate_domain_pattern(raw)
    assert decision.status == "blocked"


def test_validate_domain_pattern_allows_exact_and_narrow_wildcard() -> None:
    assert validate_domain_pattern("pypi.org") == DomainDecision(
        status="allowed",
        normalized="pypi.org",
        reason="exact_domain",
    )
    assert validate_domain_pattern("*.pythonhosted.org") == DomainDecision(
        status="allowed",
        normalized="*.pythonhosted.org",
        reason="wildcard_domain",
    )


def test_package_bundles_expand_to_known_domains() -> None:
    assert expand_package_bundle("python-package-install") == (
        "pypi.org",
        "files.pythonhosted.org",
    )
    assert "registry.npmjs.org" in expand_package_bundle("node-package-install")
    assert "rust-package-install" in PACKAGE_BUNDLES
