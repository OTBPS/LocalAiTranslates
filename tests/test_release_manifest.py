import json

import pytest

from scripts.release_manifest import create_manifest, verify_manifest, write_manifest


def test_incremental_release_manifest_is_verifiable(tmp_path):
    artifact = tmp_path / "ScreenTranslator-0.4.0-Update.exe"
    artifact.write_bytes(b"installer payload")
    output = tmp_path / "ScreenTranslator-0.4.0-Update.manifest.json"

    manifest = write_manifest(artifact, output, "0.4.0", "incremental", "0.3.0")

    assert manifest["minimum_base_version"] == "0.3.0"
    assert manifest["artifact"]["size_bytes"] == len(b"installer payload")
    assert verify_manifest(output) == json.loads(output.read_text(encoding="utf-8"))


def test_incremental_manifest_requires_base_version(tmp_path):
    artifact = tmp_path / "update.exe"
    artifact.write_bytes(b"x")
    with pytest.raises(ValueError, match="minimum base"):
        create_manifest(artifact, "0.4.0", "incremental")


def test_release_version_must_be_numeric_semver(tmp_path):
    artifact = tmp_path / "setup.exe"
    artifact.write_bytes(b"x")
    with pytest.raises(ValueError, match="numeric SemVer"):
        create_manifest(artifact, "0.4-dev", "full")


def test_verifier_rejects_modified_artifact(tmp_path):
    artifact = tmp_path / "setup.exe"
    artifact.write_bytes(b"original")
    output = tmp_path / "setup.manifest.json"
    write_manifest(artifact, output, "0.4.0", "full")
    artifact.write_bytes(b"modified")
    with pytest.raises(ValueError, match="does not match"):
        verify_manifest(output)
