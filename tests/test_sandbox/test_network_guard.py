from __future__ import annotations

from opensquilla.sandbox.network_guard import NetworkDecision, decide_network_access
from opensquilla.sandbox.run_context import DomainGrant, PackageBundleGrant, RunContext
from opensquilla.sandbox.run_mode import RunMode


def _context(
    *,
    domains: tuple[DomainGrant, ...] = (),
    bundles: tuple[PackageBundleGrant, ...] = (),
) -> RunContext:
    return RunContext(
        run_mode=RunMode.STANDARD,
        domains=domains,
        bundles=bundles,
    )


def test_decide_network_access_allows_explicit_domain_grant() -> None:
    context = _context(domains=(DomainGrant("pypi.org", source="user"),))

    decision = decide_network_access("HTTPS://PyPI.org/simple", context)

    assert decision == NetworkDecision(
        status="allow",
        normalized_host="pypi.org",
        reason="domain_grant",
        source="domain:pypi.org",
    )


def test_decide_network_access_allows_wildcard_domain_grant() -> None:
    context = _context(domains=(DomainGrant("*.pythonhosted.org"),))

    decision = decide_network_access("files.pythonhosted.org", context)

    assert decision == NetworkDecision(
        status="allow",
        normalized_host="files.pythonhosted.org",
        reason="domain_grant",
        source="domain:*.pythonhosted.org",
    )


def test_decide_network_access_asks_for_unknown_valid_domain() -> None:
    decision = decide_network_access("example.com", _context())

    assert decision == NetworkDecision(
        status="ask",
        normalized_host="example.com",
        reason="unknown_domain",
        source=None,
    )


def test_decide_network_access_blocks_unsafe_ip_literal() -> None:
    decision = decide_network_access("169.254.169.254", _context())

    assert decision == NetworkDecision(
        status="block",
        normalized_host="169.254.169.254",
        reason="ip_literal",
        source="validation",
    )


def test_decide_network_access_blocks_malformed_host_with_validation_reason() -> None:
    decision = decide_network_access("example.com:99999", _context())

    assert decision == NetworkDecision(
        status="block",
        normalized_host="example.com",
        reason="invalid_port",
        source="validation",
    )


def test_decide_network_access_allows_package_bundle_domain() -> None:
    context = _context(bundles=(PackageBundleGrant("node-package-install"),))

    decision = decide_network_access("registry.npmjs.org", context)

    assert decision == NetworkDecision(
        status="allow",
        normalized_host="registry.npmjs.org",
        reason="package_bundle",
        source="bundle:node-package-install",
    )
