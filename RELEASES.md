# OpenSquilla Releases

| Version | Tag | Date | Notes |
|---|---|---|---|
| 0.4.0 | v0.4.0 | 2026-06-27 | Control UI refresh, manual MetaSkills, coding mode, search expansion, and runtime hardening |
| 0.3.0 | v0.3.0 | 2026-05-31 | MetaSkills, Health Doctor, tool compression, and docs release |
| 0.2.1 | v0.2.1 | 2026-05-21 | 0.2 maintenance release |
| 0.2.0 | v0.2.0 | 2026-05-20 | 0.2 release |
| 0.2.0rc1 | v0.2.0rc1 | 2026-05-19 | Second public preview |
| 0.1.0rc1 | v0.1.0rc1 | 2026-05-12 | First public preview |

Preview releases publish only versioned assets:

- `OpenSquilla-<version>-windows-x64-py312-recommended-portable.zip`
- `opensquilla-<version>-py3-none-any.whl`
- `SHA256SUMS`

0.4.0 non-preview releases publish signed desktop installers plus the Python
wheel. The Windows portable zip is still published as a legacy compatibility
asset for existing scripts and portable-folder workflows. Non-preview releases
also publish a version-independent alias for the legacy Windows portable zip
`/releases/latest/download/` URL:

- `OpenSquilla-<version>-mac-arm64.dmg`
- `OpenSquilla-<version>-mac-arm64.zip`
- `OpenSquilla-<version>-win-x64.exe`
- `opensquilla-<version>-py3-none-any.whl`
- `OpenSquilla-<version>-windows-x64-py312-recommended-portable.zip`
- `OpenSquilla-windows-x64-portable.zip`
- `SHA256SUMS`

GitHub source archives remain available for code review and developer
reference; source installs should use `git clone` plus Git LFS. Public
wheelhouse zips, macOS portable zips, and Linux portable zips are intentionally
not published. Linux users install the same wheel through the versioned
`uv tool install` command documented in the README.
Python wheel filenames must remain versioned because installers validate the
version segment inside the wheel filename.

Preview releases are GitHub pre-releases. Their README install commands must
use tag-pinned URLs such as:

- `https://github.com/opensquilla/opensquilla/releases/download/v0.2.0rc1/OpenSquilla-0.2.0rc1-windows-x64-py312-recommended-portable.zip`
- `https://github.com/opensquilla/opensquilla/releases/download/v0.2.0rc1/opensquilla-0.2.0rc1-py3-none-any.whl`

0.4.0 install commands use versioned wheel URLs because Python installers
validate wheel filenames. The legacy Windows portable zip may use the
`/releases/latest/download/` alias after the non-pre-release GitHub Release
exists. Fully pinned URLs remain available for every primary asset:

- `https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-mac-arm64.dmg`
- `https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-win-x64.exe`
- `https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-windows-x64-py312-recommended-portable.zip`
- `https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/opensquilla-0.4.0-py3-none-any.whl`

## Release SOP

1. Verify `git status` is clean.
2. Update `CHANGELOG.md`: move entries from `[Unreleased]` to the release section; reopen empty `[Unreleased]`.
3. Bump `pyproject.toml` and `uv.lock` to the release version.
4. `git tag -a v0.4.0 -m "OpenSquilla 0.4.0"`
5. `git push origin v0.4.0` (this triggers `.github/workflows/wheelhouse-release.yml`)
6. Wait for the Release Assets workflow → review the draft GitHub Release.
   For non-preview releases, confirm it contains desktop installers, the
   versioned wheel, the legacy Windows portable assets, `SHA256SUMS`, plus
   GitHub's generated source archives before publishing.
7. Confirm the draft GitHub Release is not marked as a pre-release.
8. Publish the GitHub Release, then run the post-publish tag URL checks:

   ```sh
   curl --fail --head --location https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-mac-arm64.dmg
   curl --fail --head --location https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-win-x64.exe
   curl --fail --head --location https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/OpenSquilla-0.4.0-windows-x64-py312-recommended-portable.zip
   curl --fail --head --location https://github.com/opensquilla/opensquilla/releases/download/v0.4.0/opensquilla-0.4.0-py3-none-any.whl
   ```

9. Run the post-publish latest URL check:

   ```sh
   curl --fail --head --location https://github.com/opensquilla/opensquilla/releases/latest/download/OpenSquilla-windows-x64-portable.zip
   ```

10. For subsequent previews: bump `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, and the tag to the next preview version, for example `0.3.2rc1` / `v0.3.2rc1`. Preview GitHub Releases must be marked as pre-releases and should use tag-pinned README URLs until the next non-preview release exists.

## GitHub-only release checks

These checks cannot be fully proven by local artifact generation:

- The tag exists on GitHub and matches `pyproject.toml`.
- The release workflow can fetch hydrated Git LFS router assets.
- Preview GitHub Releases contain the versioned assets and `SHA256SUMS` after
  `gh release upload --clobber`.
- Non-preview GitHub Releases contain the desktop installers, versioned wheel,
  legacy Windows portable assets, update metadata, and `SHA256SUMS` after
  `gh release upload --clobber`.
- After a non-preview GitHub Release is published, the latest legacy Windows portable URL resolves:
  `.../releases/latest/download/OpenSquilla-windows-x64-portable.zip`.
- After a preview GitHub Release is published, the tag-pinned release asset URLs
  resolve.
- Windows browser downloads may carry Mark-of-the-Web; SmartScreen,
  Smart App Control, enterprise policy, and unsigned binary reputation must be
  checked on a real Windows machine.

## Why preview package versions use rc

Release zips are distributed as built artifacts, so the package filename,
manifest, zip name, and tag should describe the same preview build. PEP 440
accepts `0.2.0rc1`, while the public GitHub Release title can use the friendlier
name "OpenSquilla 0.2.0 Preview 1".
