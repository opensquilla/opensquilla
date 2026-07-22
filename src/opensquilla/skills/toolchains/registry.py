"""Pinned, built-in managed toolchain catalog.

The catalog is deliberately code-owned: callers select a component identifier,
never a URL, checksum, archive type, or extraction path.  This keeps skill
metadata from becoming an arbitrary download-and-execute surface.
"""

from __future__ import annotations

import platform as platform_module
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class UnknownComponentError(ValueError):
    """Raised when a caller requests a component outside the built-in catalog."""


@dataclass(frozen=True)
class AuxiliaryAssetDescriptor:
    """One pinned non-executable resource installed with a component."""

    asset_id: str
    url: str
    sha256: str
    size: int
    destination: str
    license: str
    source: str


@dataclass(frozen=True)
class ToolchainDescriptor:
    """One catalog component resolved for a concrete host platform."""

    component_id: str
    display_name: str
    version: str
    platform_key: str
    supported: bool
    unsupported_reason: str | None
    url: str | None
    sha256: str | None
    size: int | None
    install_backend: str
    brew_formula: str | None
    archive_type: str | None
    archive_root: str | None
    bin_relpaths: tuple[str, ...]
    probe_commands: tuple[tuple[str, ...], ...]
    post_install: str | None
    package_closure: tuple[str, ...]
    auxiliary_assets: tuple[AuxiliaryAssetDescriptor, ...]
    license: str
    license_url: str
    source: str
    closure_source: str | None
    notes: str

    @property
    def total_download_size(self) -> int | None:
        """Return pinned bytes when the primary backend also has a known size."""
        if self.size is None:
            return None
        return self.size + sum(asset.size for asset in self.auxiliary_assets)


@dataclass(frozen=True)
class _Artifact:
    url: str | None
    sha256: str | None
    size: int | None
    archive_type: str | None
    archive_root: str | None
    bin_relpaths: tuple[str, ...]
    version: str | None = None
    install_backend: str = "archive"
    brew_formula: str | None = None
    source: str | None = None
    supported: bool = True
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class _Component:
    component_id: str
    display_name: str
    version: str
    probe_commands: tuple[tuple[str, ...], ...]
    post_install: str | None
    package_closure: tuple[str, ...]
    auxiliary_assets: tuple[AuxiliaryAssetDescriptor, ...]
    license: str
    license_url: str
    source: str
    closure_source: str | None
    notes: str
    artifacts: dict[str, _Artifact]


_RELEASE_BASE = "https://github.com/rstudio/tinytex-releases/releases/download/v2026.05"
_BTBN_RELEASE_BASE = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-06-30-13-34"
)
_GYAN_RELEASE_BASE = "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2"

_NOTO_CJK_ASSETS = (
    AuxiliaryAssetDescriptor(
        asset_id="noto-cjk-font",
        url=(
            "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/"
            "Sans/OTC/NotoSansCJK-Regular.ttc"
        ),
        sha256="b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a",
        size=19_484_784,
        destination="fonts/NotoSansCJK-Regular.ttc",
        license="OFL-1.1",
        source="https://github.com/notofonts/noto-cjk/tree/Sans2.004",
    ),
    AuxiliaryAssetDescriptor(
        asset_id="noto-cjk-license",
        url="https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/LICENSE",
        sha256="6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2",
        size=4_301,
        destination="licenses/Noto-OFL.txt",
        license="OFL-1.1",
        source="https://github.com/notofonts/noto-cjk/tree/Sans2.004",
    ),
)


def _release_url(filename: str) -> str:
    return f"{_RELEASE_BASE}/{filename}"


_COMPONENTS: dict[str, _Component] = {
    "paper-tex": _Component(
        component_id="paper-tex",
        display_name="TinyTeX for paper writing",
        version="2026.05",
        probe_commands=(("xelatex", "--version"), ("bibtex", "--version")),
        post_install="paper-capability",
        package_closure=(),
        auxiliary_assets=_NOTO_CJK_ASSETS,
        license="GPL-2.0; Noto CJK: OFL-1.1",
        license_url="https://github.com/rstudio/tinytex-releases/blob/main/LICENSE",
        source="https://github.com/rstudio/tinytex-releases",
        closure_source=None,
        notes=(
            "Pinned monthly TinyTeX full archive plus a pinned Noto CJK font. "
            "The capability closure is self-contained and requires no floating TeX "
            "Live package-manager update. Windows uses the upstream ordinary ZIP, "
            "never its self-extracting installer. Installed size is larger than the "
            "downloads."
        ),
        artifacts={
            # The macOS archive is universal and is intentionally shared by Intel
            # and Apple Silicon hosts.
            "darwin-universal": _Artifact(
                url=_release_url("TinyTeX-darwin-v2026.05.tar.xz"),
                sha256="53f55f2ec100cc4e0ba5840f8a66086c6e37aa36b9aa4c64f924165352443e92",
                size=206_982_916,
                archive_type="tar.xz",
                archive_root="TinyTeX",
                bin_relpaths=("TinyTeX/bin/universal-darwin",),
            ),
            "linux-arm64": _Artifact(
                url=_release_url("TinyTeX-linux-arm64-v2026.05.tar.xz"),
                sha256="2e728c28f3d5a767516a166d07efbd9e5950888deca868c539adbdf7887a711d",
                size=152_627_036,
                archive_type="tar.xz",
                archive_root="TinyTeX",
                bin_relpaths=("TinyTeX/bin/aarch64-linux",),
            ),
            "linux-x64": _Artifact(
                url=_release_url("TinyTeX-linux-x86_64-v2026.05.tar.xz"),
                sha256="2063e7614a3604cedb98713f57b5e8684eac50f73fe23437d48fe48fa9d6a65c",
                size=150_260_820,
                archive_type="tar.xz",
                archive_root="TinyTeX",
                bin_relpaths=("TinyTeX/bin/x86_64-linux",),
            ),
            "linux-musl-x64": _Artifact(
                url=_release_url("TinyTeX-linuxmusl-x86_64-v2026.05.tar.xz"),
                sha256="6fdb0c6203cd85af7cc951b7e6d0afbe2dd267173a085dc10fcb3d87b08828f4",
                size=145_776_644,
                archive_type="tar.xz",
                archive_root="TinyTeX",
                bin_relpaths=("TinyTeX/bin/x86_64-linuxmusl",),
            ),
            # Use the upstream ordinary ZIP rather than either Windows SFX asset.
            # It contains the same complete TinyTeX tree and can pass through the
            # manager's path-, type-, member-count-, and expansion-bounded extractor.
            "windows-x64": _Artifact(
                url=_release_url("TinyTeX-v2026.05.zip"),
                sha256="64eab7759cc2a17231cb84bd4a08c0da2efd074ebcabf663d8919d6411070f4d",
                size=245_928_318,
                archive_type="zip",
                archive_root="TinyTeX",
                bin_relpaths=("TinyTeX/bin/windows",),
            ),
        },
    ),
    "media-ffmpeg": _Component(
        component_id="media-ffmpeg",
        display_name="FFmpeg media toolchain",
        version="2026.06.30",
        probe_commands=(("ffmpeg", "-version"), ("ffprobe", "-version")),
        post_install="ffmpeg-media-capability",
        package_closure=(),
        auxiliary_assets=_NOTO_CJK_ASSETS,
        license="GPL-3.0-or-later",
        license_url="https://ffmpeg.org/legal.html",
        source="https://github.com/BtbN/FFmpeg-Builds",
        closure_source=None,
        notes=(
            "Pinned GPL static archives on Linux and Windows; macOS uses the "
            "Homebrew ffmpeg-full bottle. A pinned OFL-1.1 Noto CJK font is included. "
            "Linux requires glibc 2.28 and kernel 4.18."
        ),
        artifacts={
            "darwin-universal": _Artifact(
                url=None,
                sha256=None,
                size=None,
                install_backend="brew",
                brew_formula="ffmpeg-full",
                archive_type=None,
                archive_root=None,
                bin_relpaths=("bin",),
                version="homebrew-stable",
                source="https://formulae.brew.sh/formula/ffmpeg-full",
            ),
            "linux-x64": _Artifact(
                url=(
                    f"{_BTBN_RELEASE_BASE}/"
                    "ffmpeg-n7.1.5-1-g7d0e842004-linux64-gpl-7.1.tar.xz"
                ),
                sha256="f0c580f5f12af54e8c9c649c70b2d25f264edb35393203d34b20cf4f9c126288",
                size=118_937_200,
                archive_type="tar.xz",
                archive_root="ffmpeg-n7.1.5-1-g7d0e842004-linux64-gpl-7.1",
                bin_relpaths=("ffmpeg-n7.1.5-1-g7d0e842004-linux64-gpl-7.1/bin",),
                version="7.1.5-2026.06.30",
            ),
            "linux-arm64": _Artifact(
                url=(
                    f"{_BTBN_RELEASE_BASE}/"
                    "ffmpeg-n7.1.5-1-g7d0e842004-linuxarm64-gpl-7.1.tar.xz"
                ),
                sha256="8b61e22e674c9f3530a8953a684d6789dd94de26fffd614b9234b15673b85d04",
                size=101_094_952,
                archive_type="tar.xz",
                archive_root="ffmpeg-n7.1.5-1-g7d0e842004-linuxarm64-gpl-7.1",
                bin_relpaths=("ffmpeg-n7.1.5-1-g7d0e842004-linuxarm64-gpl-7.1/bin",),
                version="7.1.5-2026.06.30",
            ),
            "windows-x64": _Artifact(
                url=f"{_GYAN_RELEASE_BASE}/ffmpeg-8.1.2-essentials_build.zip",
                sha256="db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec",
                size=109_728_040,
                archive_type="zip",
                archive_root="ffmpeg-8.1.2-essentials_build",
                bin_relpaths=("ffmpeg-8.1.2-essentials_build/bin",),
                version="8.1.2",
                source="https://github.com/GyanD/codexffmpeg",
            ),
        },
    ),
}


def normalize_platform(value: str | None = None) -> str:
    """Normalize Python/OS platform spellings to catalog names."""
    raw = (value or platform_module.system() or sys.platform).strip().lower()
    aliases = {
        "darwin": "darwin",
        "mac": "darwin",
        "macos": "darwin",
        "osx": "darwin",
        "linux": "linux",
        "linux2": "linux",
        "win": "windows",
        "win32": "windows",
        "windows": "windows",
        "cygwin": "windows",
        "msys": "windows",
    }
    return aliases.get(raw, raw)


def normalize_arch(value: str | None = None) -> str:
    """Normalize common CPU architecture spellings to catalog names."""
    raw = (value or platform_module.machine()).strip().lower().replace("-", "_")
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    return aliases.get(raw, raw)


def _uses_musl(libc_name: str | None = None) -> bool:
    if libc_name is None:
        libc_name = platform_module.libc_ver()[0]
    normalized = libc_name.strip().lower()
    if normalized:
        return "musl" in normalized

    # Some musl Python builds return an empty libc_ver().  The interpreter's
    # platform string is a bounded local signal and contains no caller input.
    return bool(re.search(r"(?:^|[-_.])musl(?:[-_.]|$)", sysconfig_platform()))


def sysconfig_platform() -> str:
    """Return the interpreter platform string without importing at module load."""
    import sysconfig

    return sysconfig.get_platform().lower()


def platform_key(
    platform_name: str | None = None,
    arch: str | None = None,
    libc_name: str | None = None,
) -> str:
    """Resolve a normalized catalog key for the current or supplied host."""
    os_name = normalize_platform(platform_name)
    cpu = normalize_arch(arch)
    if os_name == "darwin" and cpu in {"x64", "arm64"}:
        return "darwin-universal"
    if os_name == "linux" and cpu == "x64" and _uses_musl(libc_name):
        return "linux-musl-x64"
    return f"{os_name}-{cpu}"


def describe_component(
    component_id: str,
    *,
    platform_name: str | None = None,
    arch: str | None = None,
    libc_name: str | None = None,
    libc_version: str | None = None,
    kernel_release: str | None = None,
) -> ToolchainDescriptor:
    """Describe one built-in component for a host, failing closed when unknown."""
    component = _COMPONENTS.get(component_id)
    if component is None:
        raise UnknownComponentError(f"Unknown managed toolchain component: {component_id}")

    key = platform_key(platform_name, arch, libc_name)
    artifact = component.artifacts.get(key)
    if artifact is None:
        return ToolchainDescriptor(
            component_id=component.component_id,
            display_name=component.display_name,
            version=component.version,
            platform_key=key,
            supported=False,
            unsupported_reason=f"No pinned {component.display_name} artifact for {key}.",
            url=None,
            sha256=None,
            size=None,
            install_backend="archive",
            brew_formula=None,
            archive_type=None,
            archive_root=None,
            bin_relpaths=(),
            probe_commands=component.probe_commands,
            post_install=component.post_install,
            package_closure=component.package_closure,
            auxiliary_assets=component.auxiliary_assets,
            license=component.license,
            license_url=component.license_url,
            source=component.source,
            closure_source=component.closure_source,
            notes=component.notes,
        )

    supported = artifact.supported
    unsupported_reason = artifact.unsupported_reason
    if component.component_id == "media-ffmpeg" and key.startswith("linux-"):
        libc_actual_name, libc_actual_version = platform_module.libc_ver()
        selected_libc = (libc_name if libc_name is not None else libc_actual_name).lower()
        selected_libc_version = (
            libc_version if libc_version is not None else libc_actual_version
        )
        selected_kernel = kernel_release or platform_module.release()
        if selected_libc != "glibc" or not _version_at_least(selected_libc_version, (2, 28)):
            supported = False
            unsupported_reason = "This FFmpeg build requires glibc 2.28 or newer."
        elif not _version_at_least(selected_kernel, (4, 18)):
            supported = False
            unsupported_reason = "This FFmpeg build requires Linux kernel 4.18 or newer."

    return ToolchainDescriptor(
        component_id=component.component_id,
        display_name=component.display_name,
        version=artifact.version or component.version,
        platform_key=key,
        supported=supported,
        unsupported_reason=unsupported_reason,
        url=artifact.url,
        sha256=artifact.sha256,
        size=artifact.size,
        install_backend=artifact.install_backend,
        brew_formula=artifact.brew_formula,
        archive_type=artifact.archive_type,
        archive_root=artifact.archive_root,
        bin_relpaths=artifact.bin_relpaths,
        probe_commands=component.probe_commands,
        post_install=component.post_install,
        package_closure=component.package_closure,
        auxiliary_assets=component.auxiliary_assets,
        license=component.license,
        license_url=component.license_url,
        source=artifact.source or component.source,
        closure_source=component.closure_source,
        notes=component.notes,
    )


def _version_at_least(value: str, minimum: tuple[int, ...]) -> bool:
    numbers = tuple(int(item) for item in re.findall(r"\d+", value)[: len(minimum)])
    if len(numbers) < len(minimum):
        return False
    return numbers >= minimum


def component_ids() -> tuple[str, ...]:
    """Return the immutable public component identifiers in catalog order."""
    return tuple(_COMPONENTS)


def trusted_brew_executable() -> Path | None:
    """Return Homebrew only from its platform-default installation locations."""
    for candidate in (Path("/opt/homebrew/bin/brew"), Path("/usr/local/bin/brew")):
        if candidate.is_file():
            return candidate
    return None
