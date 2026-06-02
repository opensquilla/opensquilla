"""Package-manager domain bundles for sandbox managed network."""

from __future__ import annotations

PACKAGE_BUNDLES: dict[str, tuple[str, ...]] = {
    "python-package-install": (
        "pypi.org",
        "files.pythonhosted.org",
        "pypi.python.org",
        "bootstrap.pypa.io",
    ),
    "node-package-install": (
        "registry.npmjs.org",
        "registry.yarnpkg.com",
        "yarnpkg.com",
        "nodejs.org",
    ),
    "rust-package-install": (
        "crates.io",
        "static.crates.io",
        "index.crates.io",
        "github.com",
        "objects.githubusercontent.com",
    ),
    "go-package-install": (
        "proxy.golang.org",
        "sum.golang.org",
        "go.dev",
        "golang.org",
        "storage.googleapis.com",
    ),
}


def expand_package_bundle(bundle_id: str) -> tuple[str, ...]:
    return PACKAGE_BUNDLES.get(str(bundle_id or ""), ())


__all__ = ["PACKAGE_BUNDLES", "expand_package_bundle"]
