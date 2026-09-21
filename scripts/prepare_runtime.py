"""Download verified official llama.cpp Windows CUDA release into runtime/llama."""

import hashlib
import json
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    response = requests.get("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest", timeout=30)
    response.raise_for_status()
    release = response.json()
    pointer = next((a for a in release["assets"] if a["name"] == "nightly-tag.txt"), None)
    if pointer:
        tag_response = requests.get(pointer["browser_download_url"], timeout=30)
        tag_response.raise_for_status()
        tag = tag_response.text.strip()
        if not tag or "/" in tag:
            raise RuntimeError("Invalid official nightly tag")
        response = requests.get(
            f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}", timeout=30
        )
        response.raise_for_status()
        release = response.json()
    assets = release["assets"]
    cuda = [
        a
        for a in assets
        if a["name"].endswith(".zip")
        and "win-cuda" in a["name"]
        and "x64" in a["name"]
        and not a["name"].startswith("cudart")
    ]
    if not cuda:
        raise RuntimeError("Official release has no Windows CUDA x64 build")
    selected = sorted(cuda, key=lambda a: ("12.4" not in a["name"], a["name"]))[0]
    downloads = [selected]
    # Older releases split CUDA runtime DLLs into a companion archive.
    version = selected["name"].split("win-cuda-")[-1].split("-x64")[0]
    downloads += [
        a
        for a in assets
        if a["name"].startswith("cudart-llama") and version in a["name"] and "x64" in a["name"]
    ]
    destination = ROOT / "runtime" / "llama"
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for asset in downloads:
        print("Downloading", asset["name"], flush=True)
        archive = ROOT / "runtime" / asset["name"]
        digest = hashlib.sha256()
        with requests.get(asset["browser_download_url"], stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            with archive.open("wb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    digest.update(chunk)
                    out.write(chunk)
        expected = asset.get("digest")
        if not expected or expected != "sha256:" + digest.hexdigest():
            raise RuntimeError("Release asset has no matching SHA-256 digest; refusing to extract")
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                name = Path(member.filename).name
                if name.endswith((".dll", ".exe", ".txt", ".md")) or name.startswith("LICENSE"):
                    (destination / name).write_bytes(zipped.read(member))
        records.append({"name": asset["name"], "sha256": digest.hexdigest()})
    (destination / "release.json").write_text(
        json.dumps({"tag": release["tag_name"], "assets": records}, indent=2)
    )
    if not (destination / "llama-server.exe").exists():
        raise RuntimeError("llama-server.exe missing")
    print("Runtime ready:", destination)


if __name__ == "__main__":
    main()
