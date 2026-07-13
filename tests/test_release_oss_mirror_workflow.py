from __future__ import annotations

from pathlib import Path


def test_aliyun_oss_release_mirror_workflow_contract() -> None:
    workflow = Path(".github/workflows/mirror-release-to-oss.yml").read_text(
        encoding="utf-8"
    )

    assert "name: Mirror Release Assets to Aliyun OSS" in workflow
    assert "release:\n    types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "MANUAL_RELEASE_TAG: ${{ inputs.tag }}" in workflow
    assert 'tag="${MANUAL_RELEASE_TAG}"' in workflow
    assert 'tag="${{ inputs.tag }}"' not in workflow
    assert "gh release download" in workflow
    assert "sha256sum --strict -c SHA256SUMS" in workflow
    assert "CHECKSUMMED_ASSETS" in workflow
    assert "Release assets missing from SHA256SUMS" in workflow
    assert "ossutil-2.3.0-linux-amd64.zip" in workflow
    assert "OSSUTIL_SHA256" in workflow
    assert "ALIYUN_OSS_ACCESS_KEY_ID" in workflow
    assert "ALIYUN_OSS_ACCESS_KEY_SECRET" in workflow
    assert "ALIYUN_OSS_BUCKET" in workflow
    assert "OSS_REGION" in workflow
    assert "OSS_ENDPOINT" in workflow
    assert "OSS_ADDRESSING_STYLE" in workflow
    assert "ALIYUN_OSS_PREFIX_NORMALIZED" in workflow
    assert "ALIYUN_OSS_PUBLIC_BASE_URL" in workflow
    assert "OSS_PUBLIC_BASE_URL_NORMALIZED" in workflow
    assert "OSS_ADDRESSING_STYLE_NORMALIZED" in workflow
    assert "--addressing-style" in workflow
    assert (
        'dest_prefix="oss://${ALIYUN_OSS_BUCKET}/'
        '${ALIYUN_OSS_PREFIX_NORMALIZED}/${TAG}"'
    ) in workflow
    assert 'ossutil cp --force --addressing-style' in workflow
    assert 'upload_asset "release-assets/SHA256SUMS" "SHA256SUMS"' in workflow
    assert "Build latest download page" in workflow
    assert 'release-assets/latest.html' in workflow
    assert '--content-type "text/html; charset=utf-8"' in workflow
    assert '--cache-control "no-cache"' in workflow
    assert '"${mirror_root}/latest.html"' in workflow
