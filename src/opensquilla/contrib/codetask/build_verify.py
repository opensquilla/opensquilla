"""Build-mode verification for code-task (app / from-scratch generation).

Red->green->regression fits "fix a bug in an existing repo". Generating/editing
an app has no such test loop, so build mode instead runs a FIXED, runner-owned
checklist that proves the app actually builds: install from the committed
lockfile, build, and PACKAGE for the host platform.

The package step is host-aware and builds the installer for whatever OS it runs
on (each platform's installer can only be built on that platform):
- macOS    -> `electron-builder --mac`   -> a .dmg (signing auto-discovery is
  disabled so an unsigned .dmg is built deterministically, no keychain prompt).
- Windows  -> `electron-builder --win`   -> an .exe (NSIS) installer.
- Linux    -> `electron-builder --linux` -> an .AppImage / .deb installer.

To collect all three, run code-task on each OS (or a CI matrix); a single host
only produces its own platform's installer.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from opensquilla.contrib.codetask.types import BuildCheck, BuildResult, TaskState

_TAIL_LINES = 25


def _resolve_cli(name: str) -> str:
    """Resolve a node CLI shim (npm/npx) to its actual executable path.

    On Windows, ``npm``/``npx`` are ``.cmd`` shims that ``subprocess.run`` with
    ``shell=False`` cannot find by the bare name. ``shutil.which`` returns the
    fully-qualified ``npm.cmd``/``npx.cmd`` path, which Python can launch
    directly. Falls back to the bare name on POSIX (or when not found, so the
    later ``FileNotFoundError`` surfaces with a clear message).
    """
    return shutil.which(name) or name

# Build unsigned, deterministically: never auto-discover a keychain identity
# (which can prompt/hang or sign host-dependently in an automated run).
_PACKAGE_ENV = {"CSC_IDENTITY_AUTO_DISCOVERY": "false"}


def _package_step() -> tuple[str, list[str]]:
    """Host-platform electron packaging command (name, argv).

    Builds ONE tooling-free installer target for the OS we are running on, so
    packaging succeeds on a clean machine without extra build tools and without
    depending on the app's own target list:
      macOS   -> dmg       (needs only macOS' built-in hdiutil)
      Windows -> nsis      (.exe; electron-builder's built-in installer)
      Linux   -> AppImage  (self-contained; no dpkg/snapcraft/rpm tooling needed)
    Pinning the target (vs a bare ``--mac``/``--win``/``--linux``) also avoids
    triggering extra targets a generated app may have configured (deb/snap/rpm),
    which would need host tooling and fail on a clean machine. Each target can
    only be built on its own platform, so to get all three, run on each OS.
    """
    npx = _resolve_cli("npx")
    if sys.platform == "darwin":
        return "package", [npx, "electron-builder", "--mac", "dmg", "--publish", "never"]
    if sys.platform == "win32":
        return "package", [npx, "electron-builder", "--win", "nsis", "--publish", "never"]
    # Linux (and other unix): AppImage is self-contained, no extra tooling.
    return "package", [npx, "electron-builder", "--linux", "AppImage", "--publish", "never"]


def _checklist() -> list[tuple[str, list[str]]]:
    # `npm ci` (NOT install) installs strictly from the committed lockfile and
    # never mutates it, so build verification leaves the collected change clean.
    npm = _resolve_cli("npm")
    return [
        ("npm_ci", [npm, "ci"]),
        ("build", [npm, "run", "build"]),
        _package_step(),
    ]


def _installer_suffixes() -> tuple[str, ...]:
    """Installer file extension(s) electron-builder emits for the HOST platform."""
    if sys.platform == "darwin":
        return (".dmg",)
    if sys.platform == "win32":
        return (".exe", ".msi")
    return (".AppImage", ".deb", ".rpm", ".snap")


def _find_installers(repo: Path) -> list[str]:
    """Produced installer artifacts for the HOST platform — the deliverables.

    build mode packages for whatever OS it runs on (macOS -> .dmg,
    Windows -> .exe, Linux -> .AppImage/.deb). electron-builder's output dir is
    configurable (``directories.output``, default ``dist``, but a generated app
    may set ``release/``), so search the whole repo tree for the host's
    installer extension(s) rather than a fixed dir — else a real, successful
    build whose installer landed elsewhere is misreported as "no installer".
    ``node_modules``/``.git`` and the unpacked app dirs (``win-unpacked`` etc.,
    which also contain a raw ``.exe``) are pruned. Multi-arch builds can emit
    more than one installer, so return all.
    """
    suffixes = _installer_suffixes()
    skip = {"node_modules", ".git"}
    found: list[str] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [
            d for d in dirs if d not in skip and not d.endswith("-unpacked")
        ]
        found.extend(os.path.join(root, f) for f in files if f.endswith(suffixes))
    return sorted(found)


@dataclass
class BuildVerificationOutcome:
    state: TaskState
    build: BuildResult
    detail: str = ""


def _tail(text: str, n: int = _TAIL_LINES) -> str:
    return "\n".join((text or "").splitlines()[-n:])


_NODE_BUILTINS = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "http", "http2", "https", "inspector", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline",
    "repl", "stream", "string_decoder", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
})

_REQUIRE_RE = re.compile(
    r"""(?:require\(\s*|from\s+|import\(\s*)['"]([^'"]+)['"]"""
)


def _check_runtime_deps(repo: Path) -> BuildCheck:
    """Static check: every bare module the built MAIN process require()s must be
    in package.json ``dependencies``.

    electron-vite externalizes main/preload dependencies (required at runtime, not
    bundled) and electron-builder prunes ``devDependencies`` when packaging, so a
    runtime module left in ``devDependencies`` builds and packages cleanly yet
    makes the installed app crash on launch with ``Cannot find module``. This
    catches that whole class without launching the GUI.
    """
    chk = BuildCheck(
        name="runtime_deps",
        command="(static) main-process require()s must be in dependencies",
    )
    chk.ran = True
    main_dir = repo / "out" / "main"
    pkg = repo / "package.json"
    if not main_dir.is_dir() or not pkg.is_file():
        chk.ok = True
        chk.raw_tail = "skipped (no out/main or package.json)"
        return chk
    try:
        deps = set(json.loads(pkg.read_text(encoding="utf-8")).get("dependencies", {}))
    except (OSError, ValueError) as exc:
        chk.ok = False
        chk.raw_tail = f"cannot parse package.json: {exc}"
        return chk
    allowed = _NODE_BUILTINS | {"electron"}
    missing: set[str] = set()
    for js in main_dir.rglob("*.js"):
        try:
            text = js.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for spec in _REQUIRE_RE.findall(text):
            if spec.startswith((".", "/")):
                continue
            if spec.startswith("node:"):
                spec = spec[len("node:"):]
            base = (
                "/".join(spec.split("/")[:2])
                if spec.startswith("@")
                else spec.split("/")[0]
            )
            if base in allowed or base in deps:
                continue
            missing.add(base)
    if missing:
        chk.ok = False
        chk.raw_tail = (
            "main process require()s these at runtime but they are NOT in "
            'package.json "dependencies": ' + ", ".join(sorted(missing)) + ". "
            "electron-builder prunes devDependencies when packaging, so the "
            "installed app throws `Cannot find module`. Move them to dependencies."
        )
    else:
        chk.ok = True
        chk.raw_tail = "all main-process runtime require()s are in dependencies"
    return chk


def verify_build(
    repo: Path,
    *,
    check_timeout: int = 1800,
) -> BuildVerificationOutcome:
    """Run the fixed build checklist from the repo root and decide the state."""
    missing = [
        name
        for name in ("package.json", "package-lock.json")
        if not (repo / name).is_file()
    ]
    if missing:
        return BuildVerificationOutcome(
            state=TaskState.ENVIRONMENT_BLOCKED,
            build=BuildResult(checks=[], all_passed=False),
            detail=(
                f"missing {', '.join(missing)} — the app must be scaffolded and "
                "`npm install` run so a lockfile exists in the change"
            ),
        )

    env = {**os.environ, **_PACKAGE_ENV}
    checklist = _checklist()
    checks: list[BuildCheck] = []
    for name, argv in checklist:
        chk = BuildCheck(name=name, command=" ".join(argv))
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(repo),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=check_timeout,
                env=env,
            )
            chk.ran = True
            chk.exit_code = proc.returncode
            chk.ok = proc.returncode == 0
            chk.raw_tail = _tail((proc.stdout or "") + (proc.stderr or ""))
        except subprocess.TimeoutExpired:
            chk.ran = True
            chk.ok = False
            chk.raw_tail = f"TIMEOUT after {check_timeout}s"
        except FileNotFoundError as exc:
            chk.ran = False
            chk.ok = False
            chk.raw_tail = f"command not found: {exc}"
        chk.duration_seconds = round(time.monotonic() - start, 1)
        checks.append(chk)
        if not chk.ok:
            break  # later checks are meaningless once one fails

    subprocess_passed = len(checks) == len(checklist) and all(c.ok for c in checks)
    # A clean build + package does NOT prove the app runs: electron-builder
    # prunes devDependencies, so a runtime module left there packages fine but
    # makes the INSTALLED app crash on launch with `Cannot find module`.
    # Statically verify every module the built main require()s is in dependencies.
    if subprocess_passed:
        dep_chk = _check_runtime_deps(repo)
        checks.append(dep_chk)
        all_passed = dep_chk.ok
    else:
        all_passed = False
    build = BuildResult(checks=checks, all_passed=all_passed)

    if all_passed:
        # The package step must yield the host platform's installer deliverable
        # (.dmg on macOS, .exe on Windows, .AppImage/.deb on Linux). A clean exit
        # with no installer (e.g. config emitted only an unpacked dir) is NOT a
        # real success.
        installers = _find_installers(repo)
        if not installers:
            build.all_passed = False
            return BuildVerificationOutcome(
                state=TaskState.FAILED,
                build=build,
                detail="packaging exited cleanly but produced no installer",
            )
        build.installer_paths = installers
        build.installer_path = installers[0]
        return BuildVerificationOutcome(state=TaskState.VERIFIED, build=build)

    failed = next((c for c in checks if not c.ok), None)
    # Deps failing to install = the environment is the blocker; build/package
    # failing = the generated app does not build.
    state = (
        TaskState.ENVIRONMENT_BLOCKED
        if failed is not None and failed.name == "npm_ci"
        else TaskState.FAILED
    )
    detail = (
        f"build check failed: {failed.name}\n{failed.raw_tail}".rstrip()
        if failed is not None
        else "build verification did not complete"
    )
    return BuildVerificationOutcome(state=state, build=build, detail=detail)
