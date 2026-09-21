"""Fetch open-source localisation catalogs for the gold set's harder layers.

Three corpora, each with an explicit licence and a pinned commit:

  godot-editor-l10n   MIT               software UI strings
  godot-docs-l10n     CC-BY-3.0         continuous documentation paragraphs
  wesnoth             GPL-2.0-or-later  game dialogue and narrative

Every file is downloaded at an exact commit, hashed, and recorded with its
repository, path and licence so each derived gold record can cite its origin.
Results from these open corpora are reported separately from FLORES, and both
separately from the product evaluation sets.

    python -m scripts.training.fetch_l10n_corpora
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests

from scripts.training.training_paths import workspace_path

SOURCES = {
    "godot-editor": {
        "repository": "godotengine/godot-editor-l10n",
        "commit": "00d5641a9ebfc5f336c8c325c408070ce89b71df",
        "license": "MIT",
        "attribution": "Godot Engine editor translations, MIT, godotengine/godot-editor-l10n",
        "layer": "software_ui",
        # Godot uses BCP-47 style script subtags, not zh_CN.
        "files": ["editor/zh_Hans.po", "properties/zh_Hans.po"],
    },
    "godot-docs": {
        "repository": "godotengine/godot-docs-l10n",
        "commit": "d9933c37775ac255ddb9977b02a173305c3b5b3c",
        "license": "CC-BY-3.0",
        "attribution": "Godot Engine documentation translations, CC-BY-3.0, godotengine/godot-docs-l10n",
        "layer": "long_document",
        "files": [
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/01.project_setup.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/02.player_scene.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/03.coding_the_player.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/04.creating_the_enemy.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/05.the_main_game_scene.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/06.heads_up_display.po",
            "sphinx/po/zh_CN/LC_MESSAGES/getting_started/first_2d_game/07.finishing-up.po",
        ],
    },
    "wesnoth": {
        "repository": "wesnoth/wesnoth",
        "commit": "b4c3da5547c0c139bdfcafd749e331f1b4c52628",
        "license": "GPL-2.0-or-later",
        "attribution": "The Battle for Wesnoth, GPL-2.0-or-later, wesnoth/wesnoth",
        "layer": "game_dialogue",
        "files": [
            "po/wesnoth-httt/zh_CN.po",
            "po/wesnoth-ei/zh_CN.po",
            "po/wesnoth-did/zh_CN.po",
            "po/wesnoth-l/zh_CN.po",
        ],
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(session: requests.Session, source: dict, name: str, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        url = (
            f"https://raw.githubusercontent.com/{source['repository']}/"
            f"{source['commit']}/{name}"
        )
        response = session.get(url, timeout=300)
        response.raise_for_status()
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(response.content)
        os.replace(temporary, destination)
    return {
        "file": name,
        "path": str(destination),
        "sha256": sha256_file(destination),
        "bytes": destination.stat().st_size,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=workspace_path("cache/l10n"))
    parser.add_argument("--source", action="append", choices=sorted(SOURCES), default=None)
    args = parser.parse_args(argv)

    session = requests.Session()
    session.trust_env = False
    wanted = args.source or sorted(SOURCES)
    manifest = {"schema_version": 1, "sources": {}}
    for name in wanted:
        source = SOURCES[name]
        base = args.output_dir / name
        files = [fetch(session, source, path, base / path) for path in source["files"]]
        manifest["sources"][name] = {
            "repository": f"https://github.com/{source['repository']}",
            "commit": source["commit"],
            "license": source["license"],
            "attribution": source["attribution"],
            "layer": source["layer"],
            "files": files,
        }
        print(f"{name}: {len(files)} 个文件, {sum(f['bytes'] for f in files)} 字节", flush=True)

    manifest["reporting_note"] = (
        "open-source localisation corpora; report separately from FLORES and from the "
        "product evaluation sets so public data cannot mask real capability"
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
