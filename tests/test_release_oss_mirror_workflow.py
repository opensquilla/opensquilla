from __future__ import annotations

from pathlib import Path


def test_aliyun_oss_release_mirror_workflow_contract() -> None:
    workflow = Path(".github/workflows/mirror-release-to-oss.yml").read_text(
        encoding="utf-8"
    )

    assert "name: Mirror Release Assets to Aliyun OSS" in workflow
    assert "release:\n    types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "gh release download" in workflow
    assert "sha256sum -c SHA256SUMS" in workflow
    assert "ossutil-2.3.0-linux-amd64.zip" in workflow
    assert "OSSUTIL_SHA256" in workflow
    assert "ALIYUN_OSS_ACCESS_KEY_ID" in workflow
    assert "ALIYUN_OSS_ACCESS_KEY_SECRET" in workflow
    assert "ALIYUN_OSS_BUCKET" in workflow
    assert "OSS_REGION" in workflow
    assert "OSS_ENDPOINT" in workflow
    assert "ALIYUN_OSS_PREFIX_NORMALIZED" in workflow
    assert "dest_prefix=\"oss://${ALIYUN_OSS_BUCKET}/${ALIYUN_OSS_PREFIX_NORMALIZED}/${TAG}\"" in workflow
    assert "ossutil cp \"${path}\" \"${dest_prefix}/${name}\"" in workflow
