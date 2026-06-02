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


def test_package_install_bundles_cover_common_registry_and_artifact_hosts() -> None:
    expectations = {
        "python-package-install": {
            "pypi.org",
            "files.pythonhosted.org",
            "pypi.python.org",
            "bootstrap.pypa.io",
        },
        "node-package-install": {
            "registry.npmjs.org",
            "registry.yarnpkg.com",
            "yarnpkg.com",
            "nodejs.org",
        },
        "rust-package-install": {
            "crates.io",
            "static.crates.io",
            "index.crates.io",
            "github.com",
            "objects.githubusercontent.com",
        },
        "go-package-install": {
            "proxy.golang.org",
            "sum.golang.org",
            "go.dev",
            "golang.org",
            "storage.googleapis.com",
        },
    }

    for bundle_id, hosts in expectations.items():
        context = _context(bundles=(PackageBundleGrant(bundle_id),))
        for host in hosts:
            decision = decide_network_access(host, context)
            assert decision.status == "allow", (bundle_id, host, decision)
            assert decision.reason == "package_bundle"
