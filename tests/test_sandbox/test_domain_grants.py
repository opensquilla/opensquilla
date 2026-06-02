from __future__ import annotations

import pytest

from opensquilla.sandbox.domain_validation import (
    DomainDecision,
    domain_matches,
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
        "127.1",
        "0177.0.0.1",
        "10.0.0.2",
        "169.254.169.254",
        "8.8.8.8",
        "[::1]",
        "2606:4700:4700::1111",
        "*.com",
        "*.co.uk",
        "*.github.io",
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
    assert expand_package_bundle("unknown") == ()


@pytest.mark.parametrize(
    "raw",
    [
        "example..com",
        "-example.com",
        "example.com-",
        "exa_mple.com",
    ],
)
def test_validate_domain_pattern_blocks_malformed_hostnames(raw: str) -> None:
    decision = validate_domain_pattern(raw)
    assert decision.status == "blocked"


def test_domain_matches_exact_domain() -> None:
    assert domain_matches("pypi.org", "pypi.org")
    assert not domain_matches("pypi.org", "files.pythonhosted.org")


def test_domain_matches_wildcard_subdomain_and_excludes_apex() -> None:
    assert domain_matches("*.pythonhosted.org", "files.pythonhosted.org")
    assert not domain_matches("*.pythonhosted.org", "pythonhosted.org")


def test_domain_matches_requires_label_boundary() -> None:
    assert not domain_matches("*.pythonhosted.org", "notpythonhosted.org")


def test_domain_matches_returns_false_for_invalid_pattern() -> None:
    assert not domain_matches("*.github.io", "project.github.io")
