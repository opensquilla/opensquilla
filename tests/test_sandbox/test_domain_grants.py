from __future__ import annotations

import pytest

from opensquilla.sandbox.domain_validation import (
    DomainDecision,
    domain_matches,
    normalize_domain,
    validate_domain_pattern,
)
from opensquilla.sandbox.package_bundles import (
    DEFAULT_PACKAGE_BUNDLE_IDS,
    PACKAGE_BUNDLES,
    expand_package_bundle,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://PyPI.org/simple", "pypi.org"),
        ("registry.npmjs.org/", "registry.npmjs.org"),
        ("*.PythonHosted.org", "*.pythonhosted.org"),
        (".example.com", ".example.com"),
        ("..Example.com..", "..example.com.."),
        ("http://[v6.invalid]", ""),
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
        "0x7f.0.0.1",
        "0x7f.1",
        "10.0.0.2",
        "169.254.169.254",
        "8.8.8.8",
        "[::1]",
        "2606:4700:4700::1111",
        "*.com",
        "*.co.uk",
        "*.github.io",
        "*.pages.dev",
        "*.appspot.com",
        "*.cloudfront.net",
        "*.azurewebsites.net",
        "*.example.com",
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
    assert validate_domain_pattern("3m.com") == DomainDecision(
        status="allowed",
        normalized="3m.com",
        reason="exact_domain",
    )
    assert validate_domain_pattern("example.com") == DomainDecision(
        status="allowed",
        normalized="example.com",
        reason="exact_domain",
    )
    assert validate_domain_pattern("example.com:443") == DomainDecision(
        status="allowed",
        normalized="example.com",
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
        "pypi.python.org",
        "bootstrap.pypa.io",
        "python-poetry.org",
        "install.python-poetry.org",
    )
    assert expand_package_bundle("node-package-install") == (
        "registry.npmjs.org",
        "registry.yarnpkg.com",
        "yarnpkg.com",
        "nodejs.org",
        "unpkg.com",
        "cdn.jsdelivr.net",
    )
    assert expand_package_bundle("rust-package-install") == (
        "crates.io",
        "static.crates.io",
        "index.crates.io",
        "github.com",
        "objects.githubusercontent.com",
    )
    assert expand_package_bundle("go-package-install") == (
        "proxy.golang.org",
        "sum.golang.org",
        "go.dev",
        "golang.org",
        "storage.googleapis.com",
    )
    assert expand_package_bundle("java-package-install") == (
        "repo.maven.apache.org",
        "repo1.maven.org",
        "plugins.gradle.org",
        "services.gradle.org",
    )
    assert expand_package_bundle("php-package-install") == (
        "packagist.org",
        "repo.packagist.org",
        "getcomposer.org",
    )
    assert "rust-package-install" in PACKAGE_BUNDLES
    assert DEFAULT_PACKAGE_BUNDLE_IDS == tuple(PACKAGE_BUNDLES)
    assert expand_package_bundle("unknown") == ()


@pytest.mark.parametrize(
    "raw",
    [
        ".example.com",
        "..example.com..",
        "example..com",
        "-example.com",
        "example.com-",
        "exa_mple.com",
        "*.*.example.com",
        "foo.*.example.com",
        "*.",
        "example.com:abc",
        "example.com:１２３",
    ],
)
def test_validate_domain_pattern_blocks_malformed_hostnames(raw: str) -> None:
    decision = validate_domain_pattern(raw)
    assert decision.status == "blocked"


@pytest.mark.parametrize(
    "raw",
    [
        "https://[::1]foo",
        "http://[]",
        "http://[v6.invalid]",
    ],
)
def test_validate_domain_pattern_blocks_malformed_bracketed_url_hosts(raw: str) -> None:
    try:
        decision = validate_domain_pattern(raw)
    except ValueError as exc:
        pytest.fail(f"validate_domain_pattern raised {exc!r}")
    assert decision.status == "blocked"


def test_validate_domain_pattern_blocks_huge_port_without_raising() -> None:
    raw = "example.com:" + ("9" * 5000)
    try:
        decision = validate_domain_pattern(raw)
    except ValueError as exc:
        pytest.fail(f"validate_domain_pattern raised {exc!r}")
    assert decision.status == "blocked"


def test_domain_matches_exact_domain() -> None:
    assert domain_matches("pypi.org", "pypi.org")
    assert not domain_matches("pypi.org", "files.pythonhosted.org")
    assert domain_matches("example.com", "example.com:443")


def test_domain_matches_wildcard_subdomain_and_excludes_apex() -> None:
    assert domain_matches("*.pythonhosted.org", "files.pythonhosted.org")
    assert not domain_matches("*.pythonhosted.org", "pythonhosted.org")


def test_domain_matches_requires_label_boundary() -> None:
    assert not domain_matches("*.pythonhosted.org", "notpythonhosted.org")


def test_domain_matches_returns_false_for_invalid_pattern() -> None:
    assert not domain_matches("*.github.io", "project.github.io")
    assert not domain_matches("*.example.com", "api.example.com")
    assert not domain_matches("foo.*.example.com", "foo.api.example.com")


@pytest.mark.parametrize(
    "host",
    [
        ".pypi.org",
        "pypi..org",
        "pypi.org:abc",
        "exa_mple.com",
        "8.8.8.8",
        "https://[::1]foo",
        "http://[v6.invalid]",
        "example.com:１２３",
    ],
)
def test_domain_matches_returns_false_for_invalid_host(host: str) -> None:
    try:
        matched = domain_matches("pypi.org", host)
    except ValueError as exc:
        pytest.fail(f"domain_matches raised {exc!r}")
    assert not matched


def test_domain_matches_returns_false_for_huge_port_without_raising() -> None:
    host = "example.com:" + ("9" * 5000)
    try:
        matched = domain_matches("example.com", host)
    except ValueError as exc:
        pytest.fail(f"domain_matches raised {exc!r}")
    assert not matched
