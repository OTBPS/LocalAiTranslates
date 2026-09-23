"""Create and verify machine-readable release metadata for Windows packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def validate_version(version: str) -> str:
    if not SEMVER.fullmatch(version):
        raise ValueError(f"release version must be numeric SemVer (x.y.z): {version!r}")
    return version


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


PACKAGE_TYPES = ("full", "incremental")
# Which payload the package carries. The client edition ships no model
# runtime and translates through another device; it is orthogonal to whether
# the package installs everything or patches an existing installation.
EDITIONS = ("full", "client")


def create_manifest(
    artifact: Path,
    version: str,
    package_type: str,
    minimum_base_version: str | None = None,
    edition: str = "full",
) -> dict:
    artifact = artifact.resolve(strict=True)
    validate_version(version)
    if package_type not in PACKAGE_TYPES:
        raise ValueError(f"unsupported package type: {package_type}")
    if edition not in EDITIONS:
        raise ValueError(f"unsupported edition: {edition}")
    if minimum_base_version is not None:
        validate_version(minimum_base_version)
    if package_type == "incremental" and minimum_base_version is None:
        raise ValueError("incremental packages require a minimum base version")
    if package_type == "incremental" and edition != "full":
        raise ValueError("incremental packages are only published for the full edition")

    return {
        "schema_version": 2,
        "product": "Screen Translator",
        "version": version,
        "channel": "stable",
        "package_type": package_type,
        "edition": edition,
        "architecture": "x86_64",
        "minimum_windows_build": 22000,
        "minimum_base_version": minimum_base_version,
        "artifact": {
            "filename": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def write_manifest(
    artifact: Path,
    output: Path,
    version: str,
    package_type: str,
    minimum_base_version: str | None = None,
    edition: str = "full",
) -> dict:
    manifest = create_manifest(artifact, version, package_type, minimum_base_version, edition)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return manifest


def verify_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest_path.parent / manifest["artifact"]["filename"]
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if artifact.stat().st_size != manifest["artifact"]["size_bytes"]:
        raise ValueError("artifact size does not match manifest")
    if sha256_file(artifact) != manifest["artifact"]["sha256"]:
        raise ValueError("artifact SHA-256 does not match manifest")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("version")
    parser.add_argument("package_type", choices=PACKAGE_TYPES)
    parser.add_argument("--minimum-base-version")
    parser.add_argument("--edition", choices=EDITIONS, default="full")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    manifest = write_manifest(
        args.artifact,
        args.output,
        args.version,
        args.package_type,
        args.minimum_base_version,
        args.edition,
    )
    if args.verify:
        verify_manifest(args.output)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
