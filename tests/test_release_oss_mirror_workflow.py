from __future__ import annotations

from pathlib import Path


def test_aliyun_oss_release_mirror_workflow_contract() -> None:
    workflow = Path(".github/workflows/mirror-release-to-oss.yml").read_text(
        encoding="utf-8"
    )

    assert "name: Mirror Release Assets to Aliyun OSS" in workflow
    assert "release:\n    types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "group: oss-release-mirror-latest-aliases" in workflow
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
    assert "OSS_ADDRESSING_STYLE_NORMALIZED" in workflow
    assert "--addressing-style" in workflow
    assert (
        'dest_prefix="oss://${ALIYUN_OSS_BUCKET}/'
        '${ALIYUN_OSS_PREFIX_NORMALIZED}/${TAG}"'
    ) in workflow
    assert "local -a options=(" in workflow
    assert '--cache-control "${cache_control}"' in workflow
    assert 'upload_asset "release-assets/SHA256SUMS" "SHA256SUMS"' in workflow
    assert "Build stable installer aliases" in workflow
    assert 'make_alias "OpenSquilla-*-mac-arm64.dmg" "OpenSquilla-mac-arm64.dmg"' in workflow
    assert 'make_alias "OpenSquilla-*-win-x64.exe" "OpenSquilla-win-x64.exe"' in workflow
    assert 'latest_prefix="${mirror_root}/latest"' in workflow
    assert 'backup_prefix="${mirror_root}/.latest-backups/${GITHUB_RUN_ID}"' in workflow
    assert "rollback_latest_aliases" in workflow
    assert "local listing" in workflow
    assert "return 2" in workflow
    assert "if (( exists_status != 1 )); then" in workflow
    assert "if (( latest_html_status != 1 )); then" in workflow
    assert (
        'upload_asset "release-assets/${name}" "${name}" "${latest_prefix}" "no-cache"'
        in workflow
    )
    assert '"${mirror_root}/latest.html"' in workflow
    assert workflow.index(
        'upload_asset "release-assets/${name}" "${name}" "${latest_prefix}" "no-cache"'
    ) < workflow.index('"${mirror_root}/latest.html"')
