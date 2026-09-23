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
from collections.abc import Mapping
from dataclasses import dataclass
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


ROUTE_DIRECT = "direct"
ROUTE_RELAY = "relay"
ROUTE_UNKNOWN = "unknown"

_OS_NAMES = {
    "windows": "Windows",
    "macOS": "macOS",
    "linux": "Linux",
    "iOS": "iOS",
    "android": "Android",
}


@dataclass(frozen=True)
class TailnetPeer:
    """One device on the tailnet, as the picker needs to show it."""

    host_name: str
    dns_name: str
    address: str
    operating_system: str = ""
    online: bool = False
    route: str = ROUTE_UNKNOWN
    node_id: str = ""

    @property
    def label(self) -> str:
        """What to show in a list. The host name is what the user named it."""
        return self.host_name or self.dns_name or self.address

    def describe(self) -> str:
        parts = [_OS_NAMES.get(self.operating_system, self.operating_system)]
        parts.append("在线" if self.online else "离线")
        if self.online and self.route == ROUTE_RELAY:
            # Worth saying: a relayed connection works but pushes every
            # screenshot through a DERP server, which is the usual
            # explanation for a slow remote capture.
            parts.append("中继")
        elif self.online and self.route == ROUTE_DIRECT:
            parts.append("直连")
        return " · ".join(part for part in parts if part)


@dataclass(frozen=True)
class TailnetStatus:
    self_peer: TailnetPeer | None = None
    peers: tuple[TailnetPeer, ...] = ()
    magic_dns_suffix: str = ""

    def find(self, address: str) -> TailnetPeer | None:
        for peer in self.peers:
            if peer.address == address:
                return peer
        return None


def classify_route(peer: Mapping[str, object]) -> str:
    """Classify one peer entry as ``direct``, ``relay`` or ``unknown``.

    ``CurAddr`` is checked first and that order matters. ``Relay`` names the
    peer's *home* DERP region and is populated even on a direct connection, so
    reading it first reports every direct peer as relayed. Only a non-empty
    ``CurAddr`` means traffic is actually flowing peer to peer. See
    ``tests/data/tailscale_status.json`` for a recorded example of the two
    fields being set at once.
    """
    if peer.get("CurAddr"):
        return ROUTE_DIRECT
    if peer.get("Relay"):
        return ROUTE_RELAY
    return ROUTE_UNKNOWN


def _peer_address(peer: Mapping[str, object]) -> str:
    addresses = peer.get("TailscaleIPs")
    if not isinstance(addresses, list):
        return ""
    for value in addresses:
        if isinstance(value, str) and is_tailnet_address(value):
            return value
    return ""


def _decode_peer(payload: object) -> TailnetPeer | None:
    if not isinstance(payload, Mapping):
        return None
    address = _peer_address(payload)
    if not address:
        # No IPv4 in the CGNAT range means nothing here can reach it.
        return None
    dns_name = payload.get("DNSName")
    return TailnetPeer(
        host_name=str(payload.get("HostName") or ""),
        dns_name=str(dns_name or "").rstrip("."),
        address=address,
        operating_system=str(payload.get("OS") or ""),
        online=bool(payload.get("Online")),
        route=classify_route(payload),
        node_id=str(payload.get("PublicKey") or ""),
    )


def parse_status(document: object) -> TailnetStatus:
    """Turn ``tailscale status --json`` into the devices a user can pick.

    Pure, so the device picker is testable against a recorded document
    rather than whatever tailnet the developer happens to be on.
    """
    if not isinstance(document, Mapping):
        return TailnetStatus()
    peers = document.get("Peer")
    decoded = []
    if isinstance(peers, Mapping):
        for payload in peers.values():
            peer = _decode_peer(payload)
            if peer is not None:
                decoded.append(peer)
    # Online first, then by the name the user gave the machine.
    decoded.sort(key=lambda peer: (not peer.online, peer.label.lower()))
    return TailnetStatus(
        self_peer=_decode_peer(document.get("Self")),
        peers=tuple(decoded),
        magic_dns_suffix=str(document.get("MagicDNSSuffix") or ""),
    )


def parse_peer_route(document: object, peer_address: str) -> str:
    """Classify a peer connection. A thin wrapper so there is one parser."""
    peer = parse_status(document).find(peer_address)
    return peer.route if peer is not None else ROUTE_UNKNOWN


def read_status() -> TailnetStatus:
    """Ask Tailscale who else is on the tailnet. Raises `TailnetUnavailable`."""
    try:
        document = json.loads(_run(["status", "--json"]))
    except json.JSONDecodeError as error:
        raise TailnetUnavailable("tailscale status 返回的不是合法 JSON") from error
    return parse_status(document)


def peer_route(peer_address: str) -> str:
    """Best-effort route classification; never raises."""
    try:
        return read_status().find(peer_address).route
    except (TailnetUnavailable, AttributeError) as error:
        LOGGER.debug("Tailscale route lookup failed: %s", type(error).__name__)
        return ROUTE_UNKNOWN
