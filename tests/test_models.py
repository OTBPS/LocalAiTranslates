import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from screen_translator.core import CancellationToken, Cancelled
from screen_translator.models import TRANSLATION_MODELS, download_file, install_models, models_ready


@pytest.fixture
def server():
    payload = b"abcdef0123456789" * 1000
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            ranges.append(offset)
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(len(payload) - offset))
            self.send_header("Content-Range", f"bytes {offset}-{len(payload) - 1}/{len(payload)}")
            self.end_headers()
            self.wfile.write(payload[offset:])

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}/file", payload, ranges
    http.shutdown()
    http.server_close()


def test_resume_and_hash(server, tmp_path):
    url, payload, ranges = server
    dest = tmp_path / "model.gguf"
    dest.with_suffix(".gguf.part").write_bytes(payload[:3000])
    download_file(
        url, dest, hashlib.sha256(payload).hexdigest(), len(payload), CancellationToken(), lambda *args: None
    )
    assert ranges == [3000]
    assert dest.read_bytes() == payload


def test_cancel_does_not_publish(server, tmp_path):
    url, payload, _ = server
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        download_file(
            url,
            tmp_path / "model",
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            token,
            lambda *args: None,
        )
    assert not (tmp_path / "model").exists()


def test_invalid_manifest(tmp_path):
    assert not models_ready(tmp_path)


def test_selected_model_readiness_ignores_unselected_model(tmp_path):
    selected = TRANSLATION_MODELS["qwen3-8b-q5-k-m"]
    records = []
    for name in (
        selected.filename,
        "PP-OCRv5_mobile_det/inference.pdiparams",
        "PP-OCRv5_mobile_rec/inference.pdiparams",
        "korean_PP-OCRv5_mobile_rec/inference.pdiparams",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ready")
        records.append({"path": name, "size": 5, "sha256": "unused"})
    records.append({"path": "Qwen3-14B-Q5_K_M.gguf", "size": 999, "sha256": "unused"})
    (tmp_path / "manifest.json").write_text(json.dumps(records), encoding="utf-8")

    assert models_ready(tmp_path, selected.model_id)
    assert not models_ready(tmp_path, "qwen3-14b-q5-k-m")


def test_installing_second_model_preserves_first_manifest_record(tmp_path):
    original = TRANSLATION_MODELS["qwen3-14b-q5-k-m"]
    selected = TRANSLATION_MODELS["qwen3-8b-q5-k-m"]
    (tmp_path / original.filename).write_bytes(b"14b")
    (tmp_path / "manifest.json").write_text(
        json.dumps([{"path": original.filename, "size": 3, "sha256": "14b"}]), encoding="utf-8"
    )

    def fake_fetch(repo, root, _select, _token, _progress):
        name = selected.filename if repo == selected.repo else "inference.pdiparams"
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"new")
        return [{"path": name, "size": 3, "sha256": "new"}]

    with patch("screen_translator.models.fetch_repo", side_effect=fake_fetch):
        install_models(tmp_path, CancellationToken(), lambda *_args: None, selected.model_id)

    paths = {record["path"] for record in json.loads((tmp_path / "manifest.json").read_text())}
    assert original.filename in paths
    assert selected.filename in paths
    assert (tmp_path / original.filename).read_bytes() == b"14b"
    (tmp_path / "manifest.json").write_text("[]")
    assert not models_ready(tmp_path)
