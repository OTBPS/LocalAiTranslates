"""Fetch the FLORES-200 English/Chinese slices into the training cache.

FLORES-200 (Meta NLLB, CC-BY-SA-4.0) supplies **only the general-text layer**
of the gold calibration set. It is a public benchmark, so results on it are
reported separately: pretraining contamination can inflate them, and they do
not stand for real product quality. Its sentences are independent, so they must
never be concatenated into synthetic "long documents".

The Hugging Face mirrors are gated, so this uses Meta's public release URL.
The archive is downloaded to a temporary file, hashed, and only the four text
files plus the two metadata tables are extracted, each renamed atomically.

    python -m scripts.training.fetch_flores
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

import requests

from scripts.training.training_paths import workspace_path

ARCHIVE_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
LICENSE = "CC-BY-SA-4.0"
ATTRIBUTION = "FLORES-200, Meta AI (NLLB project), CC-BY-SA-4.0"
ARCHIVE_NAME = "flores200_dataset.tar.gz"
WANTED = {
    "./flores200_dataset/dev/eng_Latn.dev": "dev/eng_Latn.dev",
    "./flores200_dataset/dev/zho_Hans.dev": "dev/zho_Hans.dev",
    "./flores200_dataset/devtest/eng_Latn.devtest": "devtest/eng_Latn.devtest",
    "./flores200_dataset/devtest/zho_Hans.devtest": "devtest/zho_Hans.devtest",
    "./flores200_dataset/metadata_dev.tsv": "metadata_dev.tsv",
    "./flores200_dataset/metadata_devtest.tsv": "metadata_devtest.tsv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=workspace_path("cache/flores200"))
    parser.add_argument("--url", default=ARCHIVE_URL)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    targets = {member: args.output_dir / relative for member, relative in WANTED.items()}
    archive = args.output_dir / ARCHIVE_NAME
    # Keep the archive so a re-run never re-downloads it.
    if not archive.is_file():
        session = requests.Session()
        session.trust_env = False
        with session.get(args.url, stream=True, timeout=600) as response:
            response.raise_for_status()
            temporary = archive.with_suffix(archive.suffix + ".part")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    stream.write(chunk)
            os.replace(temporary, archive)
    archive_digest = sha256_file(archive)

    if not all(path.is_file() for path in targets.values()):
        with tarfile.open(archive, "r:gz") as bundle:
            for member, destination in targets.items():
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"archive does not contain {member}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".part")
                temporary.write_bytes(extracted.read())
                os.replace(temporary, destination)

    counts = {}
    for relative in WANTED.values():
        path = args.output_dir / relative
        counts[relative] = sum(1 for line in path.read_text(encoding="utf-8").splitlines())
    if counts["dev/eng_Latn.dev"] != counts["dev/zho_Hans.dev"]:
        raise RuntimeError("FLORES dev files are not line-aligned")
    if counts["devtest/eng_Latn.devtest"] != counts["devtest/zho_Hans.devtest"]:
        raise RuntimeError("FLORES devtest files are not line-aligned")

    manifest = {
        "schema_version": 1,
        "dataset": "FLORES-200",
        "source_url": args.url,
        "archive_sha256": archive_digest,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "files": {
            relative: {
                "sha256": sha256_file(args.output_dir / relative),
                "lines": counts[relative],
            }
            for relative in WANTED.values()
        },
        "usage_restriction": (
            "general-text layer of gold calibration only; public benchmark, report separately "
            "because pretraining contamination can inflate results; sentences are independent "
            "and must not be concatenated into synthetic long documents"
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
