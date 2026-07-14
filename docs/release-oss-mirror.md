# Aliyun OSS release mirror

OpenSquilla mirrors published GitHub Release assets to Aliyun OSS for faster
Mainland China downloads.

The workflow lives at `.github/workflows/mirror-release-to-oss.yml`. It runs
when a GitHub Release is published and can also be run manually with a tag. The
workflow downloads release assets from GitHub, verifies `SHA256SUMS`, then
uploads both immutable versioned assets and stable installer aliases.

## Repository configuration

Configure these GitHub repository secrets:

- `ALIYUN_OSS_ACCESS_KEY_ID`
- `ALIYUN_OSS_ACCESS_KEY_SECRET`

Configure these GitHub repository variables:

- `ALIYUN_OSS_BUCKET`: OSS bucket name, for example `opensquilla-downloads`.
- `ALIYUN_OSS_REGION`: OSS region ID, for example `cn-hangzhou`.
- `ALIYUN_OSS_PREFIX`: optional object prefix. Defaults to `releases`.
- `ALIYUN_OSS_ENDPOINT`: optional custom endpoint or CNAME endpoint. Use this
  when the bucket or account requires a custom OSS data API endpoint.
- `ALIYUN_OSS_ADDRESSING_STYLE`: optional ossutil addressing style. Supported
  values are `virtual`, `path`, and `cname`. Leave it unset for normal OSS
  endpoints. Set it to `cname` when `ALIYUN_OSS_ENDPOINT` is a bound custom
  upload domain; the workflow also auto-selects `cname` when the endpoint host
  does not end in `aliyuncs.com`.

Use a dedicated RAM user or role scoped to the release mirror bucket/prefix. It
needs `oss:ListObjects`, `oss:GetObject`, `oss:PutObject`, and
`oss:DeleteObject`: the workflow lists aliases, copies existing aliases to a
short-lived backup, uploads versioned assets and aliases, and removes backups
and legacy `latest.html`. Do not use a full-access account key.

## Destination layout

For tag `v0.5.0rc4` and the default prefix, the workflow writes immutable
versioned assets:

```text
oss://<bucket>/releases/v0.5.0rc4/OpenSquilla-0.5.0-rc4-win-x64.exe
oss://<bucket>/releases/v0.5.0rc4/OpenSquilla-0.5.0-rc4-mac-arm64.dmg
oss://<bucket>/releases/v0.5.0rc4/opensquilla-0.5.0rc4-py3-none-any.whl
oss://<bucket>/releases/v0.5.0rc4/SHA256SUMS
```

After those checked assets are uploaded, it also replaces these two moving
installer aliases:

```text
oss://<bucket>/releases/latest/OpenSquilla-win-x64.exe
oss://<bucket>/releases/latest/OpenSquilla-mac-arm64.dmg
```

Use versioned paths when a release must remain pinned or reproducible. Use the
`latest` aliases only for user-facing "download the newest desktop app" links.
The aliases are intentionally overwritten after each successful mirror.

With the default public endpoint, use these direct download URLs:

```text
https://<bucket>.oss-<region>.aliyuncs.com/releases/latest/OpenSquilla-win-x64.exe
https://<bucket>.oss-<region>.aliyuncs.com/releases/latest/OpenSquilla-mac-arm64.dmg
```

OSS default domains force browser downloads for these files. That is expected
for installer links and does not require a custom domain. The workflow does not
publish an HTML latest-release landing page because OSS default-domain security
policy forces HTML to download as well.

## Manual backfill

To mirror an already-published release, run the workflow manually and enter the
release tag, for example `v0.5.0rc4`. Manual backfills overwrite objects for
the same tag and filename after GitHub assets pass checksum verification, then
move the two `latest` installer aliases to that release.

## Failure model

The mirror workflow fails if required OSS configuration is missing, if the
GitHub Release has no downloadable assets, if `SHA256SUMS` is missing, if a
release asset is not listed in `SHA256SUMS`, if checksum verification fails,
or if exactly one macOS DMG and Windows EXE installer cannot be found. In those
cases, GitHub remains the source of truth and the `latest` aliases are not
updated.
