# Aliyun OSS release mirror

OpenSquilla can mirror published GitHub Release assets to Aliyun OSS for faster
Mainland China downloads.

The mirror workflow lives at `.github/workflows/mirror-release-to-oss.yml`. It
runs when a GitHub Release is published and can also be run manually with a tag.
The workflow downloads the release assets from GitHub, verifies `SHA256SUMS`,
and uploads the exact files to a versioned OSS prefix.

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
  download/upload domain; the workflow also auto-selects `cname` when the
  endpoint host does not end in `aliyuncs.com`.

Use a dedicated RAM user or role scoped to the release mirror bucket/prefix. The
workflow needs to upload objects and list the destination prefix. Do not use a
full-access account key.

## Destination layout

For tag `v0.5.0rc3` and the default prefix, the workflow writes:

```text
oss://<bucket>/releases/v0.5.0rc3/OpenSquilla-0.5.0-rc3-win-x64.exe
oss://<bucket>/releases/v0.5.0rc3/OpenSquilla-0.5.0-rc3-mac-arm64.dmg
oss://<bucket>/releases/v0.5.0rc3/opensquilla-0.5.0rc3-py3-none-any.whl
oss://<bucket>/releases/v0.5.0rc3/SHA256SUMS
```

Use versioned paths and do not overwrite a shared `latest.exe`. A versioned OSS
path is safe to cache later if a CDN is added.

The public download URL depends on the bucket endpoint or custom domain. With a
custom download domain it should look like:

```text
https://download.example.com/releases/v0.5.0rc3/OpenSquilla-0.5.0-rc3-win-x64.exe
```

## Manual backfill

To mirror an already-published release, run the workflow manually and enter the
release tag, for example `v0.5.0rc3`. Manual backfills overwrite existing OSS
objects for the same tag and filename after the GitHub assets pass checksum
verification.

## Failure model

The mirror workflow fails if required OSS configuration is missing, if the
GitHub Release has no downloadable assets, if `SHA256SUMS` is missing, if a
release asset is not listed in `SHA256SUMS`, or if the checksum verification
fails before upload. In those cases, GitHub remains the source of truth and OSS
should not be treated as a complete mirror for that tag.
