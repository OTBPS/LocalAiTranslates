"""Reading the local Tailscale state.

Kept apart from :mod:`access` so that the policy stays a pure function while
everything that shells out lives here.  The parsing helpers take a decoded
document rather than running anything, which is what makes them testable
without Tailscale installed.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .access import is_tailnet_address

LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 5.0

_WINDOWS_LOCATIONS = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)


class TailnetUnavailable(RuntimeError):
    """Raised when the local Tailscale address cannot be determined."""


def find_executable() -> Path | None:
    found = shutil.which("tailscale")
    if found:
        return Path(found)
    for candidate in _WINDOWS_LOCATIONS:
        path = Path(os.path.expandvars(candidate))
        if path.is_file():
            return path
    return None


def _run(arguments: list[str]) -> str:
    executable = find_executable()
    if executable is None:
        raise TailnetUnavailable("未找到 tailscale 命令，请确认 Tailscale 已安装")
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            creationflags=creation_flags,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TailnetUnavailable(f"无法执行 tailscale 命令（{type(error).__name__}）") from error
    if completed.returncode != 0:
        raise TailnetUnavailable("tailscale 命令返回错误，请确认已登录并连接")
    return completed.stdout


def parse_addresses(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if is_tailnet_address(line.strip())]


def discover_address() -> str:
    """Return this device's Tailscale IPv4 address.

    Failure is explicit on purpose.  Falling back to ``0.0.0.0`` would expose
    the translation service on every network the host is attached to, so the
    service refuses to start and asks the user for an address instead.
    """
    addresses = parse_addresses(_run(["ip", "-4"]))
    if not addresses:
        raise TailnetUnavailable("Tailscale 未分配 IPv4 地址，请确认已登录并连接")
    return addresses[0]


def parse_peer_route(document: object, peer_address: str) -> str:
    """Classify a peer connection as ``direct``, ``relay`` or ``unknown``.

    A relayed connection still works but pushes every screenshot through a
    DERP server, which is the usual explanation for a slow remote capture.

    ``CurAddr`` is checked first and that order matters. ``Relay`` names the
    peer's *home* DERP region and is populated even on a direct connection, so
    reading it first reports every direct peer as relayed. Only a non-empty
    ``CurAddr`` means traffic is actually flowing peer to peer. See
    ``tests/data/tailscale_status.json`` for a recorded example of the two
    fields being set at once.
    """
    if not isinstance(document, dict):
        return "unknown"
    peers = document.get("Peer")
    if not isinstance(peers, dict):
        return "unknown"
    for peer in peers.values():
        if not isinstance(peer, dict):
            continue
        addresses = peer.get("TailscaleIPs")
        if not isinstance(addresses, list) or peer_address not in addresses:
            continue
        if peer.get("CurAddr"):
            return "direct"
        if peer.get("Relay"):
            return "relay"
        return "unknown"
    return "unknown"


def peer_route(peer_address: str) -> str:
    """Best-effort route classification; never raises."""
    try:
        return parse_peer_route(json.loads(_run(["status", "--json"])), peer_address)
    except (TailnetUnavailable, json.JSONDecodeError) as error:
        LOGGER.debug("Tailscale route lookup failed: %s", type(error).__name__)
        return "unknown"
