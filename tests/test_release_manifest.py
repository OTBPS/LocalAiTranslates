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


def test_a_full_package_defaults_to_the_full_edition(tmp_path):
    artifact = tmp_path / "ScreenTranslator-0.7.0-Setup.exe"
    artifact.write_bytes(b"payload")

    manifest = create_manifest(artifact, "0.7.0", "full")

    assert manifest["edition"] == "full"
    assert manifest["schema_version"] == 2


def test_a_client_package_records_its_edition(tmp_path):
    artifact = tmp_path / "ScreenTranslator-Client-0.7.0-Setup.exe"
    artifact.write_bytes(b"payload")
    output = tmp_path / "ScreenTranslator-Client-0.7.0-Setup.manifest.json"

    manifest = write_manifest(artifact, output, "0.7.0", "full", edition="client")

    assert manifest["edition"] == "client"
    assert verify_manifest(output) == manifest


def test_an_unknown_edition_is_rejected(tmp_path):
    artifact = tmp_path / "setup.exe"
    artifact.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsupported edition"):
        create_manifest(artifact, "0.7.0", "full", edition="lite")


def test_incremental_packages_are_full_edition_only(tmp_path):
    artifact = tmp_path / "update.exe"
    artifact.write_bytes(b"x")
    with pytest.raises(ValueError, match="only published for the full edition"):
        create_manifest(artifact, "0.7.0", "incremental", "0.6.0", edition="client")


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
