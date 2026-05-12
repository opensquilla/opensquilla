# OpenSquilla Releases

| Version | Tag | Date | Notes |
|---|---|---|---|
| 0.1.0rc1 | v0.1.0rc1 | 2026-05-12 | First public preview |

`0.1.0rc1` publishes the Windows portable zip only. GitHub source archives
remain available for code review and developer reference; source installs should
use `git clone` plus Git LFS. Public wheelhouse zips, macOS portable zips, and
Linux portable zips are intentionally not published for this preview.

## Preview tag SOP

1. Verify `git status` is clean.
2. Update `CHANGELOG.md`: move entries from `[Unreleased]` to `[0.1.0rc1] - <date>` section; reopen empty `[Unreleased]`.
3. `git tag -a v0.1.0rc1 -m "OpenSquilla 0.1.0 Preview 1"`
4. `git push origin v0.1.0rc1` (this triggers `.github/workflows/wheelhouse-release.yml`)
5. Wait for the portable release workflow → review the draft GitHub Release.
   Confirm it contains exactly the Windows portable zip, its `.sha256` file,
   `SHA256SUMS`, and GitHub's source archives before
   publishing.
6. For subsequent previews: bump `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, and the tag to `0.1.0rc2`, `v0.1.0rc2`, etc.

## Why the package version uses rc

Release zips are distributed as built artifacts, so the package filename,
manifest, zip name, and tag should describe the same preview build. PEP 440
accepts `0.1.0rc1`, while the public GitHub Release title can use the friendlier
name "OpenSquilla 0.1.0 Preview 1".
