"""Acceptance check for cross-device translation.

Two commands, one per machine. Both drive the real code path — the real OCR
engine, the real llama.cpp server, the real HTTP service and the real local
renderer. Only the input is synthetic: a generated fixture image, never a
real screenshot, so nothing user-owned is read, printed or written.

On the machine that owns the models:

    .venv\\Scripts\\python.exe scripts\\remote_check.py host --self-check

On the machine that will capture:

    .venv\\Scripts\\python.exe scripts\\remote_check.py client ^
        --url http://100.100.119.102:8765 --secret <printed by the host>
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.backend import LocalBackend  # noqa: E402
from screen_translator.core import CancellationToken, Config, merge_lines  # noqa: E402
from screen_translator.inference import InferenceCoordinator  # noqa: E402
from screen_translator.remote.access import AccessPolicy, generate_secret  # noqa: E402
from screen_translator.remote.client import (  # noqa: E402
    RemoteBackend,
    RemoteError,
    claim_pairing,
)
from screen_translator.remote.service import (  # noqa: E402
    RemoteService,
    ServiceState,
    TranslationService,
)
from screen_translator.remote.tailnet import (  # noqa: E402
    TailnetUnavailable,
    peer_route,
    read_status,
)
from screen_translator.tasks import TaskRunner  # noqa: E402

# Synthetic fixture: plain ASCII drawn with a vector font, not a screenshot.
FIXTURE_LINES = (
    "Release Checklist",
    "Open the settings window and confirm the shortcut.",
    "Select the input and output languages.",
    "The application keeps working without a network.",
)


def fixture_image() -> numpy.ndarray:
    """Draw the fixture as a BGR array the OCR engine can read."""
    image = numpy.full((260, 1100, 3), 245, numpy.uint8)
    for index, line in enumerate(FIXTURE_LINES):
        cv2.putText(
            image,
            line,
            (30, 60 + index * 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0 if index else 1.3,
            (24, 24, 24),
            2,
            cv2.LINE_AA,
        )
    return image


def elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)


def qt_application() -> QApplication:
    """Rendering needs one.

    ``OverlayRenderer`` measures text with ``QFontMetrics``, and Qt aborts the
    process at the C++ level if no application object exists — a failure no
    ``except`` clause can report.
    """
    return QApplication.instance() or QApplication([])


def run_client(url: str, secret: str, source: str, target: str) -> dict:
    """Health, warm-up, OCR, translate and local render against a host."""
    report: dict[str, object] = {"url": url, "source": source, "target": target, "steps": {}}
    steps: dict[str, object] = report["steps"]
    backend = RemoteBackend(url, secret)
    token = CancellationToken()

    def progress(text: str) -> None:
        print(f"    {text}", flush=True)

    try:
        started = time.monotonic()
        health = backend.health.refresh()
        steps["health"] = {
            "ms": elapsed_ms(started),
            "reachable": health.reachable,
            "ready": health.ready,
            "device": health.device,
            "model_id": health.model_id,
            "detail": health.detail,
        }
        print(f"[health] {health.describe()}", flush=True)
        if not health.ready:
            report["status"] = "host-not-ready"
            return report

        print("[warmup] loading the host models (first run can take minutes)", flush=True)
        started = time.monotonic()
        backend.ocr.warmup(source, token, progress)
        backend.translator.start(token, progress)
        steps["warmup"] = {"ms": elapsed_ms(started)}

        print("[ocr] recognising the fixture image", flush=True)
        started = time.monotonic()
        result = backend.ocr.recognize(fixture_image(), source, token, progress)
        steps["ocr"] = {
            "ms": elapsed_ms(started),
            "lines": len(result.lines),
            "detected_language": result.detected_language,
            "device": result.device,
        }
        blocks = merge_lines(result.lines)
        if not blocks:
            report["status"] = "no-text-recognised"
            return report

        print(f"[translate] {len(blocks)} block(s) {source} -> {target}", flush=True)
        started = time.monotonic()
        translated = backend.translator.translate(
            blocks, token, progress, source, target, result.detected_language
        )
        steps["translate"] = {
            "ms": elapsed_ms(started),
            "blocks": len(translated),
            "metrics": backend.translator.last_metrics,
        }

        # Rendering stays local: this is what proves the reply carried enough
        # to composite with this machine's own DPI and fonts.
        from screen_translator.graphics import OverlayRenderer, from_array

        qt_application()
        started = time.monotonic()
        original = from_array(cv2.cvtColor(fixture_image(), cv2.COLOR_BGR2RGB))
        rendered = OverlayRenderer().render(original, translated, token, target)
        steps["render"] = {
            "ms": elapsed_ms(started),
            "size": [rendered.width(), rendered.height()],
            "drawn_blocks": sum(1 for item in translated if item.draw_rect),
        }

        report["route"] = peer_route(url.split("//", 1)[-1].split(":", 1)[0])
        report["translations"] = [item.text for item in translated]
        report["status"] = "ok"
        return report
    except Exception as error:
        report["status"] = f"error:{type(error).__name__}"
        report["error"] = str(error)
        return report
    finally:
        backend.stop()


def command_client(args: argparse.Namespace) -> int:
    report = run_client(args.url, args.secret, args.source, args.target)
    if report["status"] == "ok":
        print("\n[result] fixture translated:", flush=True)
        for line in report["translations"]:
            print(f"    {line}", flush=True)
    write_report(args.report, report)
    print(
        json.dumps({k: v for k, v in report.items() if k != "translations"}, ensure_ascii=False),
        flush=True,
    )
    return 0 if report["status"] == "ok" else 1


def command_host(args: argparse.Namespace) -> int:
    config = Config.load()
    model_dir = args.model_dir or config.model_dir
    backend = LocalBackend(
        Config(model_dir=model_dir, allow_cpu=args.allow_cpu, translation_model=config.translation_model)
    )
    if not backend.ready():
        print(f"[host] not ready: {backend.describe()}", flush=True)
        return 1

    secret = args.secret or config.service_token or generate_secret()
    inference = InferenceCoordinator(lambda: backend.translator)
    tasks = TaskRunner()
    service = RemoteService(
        TranslationService(
            ocr_provider=lambda: backend.ocr,
            inference=inference,
            ready_provider=backend.ready,
            model_provider=lambda: config.translation_model,
        ),
        AccessPolicy(secret, frozenset(args.allow or ())),
        tasks,
        address=args.address,
        port=args.port,
    )
    try:
        status = service.start()
    except TailnetUnavailable as error:
        print(f"[host] {error}", flush=True)
        return 1
    if status.state != ServiceState.RUNNING:
        print(f"[host] failed to start: {status.detail}", flush=True)
        return 1

    print(f"[host] listening on {status.url}", flush=True)
    print(f"[host] model  {config.translation_model}", flush=True)
    if args.offer:
        offer = service.broker.open_offer()
        service.broker.host_label = platform.node()
        print(f"[host] pairing code {offer.code} (valid {offer.ttl:.0f}s)", flush=True)
        print("[host] on the other device: remote_check.py pair --url <this URL> --code <code>", flush=True)
    else:
        print(f"[host] secret {secret}", flush=True)
        print("[host] copy the URL and the secret into the other device's settings", flush=True)
    exit_code = 0
    try:
        if args.self_check:
            # Against the address actually bound, not loopback: the service
            # binds one interface, so a loopback probe would fail even when
            # everything is working.
            print(f"\n[self-check] running the whole path against {status.url}", flush=True)
            report = run_client(status.url, secret, args.source, args.target)
            write_report(args.report, report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            if report["status"] != "ok":
                return 1
            print("[self-check] passed\n", flush=True)
        deadline = time.monotonic() + args.duration if args.duration else None
        print(
            "[host] serving; press Ctrl+C to stop"
            if deadline is None
            else f"[host] serving for {args.duration:.0f}s",
            flush=True,
        )
        while deadline is None or time.monotonic() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[host] stopping", flush=True)
    finally:
        service.stop()
        backend.stop()
        tasks.shutdown(timeout=5)
    return exit_code


def command_pair(args: argparse.Namespace) -> int:
    """Exchange a code for this device's own secret, the way the UI does."""
    url = args.url
    if not url and args.peer:
        peer = read_status().find(args.peer) or next(
            (item for item in read_status().peers if item.label == args.peer), None
        )
        if peer is None:
            print(f"[pair] no tailnet device named {args.peer}", flush=True)
            return 1
        url = f"http://{peer.address}:{args.port}"
    if not url:
        print("[pair] give --url or --peer", flush=True)
        return 1
    try:
        grant = claim_pairing(url, args.code, label=platform.node())
    except RemoteError as error:
        print(f"[pair] {error}", flush=True)
        return 1
    print(f"[pair] paired with {grant.host_label or url}", flush=True)
    print(f"[pair] device_id {grant.device_id}", flush=True)
    print(f"[pair] secret    {grant.secret}", flush=True)
    print("[pair] put the URL and this secret into this device's settings", flush=True)
    write_report(args.report, {"status": "ok", "url": url, "device_id": grant.device_id})
    return 0


def command_devices(args: argparse.Namespace) -> int:
    """List what the device picker would show, without a window."""
    try:
        status = read_status()
    except TailnetUnavailable as error:
        print(f"[devices] {error}", flush=True)
        return 1
    if status.self_peer is not None:
        print(f"[devices] self {status.self_peer.label} {status.self_peer.address}", flush=True)
    for peer in status.peers:
        print(f"[devices] {peer.address:<16} {peer.label:<24} {peer.describe()}", flush=True)
    return 0


def write_report(path: Path | None, report: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="zh-Hans")
    parser.add_argument("--report", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    host = commands.add_parser("host", help="serve this machine's models to the tailnet")
    host.add_argument("--address", default="auto")
    host.add_argument("--port", type=int, default=8765)
    host.add_argument("--secret")
    host.add_argument("--allow", action="append", metavar="ADDRESS")
    host.add_argument("--model-dir")
    host.add_argument("--allow-cpu", action="store_true")
    host.add_argument("--self-check", action="store_true")
    host.add_argument("--duration", type=float, default=0.0)
    host.add_argument("--offer", action="store_true", help="print a pairing code instead of the secret")
    host.set_defaults(handler=command_host)

    client = commands.add_parser("client", help="drive a remote host from this machine")
    client.add_argument("--url", required=True)
    client.add_argument("--secret", required=True)
    client.set_defaults(handler=command_client)

    pair = commands.add_parser("pair", help="claim a per-device secret with a pairing code")
    pair.add_argument("--url", help="http://<host address>:<port>")
    pair.add_argument("--peer", help="tailnet device name or address, instead of --url")
    pair.add_argument("--port", type=int, default=8765)
    pair.add_argument("--code", required=True)
    pair.set_defaults(handler=command_pair)

    devices = commands.add_parser("devices", help="list tailnet devices")
    devices.set_defaults(handler=command_devices)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
